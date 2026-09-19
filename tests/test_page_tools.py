"""Write throttle of page_tools: spacing between Page writes and the 368 spam-block stop."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from meta_ads_mcp.core import page_tools

BLOCK_368 = {"error": {"message": "HTTP Error: 400", "details": {"error": {
    "code": 368, "error_subcode": 1390008, "message": "We limit how often you can post"}}}}


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(page_tools, "STATE_FILE", str(tmp_path / "state.json"))
    page_tools._page_tokens.clear()
    page_tools._page_tokens[page_tools.DEFAULT_PAGE_ID] = "PAGE_TOKEN"


@pytest.mark.asyncio
async def test_368_blocks_further_writes_without_calling_api():
    api = AsyncMock(return_value=BLOCK_368)
    with patch.object(page_tools, "make_api_request", api):
        first = await page_tools._throttled_write("p_1", "t", {"message": "x"})
        second = await page_tools._throttled_write("p_2", "t", {"message": "x"})
    assert "spam limit" in first["error"]["message"]
    assert "blocked" in second["error"]["message"]
    assert api.await_count == 1  # second write never reached Meta


@pytest.mark.asyncio
async def test_writes_are_spaced():
    api = AsyncMock(return_value={"success": True})
    sleep = AsyncMock()
    with patch.object(page_tools, "make_api_request", api), patch.object(page_tools.asyncio, "sleep", sleep):
        await page_tools._throttled_write("p_1", "t", {"message": "x"})
        await page_tools._throttled_write("p_2", "t", {"message": "x"})
    assert sleep.await_count == 1
    assert sleep.await_args.args[0] > page_tools.MIN_WRITE_INTERVAL_S - 5


@pytest.mark.asyncio
async def test_append_text_is_idempotent():
    api = AsyncMock(return_value={"message": "Kawa.\n\nGrafika wygenerowana z pomocą AI."})
    with patch.object(page_tools, "make_api_request", api):
        out = json.loads(await page_tools.update_page_post(
            post_id="p_1", append_text="Grafika wygenerowana z pomocą AI.", access_token="t"))
    assert out["skipped"] is True
    assert api.await_count == 1  # only the read, no write
