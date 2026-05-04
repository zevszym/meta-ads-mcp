"""CRAFTBE-specific tools for Meta Ads — 20 tools missing from pipeboard.

Follows the same pattern as other tool files: @mcp_server.tool() + @meta_api_tool.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Union
from .api import meta_api_tool, make_api_request, ensure_act_prefix
from .server import mcp_server


def _resolve_object_id(account_id: str, campaign_id: str = "") -> str:
    """Return campaign_id if given, otherwise validated account_id."""
    if campaign_id:
        return campaign_id
    if not account_id:
        raise ValueError("account_id is required when campaign_id is not provided")
    return ensure_act_prefix(account_id)


def _time_range_params(time_range: Union[str, Dict[str, str]]) -> Dict[str, Any]:
    """Convert time_range arg to API params."""
    if isinstance(time_range, dict):
        if "since" not in time_range or "until" not in time_range:
            raise ValueError("Custom time_range must contain both 'since' and 'until' in YYYY-MM-DD format")
        return {"time_range": json.dumps(time_range)}
    return {"date_preset": time_range}


# ── 1. Ad Previews ───────────��──────────────────────────────────────

@mcp_server.tool()
@meta_api_tool
async def get_ad_previews(
    ad_id: str,
    ad_format: str = "DESKTOP_FEED_STANDARD",
    access_token: Optional[str] = None,
) -> str:
    """
    Get preview links/iframes for an ad in a specific placement format.

    Args:
        ad_id: The ad ID to preview
        ad_format: Preview format. Options: DESKTOP_FEED_STANDARD, MOBILE_FEED_STANDARD,
                   MOBILE_FEED_BASIC, INSTAGRAM_STANDARD, INSTAGRAM_STORY,
                   INSTAGRAM_REELS, FACEBOOK_REELS, RIGHT_COLUMN_STANDARD,
                   MARKETPLACE_MOBILE, AUDIENCE_NETWORK_OUTSTREAM_VIDEO
        access_token: Meta API access token (optional)

    Returns:
        JSON with preview iframe/link for the ad
    """
    if not ad_id:
        return json.dumps({"error": "ad_id is required"})
    endpoint = f"{ad_id}/previews"
    params = {"ad_format": ad_format}
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 2. Placement Breakdown ───────��──────────────────────────────────

@mcp_server.tool()
@meta_api_tool
async def get_placement_breakdown(
    account_id: str,
    time_range: Union[str, Dict[str, str]] = "last_7d",
    level: str = "campaign",
    campaign_id: str = "",
    access_token: Optional[str] = None,
) -> str:
    """
    Get performance breakdown by placement (Feed, Stories, Reels, etc.).

    Returns spend, impressions, clicks, CPC, CPM, CTR, conversions, and ROAS
    broken down by publisher_platform + platform_position.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        time_range: Preset (last_7d, last_30d, etc.) or {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}
        level: Aggregation level (campaign, adset, ad, account)
        campaign_id: Optional campaign ID filter — if provided, queries that campaign directly
        access_token: Meta API access token (optional)
    """
    object_id = _resolve_object_id(account_id, campaign_id)
    endpoint = f"{object_id}/insights"
    params = {
        "fields": "campaign_name,adset_name,impressions,clicks,spend,cpc,cpm,ctr,reach,actions,action_values,cost_per_action_type",
        "breakdowns": "publisher_platform,platform_position",
        "level": level,
        "limit": 100,
        **_time_range_params(time_range),
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 3. Age/Gender Breakdown ──────────────────���──────────────────────

@mcp_server.tool()
@meta_api_tool
async def get_age_gender_breakdown(
    account_id: str,
    time_range: Union[str, Dict[str, str]] = "last_7d",
    level: str = "account",
    campaign_id: str = "",
    access_token: Optional[str] = None,
) -> str:
    """
    Get performance breakdown by age and gender.

    Useful for understanding which demographics perform best. Returns
    spend, impressions, clicks, conversions broken down by age bucket and gender.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        time_range: Preset (last_7d, last_30d, etc.) or {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}
        level: Aggregation level (campaign, adset, ad, account)
        campaign_id: Optional campaign ID filter
        access_token: Meta API access token (optional)
    """
    object_id = _resolve_object_id(account_id, campaign_id)
    endpoint = f"{object_id}/insights"
    params = {
        "fields": "campaign_name,impressions,clicks,spend,cpc,cpm,ctr,reach,actions,action_values,cost_per_action_type",
        "breakdowns": "age,gender",
        "level": level,
        "limit": 100,
        **_time_range_params(time_range),
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 4. Hourly Breakdown ──────────────────��──────────────────────────

@mcp_server.tool()
@meta_api_tool
async def get_hourly_breakdown(
    account_id: str,
    time_range: Union[str, Dict[str, str]] = "last_7d",
    level: str = "account",
    campaign_id: str = "",
    access_token: Optional[str] = None,
) -> str:
    """
    Get performance breakdown by hour of day (advertiser timezone).

    Essential for dayparting decisions — shows which hours have the best
    CPC, CTR, and conversion rates.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        time_range: Preset (last_7d, last_30d, etc.) or {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"}
        level: Aggregation level (campaign, adset, ad, account)
        campaign_id: Optional campaign ID filter
        access_token: Meta API access token (optional)
    """
    object_id = _resolve_object_id(account_id, campaign_id)
    endpoint = f"{object_id}/insights"
    params = {
        "fields": "campaign_name,impressions,clicks,spend,cpc,cpm,ctr,reach,actions,cost_per_action_type",
        "breakdowns": "hourly_stats_aggregated_by_advertiser_time_zone",
        "level": level,
        "limit": 200,
        **_time_range_params(time_range),
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 5. Delivery Estimate ────────────────────────────────────────────

@mcp_server.tool()
@meta_api_tool
async def get_delivery_estimate(
    account_id: str,
    targeting_spec: Dict[str, Any],
    optimization_goal: str = "LINK_CLICKS",
    access_token: Optional[str] = None,
) -> str:
    """
    Get estimated daily reach for a targeting spec BEFORE launching a campaign.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        targeting_spec: Targeting specification dict, e.g.:
            {
                "geo_locations": {"countries": ["PL"]},
                "age_min": 25, "age_max": 55,
                "interests": [{"id": "6003139266461", "name": "Coffee"}]
            }
        optimization_goal: LINK_CLICKS, IMPRESSIONS, REACH, CONVERSIONS,
                          LANDING_PAGE_VIEWS, LEAD_GENERATION, etc.
        access_token: Meta API access token (optional)
    """
    if not account_id:
        return json.dumps({"error": "account_id is required"})
    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/delivery_estimate"
    # targeting_spec stays as dict — make_api_request GET path json.dumps dicts
    params = {
        "targeting_spec": targeting_spec,
        "optimization_goal": optimization_goal,
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 6. Ad Account Activities (Change Log) ──────────────────���────────

@mcp_server.tool()
@meta_api_tool
async def get_ad_account_activities(
    account_id: str,
    since: str = "",
    until: str = "",
    limit: int = 50,
    category: str = "",
    access_token: Optional[str] = None,
) -> str:
    """
    Get the activity/change log for an ad account — who changed what and when.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        since: Start date (YYYY-MM-DD). Default: 7 days ago
        until: End date (YYYY-MM-DD). Default: today
        limit: Max results (default: 50, max: 500)
        category: Filter by category. Options: ACCOUNT, AD, AD_SET, AUDIENCE, BID,
                  BUDGET, CAMPAIGN, DATE, STATUS, TARGETING, NONE (all). Default: all.
        access_token: Meta API access token (optional)
    """
    if not account_id:
        return json.dumps({"error": "account_id is required"})
    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/activities"
    params: Dict[str, Any] = {"limit": min(limit, 500)}

    if since:
        params["since"] = int(datetime.strptime(since, "%Y-%m-%d").timestamp())
    if until:
        params["until"] = int(datetime.strptime(until, "%Y-%m-%d").timestamp())
    if category:
        params["category"] = category

    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


# ── 7. Ad Scheduling (Dayparting) ───────────────────────────────────

@mcp_server.tool()
@meta_api_tool
async def manage_ad_scheduling(
    adset_id: str,
    schedule: List[Dict[str, Any]],
    access_token: Optional[str] = None,
) -> str:
    """
    Set dayparting schedule on an ad set — restrict delivery to specific hours/days.

    IMPORTANT: The ad set must use LIFETIME_BUDGET (not daily budget) for scheduling to work.
    This tool will verify the budget type before applying the schedule.

    Args:
        adset_id: The ad set ID to update
        schedule: List of schedule entries. Each entry:
            {
                "start_minute": 0,      # 0 = midnight (minutes from midnight, 0-1439)
                "end_minute": 1439,     # 1439 = 23:59
                "days": [0,1,2,3,4,5,6], # 0=Sun, 1=Mon, ..., 6=Sat
                "timezone_type": "USER"  # USER or ADVERTISER
            }
            Example — weekdays 8am-10pm only:
            [{"start_minute": 480, "end_minute": 1320, "days": [1,2,3,4,5], "timezone_type": "USER"}]
        access_token: Meta API access token (optional)

    Returns:
        Updated ad set confirmation
    """
    if not adset_id:
        return json.dumps({"error": "adset_id is required"})

    # Verify the adset uses lifetime budget
    check = await make_api_request(
        adset_id, access_token, {"fields": "lifetime_budget,daily_budget,name"}
    )
    if isinstance(check, dict) and "error" not in check:
        if check.get("daily_budget") and not check.get("lifetime_budget"):
            return json.dumps({
                "error": f"Ad set '{check.get('name', adset_id)}' uses daily_budget. "
                         "Dayparting requires lifetime_budget. Change the budget type first."
            })

    for entry in schedule:
        start = entry.get("start_minute", 0)
        end = entry.get("end_minute", 1439)
        if not (0 <= start <= 1439 and 0 <= end <= 1439):
            return json.dumps({"error": f"start_minute/end_minute must be 0-1439, got {start}/{end}"})
        days = entry.get("days", [])
        if not days or not all(0 <= d <= 6 for d in days):
            return json.dumps({"error": f"days must be list of 0-6 (Sun-Sat), got {days}"})

    endpoint = adset_id
    # schedule and pacing_type are lists/dicts — make_api_request POST serializes them
    params: Dict[str, Any] = {
        "pacing_type": ["day_parting"],
        "adset_schedule": schedule,
    }
    data = await make_api_request(endpoint, access_token, params, method="POST")
    return json.dumps(data, indent=2)


# ── 8. Pixel Events ─────────────────────────────────��───────────────

@mcp_server.tool()
@meta_api_tool
async def get_pixel_stats(
    account_id: str,
    access_token: Optional[str] = None,
) -> str:
    """
    List all pixels and their recent event stats for an ad account.

    Returns pixel IDs, names, and event counts — useful for verifying
    tracking setup and debugging conversion events.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        access_token: Meta API access token (optional)
    """
    if not account_id:
        return json.dumps({"error": "account_id is required"})
    account_id = ensure_act_prefix(account_id)

    pixels_data = await make_api_request(
        f"{account_id}/adspixels",
        access_token,
        {"fields": "id,name,creation_time,last_fired_time,is_unavailable,data_use_setting,automatic_matching_fields"},
    )

    if isinstance(pixels_data, dict) and "error" in pixels_data:
        return json.dumps(pixels_data, indent=2)

    result = {"pixels": []}
    for pixel in pixels_data.get("data", []):
        pixel_id = pixel.get("id")
        if not pixel_id:
            continue
        stats = await make_api_request(f"{pixel_id}/stats", access_token, {"aggregation": "event"})
        pixel["event_stats"] = stats.get("data", []) if isinstance(stats, dict) and "error" not in stats else []
        result["pixels"].append(pixel)

    return json.dumps(result, indent=2)


# ── 9. Custom Conversions ───────────────────────────────────────────

@mcp_server.tool()
@meta_api_tool
async def manage_custom_conversions(
    account_id: str,
    action: str = "list",
    name: str = "",
    pixel_id: str = "",
    custom_event_type: str = "OTHER",
    rule: Optional[Dict[str, Any]] = None,
    conversion_id: str = "",
    access_token: Optional[str] = None,
) -> str:
    """
    List, create, or delete custom conversions for an ad account.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        action: "list", "create", or "delete"
        name: Name for the custom conversion (required for create)
        pixel_id: Pixel ID to associate with (required for create)
        custom_event_type: Event type. Options: ADD_PAYMENT_INFO, ADD_TO_CART,
                          ADD_TO_WISHLIST, COMPLETE_REGISTRATION, CONTACT,
                          CUSTOMIZE_PRODUCT, DONATE, FIND_LOCATION,
                          INITIATED_CHECKOUT, LEAD, PURCHASE, SCHEDULE,
                          SEARCH, START_TRIAL, SUBMIT_APPLICATION,
                          SUBSCRIBE, VIEW_CONTENT, OTHER
        rule: URL rule dict, e.g.: {"url":{"i_contains":"thank-you"}}
        conversion_id: ID of conversion to delete (required for delete)
        access_token: Meta API access token (optional)

    Returns:
        List of custom conversions, or confirmation of create/delete
    """
    if not account_id:
        return json.dumps({"error": "account_id is required"})
    account_id = ensure_act_prefix(account_id)

    if action == "list":
        endpoint = f"{account_id}/customconversions"
        params = {
            "fields": "id,name,pixel,custom_event_type,rule,creation_time,last_fired_time,is_archived"
        }
        data = await make_api_request(endpoint, access_token, params)
        return json.dumps(data, indent=2)

    elif action == "create":
        if not name or not pixel_id:
            return json.dumps({"error": "name and pixel_id are required for create"})
        endpoint = f"{account_id}/customconversions"
        params: Dict[str, Any] = {
            "name": name,
            "pixel_id": pixel_id,
            "custom_event_type": custom_event_type,
        }
        if rule:
            # rule must be a JSON string for the API
            params["rule"] = json.dumps(rule) if isinstance(rule, dict) else rule
        data = await make_api_request(endpoint, access_token, params, method="POST")
        return json.dumps(data, indent=2)

    elif action == "delete":
        if not conversion_id:
            return json.dumps({"error": "conversion_id is required for delete"})
        data = await make_api_request(conversion_id, access_token, method="DELETE")
        return json.dumps(data, indent=2)

    return json.dumps({"error": f"Unknown action: {action}. Use list, create, or delete."})


# ── 10. Reach & Frequency Prediction ──────────────��─────────────────

@mcp_server.tool()
@meta_api_tool
async def get_reach_frequency_prediction(
    account_id: str,
    targeting_spec: Dict[str, Any],
    budget: int,
    duration_days: int = 7,
    frequency_cap: int = 0,
    objective: str = "REACH",
    access_token: Optional[str] = None,
) -> str:
    """
    Predict reach and frequency for a given budget and targeting — plan before you spend.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        targeting_spec: Targeting specification dict (same format as create_adset), e.g.:
            {
                "geo_locations": {"countries": ["PL"]},
                "age_min": 25, "age_max": 55,
                "interests": [{"id": "6003139266461", "name": "Coffee"}]
            }
        budget: Total budget in account currency smallest unit (e.g., 10000 = 100.00 PLN in grosz)
        duration_days: Campaign duration in days (default: 7, min: 1, max: 90)
        frequency_cap: Max impressions per person (0 = no cap)
        objective: Campaign objective. Options: REACH, BRAND_AWARENESS, VIDEO_VIEWS, POST_ENGAGEMENT
        access_token: Meta API access token (optional)

    Returns:
        Predicted reach, frequency, impressions, CPM for the given budget and targeting
    """
    import time as _time

    if not account_id:
        return json.dumps({"error": "account_id is required"})
    if budget <= 0:
        return json.dumps({"error": "budget must be a positive integer (in currency smallest unit)"})
    if not 1 <= duration_days <= 90:
        return json.dumps({"error": "duration_days must be between 1 and 90"})

    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/reachfrequencypredictions"

    now = int(_time.time())
    end_time = now + (duration_days * 86400)

    params: Dict[str, Any] = {
        "targeting_spec": targeting_spec,  # make_api_request POST serializes dicts
        "budget": budget,
        "prediction_mode": 0,
        "start_time": now,
        "end_time": end_time,
        "objective": objective,
    }

    if frequency_cap > 0:
        params["frequency_cap"] = frequency_cap

    data = await make_api_request(endpoint, access_token, params, method="POST")

    if isinstance(data, dict) and "id" in data and "error" not in data:
        prediction_id = data["id"]
        result_params = {
            "fields": "account_id,prediction_mode,budget,reach,frequency,impressions,"
                      "cpm,external_budget,external_impression,external_reach,"
                      "external_maximum_budget,external_maximum_impression,"
                      "external_maximum_reach,external_minimum_budget,"
                      "external_minimum_impression,external_minimum_reach,"
                      "status,story_event_type,target_spec,time_created"
        }
        prediction_data = await make_api_request(prediction_id, access_token, result_params)
        return json.dumps(prediction_data, indent=2)

    return json.dumps(data, indent=2)
