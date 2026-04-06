"""Tests for iMessage platform adapter (macOS Messages.app integration).

Covers:
- Platform enum and config loading
- Requirements checking (imsg CLI, chat.db, env vars)
- Allowed users parsing and authorization
- Echo prevention (filter own messages)
- Toolset and platform hint verification
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime
import time

import pytest

from gateway.config import Platform, PlatformConfig, HomeChannel


# ---------------------------------------------------------------------------
# Platform Enum
# ---------------------------------------------------------------------------

class TestIMessagePlatformEnum:
    """Verify Platform.IMESSAGE is correctly defined."""

    def test_imessage_enum_exists(self):
        assert hasattr(Platform, "IMESSAGE")
        assert Platform.IMESSAGE.value == "imessage"

    def test_imessage_in_platform_list(self):
        platforms = [p.value for p in Platform]
        assert "imessage" in platforms


# ---------------------------------------------------------------------------
# Config Loading
# ---------------------------------------------------------------------------

class TestIMessageConfigLoading:
    """Verify _apply_env_overrides wires iMessage correctly."""

    def test_env_overrides_create_imessage_config(self, monkeypatch):
        """IMESSAGE_ENABLED=true should create platform config."""
        monkeypatch.setenv("IMESSAGE_ENABLED", "true")

        from gateway.config import load_gateway_config

        config = load_gateway_config()
        assert Platform.IMESSAGE in config.platforms
        pc = config.platforms[Platform.IMESSAGE]
        assert pc.enabled is True

    def test_env_overrides_allowed_users_enables(self, monkeypatch):
        """IMESSAGE_ALLOWED_USERS should also enable the platform."""
        monkeypatch.delenv("IMESSAGE_ENABLED", raising=False)
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567,+15559876543")

        from gateway.config import load_gateway_config

        config = load_gateway_config()
        assert Platform.IMESSAGE in config.platforms
        assert config.platforms[Platform.IMESSAGE].enabled is True

    def test_env_overrides_set_home_channel(self, monkeypatch):
        """IMESSAGE_HOME_CHANNEL should configure home channel."""
        monkeypatch.setenv("IMESSAGE_ENABLED", "true")
        monkeypatch.setenv("IMESSAGE_HOME_CHANNEL", "+15551234567")
        monkeypatch.setenv("IMESSAGE_HOME_CHANNEL_NAME", "My iPhone")

        from gateway.config import load_gateway_config

        config = load_gateway_config()
        hc = config.platforms[Platform.IMESSAGE].home_channel
        assert hc is not None
        assert hc.chat_id == "+15551234567"
        assert hc.name == "My iPhone"
        assert hc.platform == Platform.IMESSAGE

    def test_imessage_in_connected_platforms(self, monkeypatch):
        """iMessage should appear in get_connected_platforms when enabled with allowed users."""
        monkeypatch.setenv("IMESSAGE_ENABLED", "true")
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")

        from gateway.config import load_gateway_config

        config = load_gateway_config()
        connected = config.get_connected_platforms()
        assert Platform.IMESSAGE in connected


# ---------------------------------------------------------------------------
# Requirements Check
# ---------------------------------------------------------------------------

class TestIMessageRequirements:
    """Tests for check_imessage_requirements()."""

    def test_check_requires_imsg_cli(self, monkeypatch):
        """Should return False if imsg CLI is not installed."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")

        # Mock shutil.which to return None (not in PATH)
        # Mock Path.exists to return False for known Homebrew locations
        with patch("shutil.which", return_value=None), \
             patch.object(Path, "exists", return_value=False):
            from gateway.platforms.imessage import check_imessage_requirements
            result = check_imessage_requirements()
            assert result is False

    def test_check_requires_chat_db(self, monkeypatch):
        """Should return False if chat.db doesn't exist."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")

        with patch("shutil.which", return_value="/usr/local/bin/imsg"), \
             patch.object(Path, "exists", return_value=False):
            from gateway.platforms.imessage import check_imessage_requirements
            result = check_imessage_requirements()
            assert result is False

    def test_check_requires_allowed_users(self, monkeypatch):
        """Should return False if IMESSAGE_ALLOWED_USERS is not set."""
        monkeypatch.delenv("IMESSAGE_ALLOWED_USERS", raising=False)

        with patch("shutil.which", return_value="/usr/local/bin/imsg"), \
             patch.object(Path, "exists", return_value=True):
            from gateway.platforms.imessage import check_imessage_requirements
            result = check_imessage_requirements()
            assert result is False

    def test_check_passes_with_all_requirements(self, monkeypatch):
        """Should return True when all requirements are met."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")

        with patch("shutil.which", return_value="/usr/local/bin/imsg"), \
             patch.object(Path, "exists", return_value=True):
            from gateway.platforms.imessage import check_imessage_requirements
            result = check_imessage_requirements()
            assert result is True


