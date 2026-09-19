"""Page tools — posts and comments on the Facebook Page and Instagram account.

Writes on a Page (edits, replies, hides) are guarded by a write throttle:
Meta answers bursts with error 368 ("We limit how often you can post…"), a spam
block that lasts hours and grows when you keep retrying. Ad creatives count too —
each one creates a hidden post on the Page. So every write here:
  * waits until MIN_WRITE_INTERVAL_S has passed since the previous Page write,
  * on 368 records a block (persisted in STATE_FILE, survives MCP restarts) and
    refuses further writes until it expires — no retry loop.

Instagram Graph API cannot edit a published caption (only comment_enabled), so
there is no tool for it — captions are edited by hand in the app.
"""

import asyncio
import json
import os
import time
from typing import Optional, Dict, Any

from .api import meta_api_tool, make_api_request
from .server import mcp_server

DEFAULT_PAGE_ID = os.environ.get("META_PAGE_ID", "100480158941339")
MIN_WRITE_INTERVAL_S = 90
BLOCK_BACKOFF_S = 6 * 3600
STATE_FILE = os.path.expanduser("~/.meta-ads-mcp/page_write_state.json")

_page_tokens: Dict[str, str] = {}
_write_lock = asyncio.Lock()


def _load_state() -> Dict[str, Any]:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def _graph_error(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the Graph error object from a make_api_request result, or None."""
    err = data.get("error") if isinstance(data, dict) else None
    if not err:
        return None
    details = err.get("details") if isinstance(err, dict) else None
    if isinstance(details, dict) and isinstance(details.get("error"), dict):
        return details["error"]
    return err


async def _page_token(page_id: str, access_token: str) -> str:
    if page_id not in _page_tokens:
        data = await make_api_request(page_id, access_token, {"fields": "access_token"})
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"No page access token for {page_id}: {json.dumps(data)[:300]}")
        _page_tokens[page_id] = token
    return _page_tokens[page_id]


async def _ig_user_id(page_id: str, access_token: str) -> str:
    data = await make_api_request(page_id, access_token, {"fields": "instagram_business_account"})
    ig = (data.get("instagram_business_account") or {}).get("id")
    if not ig:
        raise RuntimeError(f"Page {page_id} has no linked Instagram account")
    return ig


async def _throttled_write(endpoint: str, token: str, params: Dict[str, Any], method: str = "POST") -> Dict[str, Any]:
    """Single entry point for every Page write. Enforces spacing and the 368 block."""
    async with _write_lock:
        state = _load_state()
        now = time.time()
        blocked_until = state.get("blocked_until", 0)
        if now < blocked_until:
            return {"error": {
                "message": "Page writes blocked by Meta spam limit (368) — not retrying.",
                "blocked_until": time.strftime("%Y-%m-%d %H:%M", time.localtime(blocked_until)),
                "hint": "Do the remaining edits by hand, or try again after blocked_until.",
            }}
        wait = state.get("last_write", 0) + MIN_WRITE_INTERVAL_S - now
        if wait > 0:
            await asyncio.sleep(wait)
        data = await make_api_request(endpoint, token, params, method)
        state["last_write"] = time.time()
        err = _graph_error(data)
        if err and err.get("code") == 368:
            state["blocked_until"] = time.time() + BLOCK_BACKOFF_S
            _save_state(state)
            return {"error": {
                "message": "Meta spam limit (368) hit — Page writes paused, no retries.",
                "blocked_until": time.strftime("%Y-%m-%d %H:%M", time.localtime(state["blocked_until"])),
                "meta_message": err.get("message"),
            }}
        _save_state(state)
        return data


@mcp_server.tool()
@meta_api_tool
async def get_page_posts(
    page_id: str = DEFAULT_PAGE_ID,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 25,
    access_token: Optional[str] = None,
) -> str:
    """
    List posts published on the Facebook Page, with comment counts.

    Args:
        page_id: Facebook Page ID (default: CRAFTBE page)
        since: Start date YYYY-MM-DD (optional)
        until: End date YYYY-MM-DD (optional)
        limit: Max posts (default 25, max 100)
        access_token: Meta API access token (optional)
    """
    token = await _page_token(page_id, access_token)
    params: Dict[str, Any] = {
        "fields": "id,created_time,updated_time,message,permalink_url,full_picture,comments.summary(true).limit(0)",
        "limit": min(limit, 100),
    }
    if since:
        params["since"] = since
    if until:
        params["until"] = until
    data = await make_api_request(f"{page_id}/posts", token, params)
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp_server.tool()
@meta_api_tool
async def get_instagram_media(
    page_id: str = DEFAULT_PAGE_ID,
    limit: int = 25,
    access_token: Optional[str] = None,
) -> str:
    """
    List recent Instagram posts of the account linked to the Page.

    Args:
        page_id: Facebook Page ID whose Instagram account to read (default: CRAFTBE)
        limit: Max media (default 25, max 100)
        access_token: Meta API access token (optional)
    """
    ig = await _ig_user_id(page_id, access_token)
    data = await make_api_request(f"{ig}/media", access_token, {
        "fields": "id,timestamp,media_type,caption,permalink,comments_count,like_count",
        "limit": min(limit, 100),
    })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp_server.tool()
@meta_api_tool
async def get_post_comments(
    object_id: str,
    platform: str = "facebook",
    page_id: str = DEFAULT_PAGE_ID,
    limit: int = 100,
    access_token: Optional[str] = None,
) -> str:
    """
    Read comments under a Page post, an ad's post (effective_object_story_id) or an Instagram media.

    Args:
        object_id: FB post ID ({page_id}_{post_id}) or Instagram media ID
        platform: "facebook" or "instagram"
        page_id: Page that owns the post (default: CRAFTBE)
        limit: Max comments (default 100)
        access_token: Meta API access token (optional)
    """
    if platform == "instagram":
        data = await make_api_request(f"{object_id}/comments", access_token, {
            "fields": "id,text,timestamp,username,like_count,hidden,replies{id,text,username,timestamp}",
            "limit": min(limit, 100),
        })
    else:
        token = await _page_token(page_id, access_token)
        data = await make_api_request(f"{object_id}/comments", token, {
            "fields": "id,message,created_time,from{id,name},is_hidden,comment_count",
            "filter": "stream",
            "limit": min(limit, 100),
        })
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp_server.tool()
@meta_api_tool
async def update_page_post(
    post_id: str,
    message: Optional[str] = None,
    append_text: Optional[str] = None,
    page_id: str = DEFAULT_PAGE_ID,
    dry_run: bool = False,
    access_token: Optional[str] = None,
) -> str:
    """
    Edit the text of a Facebook Page post (throttled: one Page write per 90 s; stops on spam block 368).

    Use append_text for idempotent additions (e.g. an AI disclosure): if the post already
    contains it, nothing is written. Instagram captions cannot be edited via API.
    Edit posts one at a time — each call may wait up to 90 s.

    Args:
        post_id: FB post ID ({page_id}_{post_id})
        message: New full text (replaces the post text)
        append_text: Text appended after a blank line (skipped if already present)
        page_id: Page that owns the post (default: CRAFTBE)
        dry_run: Return the new text without writing
        access_token: Meta API access token (optional)
    """
    if bool(message) == bool(append_text):
        return json.dumps({"error": "Provide exactly one of message or append_text"})
    token = await _page_token(page_id, access_token)
    if append_text:
        current = (await make_api_request(post_id, token, {"fields": "message"})).get("message", "")
        if append_text.strip() in current:
            return json.dumps({"skipped": True, "reason": "append_text already present", "post_id": post_id})
        message = f"{current}\n\n{append_text.strip()}" if current else append_text.strip()
    if dry_run:
        return json.dumps({"dry_run": True, "post_id": post_id, "new_message": message}, ensure_ascii=False)
    data = await _throttled_write(post_id, token, {"message": message})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp_server.tool()
@meta_api_tool
async def reply_to_comment(
    comment_id: str,
    message: str,
    platform: str = "facebook",
    page_id: str = DEFAULT_PAGE_ID,
    access_token: Optional[str] = None,
) -> str:
    """
    Reply to a comment as the Page (throttled like all Page writes).

    Needs token permissions: pages_manage_engagement (Facebook) or
    instagram_manage_comments (Instagram).

    Args:
        comment_id: Comment ID from get_post_comments
        message: Reply text
        platform: "facebook" or "instagram"
        page_id: Page replying (default: CRAFTBE)
        access_token: Meta API access token (optional)
    """
    if platform == "instagram":
        data = await _throttled_write(f"{comment_id}/replies", access_token, {"message": message})
    else:
        token = await _page_token(page_id, access_token)
        data = await _throttled_write(f"{comment_id}/comments", token, {"message": message})
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp_server.tool()
@meta_api_tool
async def set_comment_hidden(
    comment_id: str,
    hidden: bool = True,
    platform: str = "facebook",
    page_id: str = DEFAULT_PAGE_ID,
    access_token: Optional[str] = None,
) -> str:
    """
    Hide or unhide a comment (hidden = visible only to its author and friends).

    Needs pages_manage_engagement (Facebook) or instagram_manage_comments (Instagram).

    Args:
        comment_id: Comment ID from get_post_comments
        hidden: True to hide, False to unhide
        platform: "facebook" or "instagram"
        page_id: Page that owns the post (default: CRAFTBE)
        access_token: Meta API access token (optional)
    """
    if platform == "instagram":
        data = await _throttled_write(comment_id, access_token, {"hide": "true" if hidden else "false"})
    else:
        token = await _page_token(page_id, access_token)
        data = await _throttled_write(comment_id, token, {"is_hidden": "true" if hidden else "false"})
    return json.dumps(data, indent=2, ensure_ascii=False)
