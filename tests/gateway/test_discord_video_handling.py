"""Tests for Discord incoming video attachment handling.

Covers the video branch in DiscordAdapter._handle_message() —
the `elif content_type.startswith("video/")` clause that downloads,
caches, and passes video attachments to the agent via media_urls.
"""

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.base import MessageType


# ---------------------------------------------------------------------------
# Discord mock setup (copied from test_discord_document_handling.py)
# ---------------------------------------------------------------------------

def _ensure_discord_mock():
    """Install a mock discord module when discord.py isn't available."""
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(View=object, button=lambda *a, **k: (lambda fn: fn), Button=object)
    discord_mod.ButtonStyle = SimpleNamespace(success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3)
    discord_mod.Color = SimpleNamespace(orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5)
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

import gateway.platforms.discord as discord_platform  # noqa: E402
from gateway.platforms.discord import DiscordAdapter  # noqa: E402


# ---------------------------------------------------------------------------
# Fake channel / thread types
# ---------------------------------------------------------------------------

class FakeDMChannel:
    def __init__(self, channel_id: int = 1):
        self.id = channel_id
        self.name = "dm"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path, monkeypatch):
    """Point video/image/audio cache to tmp_path so tests never write to ~/.hermes."""
    monkeypatch.setattr(
        "gateway.platforms.base.VIDEO_CACHE_DIR", tmp_path / "video_cache"
    )
    monkeypatch.setattr(
        "gateway.platforms.base.IMAGE_CACHE_DIR", tmp_path / "image_cache"
    )
    monkeypatch.setattr(
        "gateway.platforms.base.AUDIO_CACHE_DIR", tmp_path / "audio_cache"
    )
    monkeypatch.setattr(
        "gateway.platforms.base.DOCUMENT_CACHE_DIR", tmp_path / "doc_cache"
    )


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(discord_platform.discord, "DMChannel", FakeDMChannel, raising=False)
    monkeypatch.setattr(discord_platform.discord, "Thread", type("Thread", (), {}), raising=False)

    config = PlatformConfig(enabled=True, token="fake-token")
    a = DiscordAdapter(config)
    a._client = SimpleNamespace(user=SimpleNamespace(id=999))
    a.handle_message = AsyncMock()
    return a


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_attachment(
    *,
    filename: str,
    content_type: str,
    size: int = 1024,
    url: str = "https://cdn.discordapp.com/attachments/fake/file",
) -> SimpleNamespace:
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        size=size,
        url=url,
    )


def make_message(attachments: list, content: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=123,
        content=content,
        attachments=attachments,
        mentions=[],
        reference=None,
        created_at=datetime.now(timezone.utc),
        channel=FakeDMChannel(),
        author=SimpleNamespace(id=42, display_name="Tester", name="Tester"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestIncomingVideoHandling:

    @pytest.mark.asyncio
    async def test_mp4_video_cached(self, adapter):
        """An mp4 video attachment should be detected, downloaded, cached, and typed as VIDEO."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_test_video.mp4",
        ):
            msg = make_message([
                make_attachment(filename="clip.mp4", content_type="video/mp4")
            ])
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.VIDEO
        assert len(event.media_urls) == 1
        assert event.media_urls[0] == "/tmp/cached_test_video.mp4"
        assert event.media_types == ["video/mp4"]

    @pytest.mark.asyncio
    async def test_mov_video_cached(self, adapter):
        """A .mov video should also be cached correctly."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_test_video.mov",
        ):
            msg = make_message([
                make_attachment(filename="movie.mov", content_type="video/quicktime")
            ])
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.VIDEO
        assert event.media_urls == ["/tmp/cached_test_video.mov"]
        assert event.media_types == ["video/quicktime"]

    @pytest.mark.asyncio
    async def test_webm_video_cached(self, adapter):
        """A .webm video (screen recording format) should be cached."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_test_video.webm",
        ):
            msg = make_message([
                make_attachment(filename="recording.webm", content_type="video/webm")
            ])
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.VIDEO
        assert len(event.media_urls) == 1
        assert event.media_types == ["video/webm"]

    @pytest.mark.asyncio
    async def test_video_with_unrecognized_subtype_defaults_to_mp4(self, adapter):
        """An uncommon video subtype should default to .mp4 extension for caching."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_test_video.mp4",
        ) as mock_cache:
            msg = make_message([
                make_attachment(filename="weird.ogv", content_type="video/ogg")
            ])
            await adapter._handle_message(msg)

        # Called with .mp4 fallback since .ogv is not in the known extension list
        call_kwargs = mock_cache.call_args[1]
        assert call_kwargs["ext"] == ".mp4"

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.VIDEO

    @pytest.mark.asyncio
    async def test_video_download_error_does_not_crash(self, adapter):
        """If video caching raises, the handler should not crash and falls back to CDN URL."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            side_effect=Exception("HTTP 500"),
        ):
            msg = make_message([
                make_attachment(
                    filename="clip.mp4",
                    content_type="video/mp4",
                    url="https://cdn.discordapp.com/attachments/fake/clip.mp4",
                )
            ])
            # Should not raise
            await adapter._handle_message(msg)

        # Must still deliver an event
        adapter.handle_message.assert_called_once()
        event = adapter.handle_message.call_args[0][0]
        # Falls back to the CDN URL
        assert event.message_type == MessageType.VIDEO
        assert len(event.media_urls) == 1
        assert "cdn.discordapp.com" in event.media_urls[0]

    @pytest.mark.asyncio
    async def test_video_with_text_caption(self, adapter):
        """Video attachment with text caption should include caption in event.text."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_video.mp4",
        ):
            msg = make_message(
                attachments=[
                    make_attachment(filename="clip.mp4", content_type="video/mp4")
                ],
                content="Can you summarize this video?",
            )
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.VIDEO
        assert "Can you summarize this video?" in event.text
        assert len(event.media_urls) == 1

    @pytest.mark.asyncio
    async def test_image_attachments_unaffected_by_video_code(self, adapter):
        """Image attachments should still go through the image path, not the video path."""
        with patch(
            "gateway.platforms.discord.cache_image_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_image.png",
        ):
            msg = make_message([
                make_attachment(filename="photo.png", content_type="image/png")
            ])
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.PHOTO
        assert event.media_urls == ["/tmp/cached_image.png"]
        assert event.media_types == ["image/png"]

    @pytest.mark.asyncio
    async def test_audio_attachments_unaffected_by_video_code(self, adapter):
        """Audio attachments should still go through the audio path, not the video path."""
        with patch(
            "gateway.platforms.discord.cache_audio_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_audio.ogg",
        ):
            msg = make_message([
                make_attachment(filename="voice.ogg", content_type="audio/ogg")
            ])
            await adapter._handle_message(msg)

        event = adapter.handle_message.call_args[0][0]
        assert event.message_type == MessageType.AUDIO
        assert event.media_urls == ["/tmp/cached_audio.ogg"]
        assert event.media_types == ["audio/ogg"]

    @pytest.mark.asyncio
    async def test_video_attachment_without_content_type(self, adapter):
        """An attachment with no content_type should not trigger video path (falls to text doc path)."""
        with patch(
            "gateway.platforms.discord.cache_video_from_url",
            new_callable=AsyncMock,
            return_value="/tmp/cached_video.mp4",
        ) as mock_cache:
            # No content_type means it won't match video/* branch
            msg = make_message([
                make_attachment(filename="clip.mp4", content_type="")
            ])
            await adapter._handle_message(msg)

        # cache_video_from_url should NOT be called since no content_type
        mock_cache.assert_not_called()
        # Event is still delivered
        adapter.handle_message.assert_called_once()