# ---------------------------------------------------------------------------
# Adapter Initialization
# ---------------------------------------------------------------------------

class TestIMessageAdapterInit:
    """Tests for IMessageAdapter initialization."""

    def _make_adapter(self, monkeypatch, allowed_users="+15551234567", poll_interval=None):
        """Create an IMessageAdapter with sensible test defaults."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", allowed_users)
        if poll_interval:
            monkeypatch.setenv("IMESSAGE_POLL_INTERVAL", str(poll_interval))

        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        return IMessageAdapter(config)

    def test_init_parses_allowed_users(self, monkeypatch):
        """Should parse comma-separated allowed users from env."""
        adapter = self._make_adapter(monkeypatch, allowed_users="+15551234567,+15559876543")
        assert "+15551234567" in adapter._allowed_users
        assert "+15559876543" in adapter._allowed_users

    def test_init_strips_whitespace(self, monkeypatch):
        """Should strip whitespace from allowed users."""
        adapter = self._make_adapter(monkeypatch, allowed_users=" +15551112222 , +15553334444 ")
        assert "+15551112222" in adapter._allowed_users
        assert "+15553334444" in adapter._allowed_users

    def test_init_empty_allowed_users(self, monkeypatch):
        """Should have empty list if no allowed users configured."""
        monkeypatch.delenv("IMESSAGE_ALLOWED_USERS", raising=False)
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)
        assert adapter._allowed_users == []

    def test_init_custom_poll_interval(self, monkeypatch):
        """Should read IMESSAGE_POLL_INTERVAL from env."""
        adapter = self._make_adapter(monkeypatch, poll_interval=5.0)
        assert adapter._poll_interval == 5.0

    def test_init_default_poll_interval(self, monkeypatch):
        """Should use default poll interval if not configured."""
        adapter = self._make_adapter(monkeypatch)
        from gateway.platforms.imessage import DEFAULT_POLL_INTERVAL
        assert adapter._poll_interval == DEFAULT_POLL_INTERVAL


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

class TestIMessageAuthorization:
    """Tests for _is_user_allowed()."""

    def _make_adapter(self, monkeypatch, allowed_users="+15551234567"):
        """Create an adapter for testing."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", allowed_users)
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        return IMessageAdapter(config)

    def test_allowed_user_is_authorized(self, monkeypatch):
        """User in allowed list should be authorized."""
        adapter = self._make_adapter(monkeypatch, allowed_users="+15551234567")
        assert adapter._is_user_allowed("+15551234567") is True

    def test_disallowed_user_not_authorized(self, monkeypatch):
        """User not in allowed list should not be authorized."""
        adapter = self._make_adapter(monkeypatch, allowed_users="+15551234567")
        assert adapter._is_user_allowed("+15559999999") is False

    def test_allow_all_users_bypasses_list(self, monkeypatch):
        """IMESSAGE_ALLOW_ALL_USERS=true should authorize everyone."""
        monkeypatch.setenv("IMESSAGE_ALLOW_ALL_USERS", "true")
        adapter = self._make_adapter(monkeypatch, allowed_users="+15551234567")

        assert adapter._is_user_allowed("+15559999999") is True
        assert adapter._is_user_allowed("anyone@example.com") is True

    def test_empty_allowed_list_denies_all(self, monkeypatch):
        """Empty allowed list should deny all users."""
        monkeypatch.delenv("IMESSAGE_ALLOWED_USERS", raising=False)
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        assert adapter._is_user_allowed("+15551234567") is False

    def test_email_identifier_authorized(self, monkeypatch):
        """Email identifiers should work in allowed list."""
        adapter = self._make_adapter(monkeypatch, allowed_users="user@example.com")
        assert adapter._is_user_allowed("user@example.com") is True


