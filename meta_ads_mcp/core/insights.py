"""Insights and Reporting functionality for Meta Ads API."""

import json
from typing import Optional, Union, Dict, List
from .api import meta_api_tool, make_api_request
from .utils import download_image, try_multiple_download_methods, ad_creative_images, create_resource_from_image
from .server import mcp_server
import base64
import datetime


# Prefixes of action_type values that are always redundant duplicates of other
# action types already present in the response.  For every canonical event
# (e.g. "purchase"), the Meta API returns 5-8 variants that carry the exact
# same numeric value:
#   omni_purchase, onsite_web_purchase, onsite_web_app_purchase,
#   web_in_store_purchase, web_app_in_store_purchase,
#   offsite_conversion.fb_pixel_purchase  …
# Removing these cuts each insight row from ~4 KB to ~1 KB without any
# information loss.
_REDUNDANT_ACTION_PREFIXES = (
    "omni_",                       # omnichannel roll-up  (== onsite_web_app_*)
    "onsite_web_app_",             # web+app combined     (== onsite_web_*)
    "onsite_web_",                 # web-only subset      (== canonical + onsite)
    "onsite_app_",                 # app-only subset      (== onsite_conversion.*)
    "web_app_in_store_",           # web+app in-store     (== web_in_store_*)
    "offsite_conversion.fb_pixel_",  # pixel attribution  (== canonical type)
)


def _strip_redundant_actions(row: dict) -> dict:
    """Remove redundant action-type entries from a single insight row."""
    for key in ("actions", "action_values", "cost_per_action_type"):
        items = row.get(key)
        if not isinstance(items, list):
            continue
        row[key] = [
            item for item in items
            if not any(
                item.get("action_type", "").startswith(prefix)
                for prefix in _REDUNDANT_ACTION_PREFIXES
            )
        ]
    return row


