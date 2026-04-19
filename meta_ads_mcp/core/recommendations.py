"""Optimization recommendations from Meta Ads API."""

import json
from typing import Optional
from .api import meta_api_tool, make_api_request, ensure_act_prefix
from .server import mcp_server


@mcp_server.tool()
@meta_api_tool
async def get_recommendations(
    account_id: str,
    access_token: Optional[str] = None,
) -> str:
    """
    Get optimization recommendations ("Wynik sposobności" / Optimization Score) for the ad account.

    Returns the same recommendations visible in Ads Manager — actionable suggestions to
    improve campaign performance with estimated lift percentages and opportunity scores.

    Each recommendation includes:
    - type: recommendation category (e.g. APLUSC_STANDARD_ENHANCEMENTS_BUNDLE, REELS_PC_RECOMMENDATION)
    - object_ids: which ads/ad sets are affected
    - lift_estimate: predicted improvement (e.g. "3% lower cost per result")
    - opportunity_score_lift: how many points it adds to the Optimization Score
    - url: direct link to apply the recommendation in Ads Manager

    Args:
        account_id: Meta Ads account ID (format: act_XXXXXXXXX)
        access_token: Meta API access token (optional)
    """
    if not account_id:
        return json.dumps({"error": "No account ID specified"}, indent=2)

    account_id = ensure_act_prefix(account_id)

    data = await make_api_request(
        account_id,
        access_token,
        {"fields": "recommendations"},
    )

    recs_data = data.get("recommendations", {}).get("data", [])

    all_recs = []
    for group in recs_data:
        for rec in group.get("recommendations", []):
            all_recs.append(rec)

    if not all_recs:
        return json.dumps({"message": "No recommendations available for this account."}, indent=2)

    return json.dumps({
        "account_id": account_id,
        "total_recommendations": len(all_recs),
        "total_opportunity_score_lift": sum(
            int(r.get("recommendation_content", {}).get("opportunity_score_lift", 0))
            for r in all_recs
        ),
        "recommendations": all_recs,
    }, indent=2, ensure_ascii=False)