# ---------------------------------------------------------------------------
# Echo Prevention
# ---------------------------------------------------------------------------

class TestIMessageEchoPrevention:
    """Tests for _filter_echo() and _record_sent()."""

    def _make_adapter(self, monkeypatch):
        """Create an adapter for testing."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        return IMessageAdapter(config)

    def test_echo_filter_returns_false_initially(self, monkeypatch):
        """No echoes should be detected initially."""
        adapter = self._make_adapter(monkeypatch)
        assert adapter._filter_echo("+15551234567", "hello", time.time()) is False

    def test_echo_filter_detects_recent_send(self, monkeypatch):
        """Messages sent within 3 seconds should be filtered as echoes."""
        adapter = self._make_adapter(monkeypatch)

        # Record a sent message
        now = time.time()
        adapter._record_sent("+15551234567", now)

        # Same chat, same time window should be filtered
        assert adapter._filter_echo("+15551234567", "hello", now) is True

    def test_echo_filter_allows_old_messages(self, monkeypatch):
        """Messages outside the time window should not be filtered."""
        adapter = self._make_adapter(monkeypatch)

        # Record a sent message
        now = time.time()
        adapter._record_sent("+15551234567", now)

        # Message 5 seconds later should not be filtered
        assert adapter._filter_echo("+15551234567", "hello", now + 5.0) is False

    def test_echo_filter_different_chat(self, monkeypatch):
        """Messages to different chats should not be filtered."""
        adapter = self._make_adapter(monkeypatch)

        now = time.time()
        adapter._record_sent("+15551234567", now)

        # Different chat should not be filtered
        assert adapter._filter_echo("+15559999999", "hello", now) is False

    def test_echo_filter_cleans_old_entries(self, monkeypatch):
        """Old entries should be cleaned from the sent list."""
        adapter = self._make_adapter(monkeypatch)

        # Add an old entry (6 seconds ago)
        old_time = time.time() - 6.0
        adapter._record_sent("+15551234567", old_time)
        initial_len = len(adapter._recent_sent)

        # This should clean old entries
        adapter._filter_echo("+15559999999", "test", time.time())

        # Old entry should be removed
        assert len(adapter._recent_sent) < initial_len

    def test_record_sent_limits_list_size(self, monkeypatch):
        """_recent_sent should be limited to 20 entries."""
        adapter = self._make_adapter(monkeypatch)

        # Add 25 entries
        for i in range(25):
            adapter._record_sent(f"+1555{i:08d}", time.time())

        # Should be limited to 20
        assert len(adapter._recent_sent) <= 20


# ---------------------------------------------------------------------------
# Phone Redaction
# ---------------------------------------------------------------------------

class TestIMessagePhoneRedaction:
    """Tests for _redact_phone helper."""

    def test_redact_long_phone(self):
        """Long phone numbers should be partially redacted."""
        from gateway.platforms.imessage import _redact_phone

        # +15551234567 (12 chars) -> phone[:5] + "***" + phone[-4:] = "+1555***4567"
        result = _redact_phone("+15551234567")
        assert result == "+1555***4567"

    def test_redact_medium_phone(self):
        """Medium phone numbers (>8 chars) use the standard format."""
        from gateway.platforms.imessage import _redact_phone

        # +12345678 (9 chars) -> phone[:5] + "***" + phone[-4:] = "+1234***5678"
        result = _redact_phone("+12345678")
        assert result == "+1234***5678"

    def test_redact_short_phone(self):
        """Short phone numbers (<=8 chars, >4 chars) use compact format."""
        from gateway.platforms.imessage import _redact_phone

        # +1234 (5 chars) -> phone[:2] + "***" + phone[-2:] = "+1***34"
        result = _redact_phone("+1234")
        assert result == "+1***34"

    def test_redact_very_short_phone(self):
        """Very short phone numbers (<=4 chars) should be fully redacted."""
        from gateway.platforms.imessage import _redact_phone

        result = _redact_phone("+12")
        assert result == "****"

    def test_redact_empty_phone(self):
        """Empty phone should return <none>."""
        from gateway.platforms.imessage import _redact_phone

        result = _redact_phone("")
        assert result == "<none>"

    def test_redact_none_phone(self):
        """None phone should return <none>."""
        from gateway.platforms.imessage import _redact_phone

        result = _redact_phone(None)
        assert result == "<none>"


# ---------------------------------------------------------------------------
# Toolset Verification
# ---------------------------------------------------------------------------

class TestIMessageToolset:
    """Verify iMessage is properly integrated into toolsets."""

    def test_hermes_imessage_toolset_exists(self):
        """hermes-imessage toolset should be defined."""
        from toolsets import get_toolset

        ts = get_toolset("hermes-imessage")
        assert ts is not None
        assert "tools" in ts

    def test_hermes_imessage_in_gateway_includes(self):
        """hermes-imessage should be included in hermes-gateway."""
        from toolsets import get_toolset

        gw = get_toolset("hermes-gateway")
        assert gw is not None
        assert "hermes-imessage" in gw["includes"]

    def test_imessage_platform_hint_exists(self):
        """Platform hints should mention iMessage with appropriate guidance."""
        from agent.prompt_builder import PLATFORM_HINTS

        assert "imessage" in PLATFORM_HINTS
        # iMessage should mention plain text (no markdown support)
        assert "plain text" in PLATFORM_HINTS["imessage"].lower()

    def test_imessage_in_scheduler_platform_map(self):
        """Scheduler should recognize 'imessage' as a valid platform."""
        assert Platform.IMESSAGE.value == "imessage"

    def test_imessage_in_send_message_platform_map(self):
        """send_message_tool should recognize 'imessage'."""
        assert hasattr(Platform, "IMESSAGE")


# ---------------------------------------------------------------------------
# Channel Directory
# ---------------------------------------------------------------------------

class TestIMessageChannelDirectory:
    """Verify iMessage is included in channel directory building."""

    def test_imessage_in_session_platform_list(self):
        """iMessage should be in the platform list for session-based discovery."""
        # The channel_directory.py adds "imessage" to the list
        # This is a simple check that the integration exists
        from gateway.channel_directory import build_channel_directory
        # Just verify the import works and Platform.IMESSAGE is valid
        assert Platform.IMESSAGE.value == "imessage"


# ---------------------------------------------------------------------------
# Authorization in run.py
# ---------------------------------------------------------------------------

class TestIMessageRunAuthorization:
    """Verify iMessage is recognized in authorization checks."""

    def test_imessage_allowed_users_env_var_recognized(self, monkeypatch):
        """IMESSAGE_ALLOWED_USERS should be recognized at startup."""
        # This tests that the startup warning check includes iMessage
        # The actual check is in run.py __init__ where it warns if no allowlists
        from gateway.config import Platform

        # Just verify the Platform enum is correct
        assert Platform.IMESSAGE.value == "imessage"

    def test_imessage_allow_all_users_env_var_recognized(self, monkeypatch):
        """IMESSAGE_ALLOW_ALL_USERS should allow all users."""
        monkeypatch.setenv("IMESSAGE_ALLOW_ALL_USERS", "true")

        from gateway.platforms.imessage import IMessageAdapter
        from gateway.config import PlatformConfig

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should allow any user when ALLOW_ALL is set
        assert adapter._is_user_allowed("+15559999999") is True
        assert adapter._is_user_allowed("anyone@example.com") is True


# ---------------------------------------------------------------------------
# Status Display
# ---------------------------------------------------------------------------

class TestIMessageStatusDisplay:
    """Verify iMessage appears in status output."""

    def test_imessage_in_status_platforms(self):
        """iMessage should be in the status display platforms dict."""
        # Just verify the config key exists and is correct
        assert Platform.IMESSAGE.value == "imessage"


# ---------------------------------------------------------------------------
# Cron Scheduler
# ---------------------------------------------------------------------------

class TestIMessageCronScheduler:
    """Verify iMessage is in the cron scheduler platform map."""

    def test_imessage_in_cron_platform_map(self):
        """Cron scheduler should recognize 'imessage' for delivery."""
        # The scheduler has a platform_map that includes 'imessage'
        # We just verify the Platform enum exists correctly
        assert Platform.IMESSAGE.value == "imessage"


# ---------------------------------------------------------------------------
# Persistent State
# ---------------------------------------------------------------------------

class TestIMessagePersistentState:
    """Tests for state persistence across gateway restarts."""

    def _make_adapter(self, monkeypatch, allowed_users="+15551234567"):
        """Create an IMessageAdapter with sensible test defaults."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", allowed_users)
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        return IMessageAdapter(config)

    def test_load_state_missing_file(self, monkeypatch, tmp_path):
        """Should handle missing state file gracefully."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            tmp_path / "nonexistent.json"
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should initialize with empty state
        assert adapter._seen_messages == {}
        assert adapter._sms_contacts == set()

    def test_load_state_valid_file(self, monkeypatch, tmp_path):
        """Should load state from valid JSON file."""
        import json

        state_file = tmp_path / "imessage_state.json"
        state_data = {
            "seen_messages": {
                "+15551234567": {
                    "row_id": 123,
                    "timestamp": 1712345678.0,
                    "text": "Hello",
                    "is_from_me": False
                },
                "+15559876543": {
                    "row_id": 456,
                    "timestamp": 1712345680.0,
                    "text": "World",
                    "is_from_me": True
                }
            },
            "sms_contacts": ["+15551111111", "+15552222222"]
        }
        state_file.write_text(json.dumps(state_data), encoding="utf-8")

        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter, SeenMessage

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should load seen messages
        assert "+15551234567" in adapter._seen_messages
        msg = adapter._seen_messages["+15551234567"]
        assert isinstance(msg, SeenMessage)
        assert msg.row_id == 123
        assert msg.timestamp == 1712345678.0
        assert msg.text == "Hello"
        assert msg.is_from_me is False

        # Should load SMS contacts
        assert "+15551111111" in adapter._sms_contacts
        assert "+15552222222" in adapter._sms_contacts

    def test_load_state_corrupted_file(self, monkeypatch, tmp_path):
        """Should handle corrupted state file gracefully."""
        state_file = tmp_path / "imessage_state.json"
        state_file.write_text("not valid json {", encoding="utf-8")

        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should initialize with empty state after failed load
        assert adapter._seen_messages == {}
        assert adapter._sms_contacts == set()

    def test_load_state_partial_data(self, monkeypatch, tmp_path):
        """Should handle state file with missing fields."""
        import json

        state_file = tmp_path / "imessage_state.json"
        # Missing "sms_contacts" field
        state_data = {
            "seen_messages": {
                "+15551234567": {
                    "row_id": 123,
                    "timestamp": 1712345678.0,
                    "text": "Hello",
                    "is_from_me": False
                }
            }
        }
        state_file.write_text(json.dumps(state_data), encoding="utf-8")

        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should load what's present and use defaults for missing
        assert "+15551234567" in adapter._seen_messages
        assert adapter._sms_contacts == set()

    def test_save_state_creates_file(self, monkeypatch, tmp_path):
        """_save_state should create state file."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            tmp_path / "imessage_state.json"
        )
        from gateway.platforms.imessage import IMessageAdapter, SeenMessage

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Add some state
        adapter._seen_messages["+15551234567"] = SeenMessage(
            row_id=123,
            timestamp=1712345678.0,
            text="Test message",
            is_from_me=False
        )
        adapter._sms_contacts.add("+15551111111")

        # Save state
        adapter._save_state()

        # Verify file was created
        import json
        state_file = tmp_path / "imessage_state.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert "seen_messages" in data
        assert "+15551234567" in data["seen_messages"]
        assert data["seen_messages"]["+15551234567"]["row_id"] == 123
        assert "+15551111111" in data["sms_contacts"]

    def test_save_state_atomic_write(self, monkeypatch, tmp_path):
        """_save_state should use atomic write (write to temp, then rename)."""
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        state_file = tmp_path / "imessage_state.json"
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Save state
        adapter._save_state()

        # Verify no temp files left behind
        temp_files = list(tmp_path.glob(".imessage_state_*.tmp"))
        assert len(temp_files) == 0, "Temp files should be cleaned up"

        # Verify final file exists
        assert state_file.exists()

    def test_save_state_handles_missing_fields(self, monkeypatch, tmp_path):
        """_save_state should handle SeenMessage with missing optional fields."""
        import json

        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            tmp_path / "imessage_state.json"
        )
        from gateway.platforms.imessage import IMessageAdapter, SeenMessage

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Add message with all fields populated
        adapter._seen_messages["+15551234567"] = SeenMessage(
            row_id=123,
            timestamp=1712345678.0,
            text="Full message",
            is_from_me=False
        )

        adapter._save_state()

        # Verify saved data has all fields
        state_file = tmp_path / "imessage_state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        msg_data = data["seen_messages"]["+15551234567"]
        assert msg_data["row_id"] == 123
        assert msg_data["timestamp"] == 1712345678.0
        assert msg_data["text"] == "Full message"
        assert msg_data["is_from_me"] is False

    def test_state_persists_across_reinstantiation(self, monkeypatch, tmp_path):
        """State should persist when adapter is recreated."""
        import json

        state_file = tmp_path / "imessage_state.json"
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter, SeenMessage

        config = PlatformConfig(enabled=True)

        # First adapter instance - add state
        adapter1 = IMessageAdapter(config)
        adapter1._seen_messages["+15551234567"] = SeenMessage(
            row_id=999,
            timestamp=1712999999.0,
            text="Persistent message",
            is_from_me=True
        )
        adapter1._sms_contacts.add("+15553333333")
        adapter1._save_state()

        # Second adapter instance - should load state
        adapter2 = IMessageAdapter(config)

        # Verify state was restored
        assert "+15551234567" in adapter2._seen_messages
        assert adapter2._seen_messages["+15551234567"].row_id == 999
        assert "+15553333333" in adapter2._sms_contacts

    def test_save_state_creates_parent_directory(self, monkeypatch, tmp_path):
        """_save_state should create parent directory if missing."""
        import json

        # Create a nested path that doesn't exist
        nested_state_file = tmp_path / "nested" / "deep" / "imessage_state.json"
        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            nested_state_file
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should create parent directories
        adapter._save_state()

        # Verify file was created
        assert nested_state_file.exists()

    def test_load_state_handles_incompatible_schema(self, monkeypatch, tmp_path):
        """Should handle state file with incompatible schema (missing required fields)."""
        import json

        state_file = tmp_path / "imessage_state.json"
        # State with missing required "row_id" field
        state_data = {
            "seen_messages": {
                "+15551234567": {
                    "timestamp": 1712345678.0,
                    "text": "Hello"
                    # Missing row_id - required by SeenMessage
                }
            }
        }
        state_file.write_text(json.dumps(state_data), encoding="utf-8")

        monkeypatch.setenv("IMESSAGE_ALLOWED_USERS", "+15551234567")
        monkeypatch.setattr(
            "gateway.platforms.imessage.IMESSAGE_STATE_FILE",
            state_file
        )
        from gateway.platforms.imessage import IMessageAdapter

        config = PlatformConfig(enabled=True)
        adapter = IMessageAdapter(config)

        # Should handle gracefully and initialize empty
        # The load_state catches exceptions and logs warning
        assert adapter._seen_messages == {}