@mcp_server.tool()
@meta_api_tool
async def get_insights(object_id: str = "", access_token: Optional[str] = None,
                      time_range: Union[str, Dict[str, str]] = "maximum", breakdown: str = "",
                      level: str = "ad", limit: int = 25, after: str = "",
                      action_attribution_windows: Optional[List[str]] = None,
                      compact: bool = False,
                      account_id: str = "", campaign_id: str = "",
                      adset_id: str = "", ad_id: str = "") -> str:
    """
    Get performance insights for a campaign, ad set, ad or account.

    Args:
        object_id: ID of the campaign, ad set, ad or account. You can also use the alias parameters below.
        account_id: Alias for object_id when querying account-level insights
        campaign_id: Alias for object_id when querying campaign-level insights
        adset_id: Alias for object_id when querying ad-set-level insights
        ad_id: Alias for object_id when querying ad-level insights
        access_token: Meta API access token (optional - will use cached token if not provided)
        time_range: Either a preset time range string or a dictionary with "since" and "until" dates in YYYY-MM-DD format
                   Preset options: today, yesterday, this_month, last_month, this_quarter, maximum, data_maximum, 
                   last_3d, last_7d, last_14d, last_28d, last_30d, last_90d, last_week_mon_sun, 
                   last_week_sun_sat, last_quarter, last_year, this_week_mon_today, this_week_sun_today, this_year
                   Dictionary example: {"since":"2023-01-01","until":"2023-01-31"}
        breakdown: Optional breakdown dimension. Valid values include:
                   Demographic: age, gender, country, region, dma
                   Platform/Device: device_platform, platform_position, publisher_platform, impression_device
                   Creative Assets: ad_format_asset, body_asset, call_to_action_asset, description_asset, 
                                  image_asset, link_url_asset, title_asset, video_asset, media_asset_url,
                                  media_creator, media_destination_url, media_format, media_origin_url,
                                  media_text_content, media_type, creative_relaxation_asset_type,
                                  flexible_format_asset_type, gen_ai_asset_type
                   Campaign/Ad Attributes: breakdown_ad_objective, breakdown_reporting_ad_id, app_id, product_id
                   Conversion Tracking: coarse_conversion_value, conversion_destination, standard_event_content_type,
                                       signal_source_bucket, is_conversion_id_modeled, fidelity_type, redownload
                   Time-based: hourly_stats_aggregated_by_advertiser_time_zone, 
                              hourly_stats_aggregated_by_audience_time_zone, frequency_value
                   Extensions/Landing: ad_extension_domain, ad_extension_url, landing_destination, 
                                      mdsa_landing_destination
                   Attribution: sot_attribution_model_type, sot_attribution_window, sot_channel, 
                               sot_event_type, sot_source
                   Mobile/SKAN: skan_campaign_id, skan_conversion_id, skan_version, postback_sequence_index
                   CRM/Business: crm_advertiser_l12_territory_ids, crm_advertiser_subvertical_id,
                                crm_advertiser_vertical_id, crm_ult_advertiser_id, user_persona_id, user_persona_name
                   Advanced: hsid, is_auto_advance, is_rendered_as_delayed_skip_ad, mmm, place_page_id,
                            marketing_messages_btn_name, impression_view_time_advertiser_hour_v2, comscore_market,
                            comscore_market_code
        level: Level of aggregation (ad, adset, campaign, account)
        limit: Maximum number of results to return per page (default: 25, Meta API allows much higher values)
        after: Pagination cursor to get the next set of results. Use the 'after' cursor from previous response's paging.next field.
        action_attribution_windows: Optional list of attribution windows (e.g., ["1d_click", "7d_click", "1d_view"]).
                   When specified, actions include additional fields for each window. The 'value' field always shows 7d_click.
        compact: When True, strips redundant action-type duplicates from the response
                 (omni_*, onsite_web_*, offsite_conversion.fb_pixel_*, etc.) to reduce
                 payload size by ~60%. The canonical action types (purchase, add_to_cart,
                 view_content, etc.) are always preserved. Default: False.

    Note on response size: This tool always returns a fixed set of fields (impressions, clicks,
    spend, cpc, cpm, ctr, reach, actions, action_values, etc.) and cannot filter to a subset.
    For large result sets (50+ rows), the actions/action_values arrays can make responses very
    large (1–2MB+). If you only need specific metrics like spend or impressions, consider using
    bulk_get_insights with compact=true and the fields parameter:
        bulk_get_insights(level="ad", account_ids=[...], compact=true, fields=["spend", "impressions"])
    bulk_get_insights supports level="ad", "adset", "campaign", and "account".
    """
    # Accept common aliases for object_id (LLMs frequently use these instead)
    if not object_id:
        object_id = account_id or campaign_id or adset_id or ad_id

    if not object_id:
        return json.dumps({"error": "No object ID provided. Use object_id, account_id, campaign_id, adset_id, or ad_id."}, indent=2)
        
    endpoint = f"{object_id}/insights"
    params = {
        "fields": "account_id,account_name,campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,impressions,clicks,spend,cpc,cpm,ctr,reach,frequency,actions,action_values,conversions,unique_clicks,cost_per_action_type",
        "level": level,
        "limit": limit
    }
    
    # Handle time range based on type
    if isinstance(time_range, dict):
        # Use custom date range with since/until parameters
        if "since" in time_range and "until" in time_range:
            params["time_range"] = json.dumps(time_range)
        else:
            return json.dumps({"error": "Custom time_range must contain both 'since' and 'until' keys in YYYY-MM-DD format"}, indent=2)
    else:
        # Use preset date range
        params["date_preset"] = time_range
    
    if breakdown:
        params["breakdowns"] = breakdown
    
    if after:
        params["after"] = after

    if action_attribution_windows:
        # Meta API expects single-quote format: ['1d_click','7d_click']
        params["action_attribution_windows"] = "[" + ",".join(f"'{w}'" for w in action_attribution_windows) + "]"

    data = await make_api_request(endpoint, access_token, params)

    # In compact mode, strip redundant action-type duplicates to reduce response size.
    if compact and isinstance(data, dict):
        for row in data.get("data", []):
            if isinstance(row, dict):
                _strip_redundant_actions(row)

    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def meta_daily_snapshot(
    account_id: str = "",
    days: int = 3,
    compact: bool = True,
    access_token: Optional[str] = None,
) -> str:
    """
    Get a comprehensive daily ads snapshot in one call: account-level daily spend,
    per-campaign breakdown, campaign statuses, and budgets. Designed for daily
    audits — replaces multiple get_campaigns + get_insights calls.

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX). If omitted, auto-resolves to the first account accessible by the current token.
        days: Number of days to look back (default: 3, max: 90)
        compact: Strip zero-spend rows and redundant action types (default: True)
        access_token: Meta API access token (optional)
    """
    from .api import ensure_act_prefix

    if not account_id:
        # Auto-resolve: fetch the first ad account accessible by the current token
        accts = await make_api_request(
            "me/adaccounts", access_token, {"fields": "id", "limit": 1}
        )
        accts_list = accts.get("data", []) if isinstance(accts, dict) else []
        if accts_list:
            account_id = accts_list[0]["id"]
        else:
            return json.dumps(
                {"error": "No account_id provided and could not auto-resolve one from the current token"},
                indent=2,
            )

    account_id = ensure_act_prefix(account_id)
    days = max(1, min(days, 90))

    today = datetime.date.today()
    since = (today - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    until = today.strftime("%Y-%m-%d")
    time_range_json = json.dumps({"since": since, "until": until})

    insight_fields = (
        "account_id,impressions,clicks,spend,cpc,cpm,ctr,reach,frequency,"
        "actions,action_values"
    )

    # --- 1. Campaigns list ---
    campaigns_data = await make_api_request(
        f"{account_id}/campaigns",
        access_token,
        {
            "fields": "id,name,status,daily_budget,lifetime_budget,bid_strategy,start_time",
            "limit": 100,
        },
    )

    # --- 2. Account insights by day ---
    account_insights_data = await make_api_request(
        f"{account_id}/insights",
        access_token,
        {
            "fields": insight_fields,
            "time_range": time_range_json,
            "time_increment": "1",
            "limit": 500,
        },
    )

    # --- 3. Campaign insights by day ---
    campaign_insight_fields = f"campaign_id,campaign_name,{insight_fields}"
    campaign_insights_data = await make_api_request(
        f"{account_id}/insights",
        access_token,
        {
            "fields": campaign_insight_fields,
            "time_range": time_range_json,
            "time_increment": "1",
            "level": "campaign",
            "limit": 500,
        },
    )

    # ---- Extract data lists ----
    campaigns_list = campaigns_data.get("data", []) if isinstance(campaigns_data, dict) else []
    account_daily = account_insights_data.get("data", []) if isinstance(account_insights_data, dict) else []
    campaign_daily = campaign_insights_data.get("data", []) if isinstance(campaign_insights_data, dict) else []

    # ---- Compact mode processing ----
    if compact:
        # Strip redundant action types
        for row in account_daily:
            if isinstance(row, dict):
                _strip_redundant_actions(row)
        for row in campaign_daily:
            if isinstance(row, dict):
                _strip_redundant_actions(row)

        # Remove zero-spend rows
        account_daily = [
            r for r in account_daily
            if isinstance(r, dict) and float(r.get("spend", "0") or "0") > 0
        ]
        campaign_daily = [
            r for r in campaign_daily
            if isinstance(r, dict) and float(r.get("spend", "0") or "0") > 0
        ]

        # Keep only ACTIVE campaigns in campaign_daily
        active_ids = {
            c["id"] for c in campaigns_list
            if isinstance(c, dict) and c.get("status") == "ACTIVE"
        }
        if active_ids:
            campaign_daily = [
                r for r in campaign_daily
                if r.get("campaign_id") in active_ids
            ]

    # ---- Build summary ----
    total_spend = sum(float(r.get("spend", "0") or "0") for r in account_daily)

    total_purchases = 0
    total_purchase_value = 0.0
    for row in account_daily:
        for action in row.get("actions", []) or []:
            if action.get("action_type") == "purchase":
                total_purchases += int(float(action.get("value", "0")))
        for av in row.get("action_values", []) or []:
            if av.get("action_type") == "purchase":
                total_purchase_value += float(av.get("value", "0"))

    active_count = sum(1 for c in campaigns_list if c.get("status") == "ACTIVE")
    paused_count = sum(1 for c in campaigns_list if c.get("status") == "PAUSED")

    result = {
        "period": {"since": since, "until": until},
        "account_daily": account_daily,
        "campaigns": campaigns_list,
        "campaign_daily": campaign_daily,
        "summary": {
            "total_spend": round(total_spend, 2),
            "total_purchases": total_purchases,
            "total_purchase_value": round(total_purchase_value, 2),
            "roas": round(total_purchase_value / total_spend, 2) if total_spend > 0 else 0,
            "active_campaigns": active_count,
            "paused_campaigns": paused_count,
        },
    }

    return json.dumps(result, indent=2)

 