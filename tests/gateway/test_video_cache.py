"""
Tests for video cache utilities in gateway/platforms/base.py.

Covers: get_video_cache_dir, cache_video_from_bytes, cache_video_from_url,
        cleanup_video_cache.
"""

import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.platforms.base import (
    cache_video_from_bytes,
    cache_video_from_url,
    cleanup_video_cache,
    get_video_cache_dir,
)


# ---------------------------------------------------------------------------
# Fixture: redirect VIDEO_CACHE_DIR to a temp directory for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _redirect_cache(tmp_path, monkeypatch):
    """Point the module-level VIDEO_CACHE_DIR to a fresh tmp_path."""
    monkeypatch.setattr(
        "gateway.platforms.base.VIDEO_CACHE_DIR", tmp_path / "video_cache"
    )


# ---------------------------------------------------------------------------
# TestGetVideoCacheDir
# ---------------------------------------------------------------------------

class TestGetVideoCacheDir:
    def test_creates_directory(self, tmp_path):
        cache_dir = get_video_cache_dir()
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_returns_existing_directory(self):
        first = get_video_cache_dir()
        second = get_video_cache_dir()
        assert first == second
        assert first.exists()


# ---------------------------------------------------------------------------
# TestCacheVideoFromBytes
# ---------------------------------------------------------------------------

class TestCacheVideoFromBytes:
    def test_basic_caching(self):
        data = b"\x00\x00\x00\x1cftypmp42"  # fake mp4 header
        path = cache_video_from_bytes(data)
        assert os.path.exists(path)
        assert Path(path).read_bytes() == data

    def test_default_extension_is_mp4(self):
        data = b"fake video bytes"
        path = cache_video_from_bytes(data)
        assert path.endswith(".mp4")

    def test_custom_extension_preserved(self):
        data = b"fake webm bytes"
        path = cache_video_from_bytes(data, ext=".webm")
        assert path.endswith(".webm")

    def test_various_video_extensions(self):
        for ext in (".mp4", ".mov", ".avi", ".webm", ".mkv"):
            path = cache_video_from_bytes(b"video", ext=ext)
            assert path.endswith(ext)

    def test_unique_filenames(self):
        p1 = cache_video_from_bytes(b"a")
        p2 = cache_video_from_bytes(b"b")
        assert p1 != p2

    def test_filename_has_video_prefix(self):
        path = cache_video_from_bytes(b"data")
        basename = os.path.basename(path)
        assert basename.startswith("video_")


# ---------------------------------------------------------------------------
# TestCacheVideoFromUrl
# ---------------------------------------------------------------------------

class TestCacheVideoFromUrl:
    @pytest.mark.asyncio
    async def test_successful_download(self):
        """A valid video URL should download and cache the file."""
        video_data = b"\x00\x00\x00\x1cftypmp42fake"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content = video_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("gateway.platforms.base.httpx.AsyncClient", return_value=mock_client):
            path = await cache_video_from_url("https://cdn.example.com/video.mp4")

        assert os.path.exists(path)
        assert Path(path).read_bytes() == video_data

    @pytest.mark.asyncio
    async def test_custom_extension(self):
        """Extension should be honored and reflected in the saved filename."""
        video_data = b"fake webm video"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.content = video_data
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("gateway.platforms.base.httpx.AsyncClient", return_value=mock_client):
            path = await cache_video_from_url(
                "https://cdn.example.com/video.webm", ext=".webm"
            )

        assert path.endswith(".webm")
        assert Path(path).read_bytes() == video_data

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self):
        """Should retry on httpx.TimeoutException."""
        video_data = b"final success"
        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                import httpx
                raise httpx.TimeoutException("timeout")
            resp = AsyncMock()
            resp.status = 200
            resp.content = video_data
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get

        with patch("gateway.platforms.base.httpx.AsyncClient", return_value=mock_client):
            path = await cache_video_from_url("https://cdn.example.com/video.mp4", retries=2)

        assert call_count == 3
        assert Path(path).read_bytes() == video_data

    @pytest.mark.asyncio
    async def test_raises_on_404(self):
        """Client errors (4xx) should raise immediately without retries."""
        import httpx

        mock_resp = AsyncMock()
        mock_resp.status_code = 404
        exc = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_resp)
        mock_resp.raise_for_status.side_effect = exc

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("gateway.platforms.base.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await cache_video_from_url("https://cdn.example.com/notfound.mp4")

    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        """Rate limit (429) should be retried like a transient error."""
        video_data = b"rate limited but eventually ok"
        attempt = [0]

        def mock_get(*args, **kwargs):
            attempt[0] += 1
            import httpx
            if attempt[0] == 1:
                resp = AsyncMock()
                resp.status_code = 429
                exc = httpx.HTTPStatusError("Rate limited", request=MagicMock(), response=resp)
                exc.response = resp
                raise exc
            resp = AsyncMock()
            resp.status = 200
            resp.content = video_data
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = mock_get

        with patch("gateway.platforms.base.httpx.AsyncClient", return_value=mock_client):
            path = await cache_video_from_url("https://cdn.example.com/video.mp4", retries=2)

        assert attempt[0] == 2
        assert Path(path).read_bytes() == video_data


# ---------------------------------------------------------------------------
# TestCleanupVideoCache
# ---------------------------------------------------------------------------

class TestCleanupVideoCache:
    def test_removes_old_files(self, tmp_path):
        """Files older than max_age_hours should be deleted."""
        cache_dir = get_video_cache_dir()
        old_file = cache_dir / "video_abc123.mp4"
        old_file.write_bytes(b"old video")

        # Make the file appear old
        old_time = time.time() - (48 * 3600)  # 48 hours ago
        os.utime(old_file, (old_time, old_time))

        removed = cleanup_video_cache(max_age_hours=24)
        assert removed == 1
        assert not old_file.exists()

    def test_keeps_recent_files(self, tmp_path):
        """Files younger than max_age_hours should be kept."""
        cache_dir = get_video_cache_dir()
        new_file = cache_dir / "video_def456.mp4"
        new_file.write_bytes(b"new video")

        removed = cleanup_video_cache(max_age_hours=24)
        assert removed == 0
        assert new_file.exists()

    def test_returns_zero_on_empty_cache(self):
        """An empty cache directory should return 0."""
        removed = cleanup_video_cache(max_age_hours=24)
        assert removed == 0
