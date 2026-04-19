"""Custom Audience management for Meta Ads API — create, populate, and manage customer lists + lookalikes."""

import json
import hashlib
import re
from typing import Optional, List, Dict, Any
from .api import meta_api_tool, make_api_request, ensure_act_prefix
from .server import mcp_server

MAX_BATCH_SIZE = 10_000


def _hash_sha256(value: str) -> str:
    """SHA-256 hash a value after lowercasing and stripping whitespace (Meta's normalization)."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _normalize_phone(phone: str) -> str:
    """Normalize phone to digits-only with country code. PL 9-digit numbers get '48' prefix.

    Handles: +48501234567, 0048501234567, 48501234567, 501234567, 501-234-567
    Returns empty string for invalid numbers.
    """
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 9:
        digits = "48" + digits
    if len(digits) < 10 or len(digits) > 15:
        return ""
    return digits


def _build_user_schema_and_data(
    phones: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
    first_names: Optional[List[str]] = None,
    last_names: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the schema + data payload for Custom Audience user operations.

    Meta requires all PII to be SHA-256 hashed before upload.
    Rows where all identifier fields (phone/email) are empty are skipped.
    """
    columns: List[tuple] = []
    if phones:
        columns.append(("PHONE", phones))
    if emails:
        columns.append(("EMAIL", emails))
    if first_names:
        columns.append(("FN", first_names))
    if last_names:
        columns.append(("LN", last_names))
    if cities:
        columns.append(("CT", cities))

    schema = [col[0] for col in columns]
    max_len = max((len(col[1]) for col in columns), default=0)

    data = []
    for i in range(max_len):
        row = []
        has_identifier = False
        for col_name, col_list in columns:
            val = col_list[i].strip() if i < len(col_list) else ""
            if not val:
                row.append("")
                continue
            if col_name == "PHONE":
                normalized = _normalize_phone(val)
                if normalized:
                    row.append(_hash_sha256(normalized))
                    has_identifier = True
                else:
                    row.append("")
            elif col_name == "EMAIL":
                row.append(_hash_sha256(val))
                has_identifier = True
            else:
                row.append(_hash_sha256(val))
        if has_identifier:
            data.append(row)

    return {"schema": schema, "data": data}


@mcp_server.tool()
@meta_api_tool
async def get_custom_audiences(
    account_id: str,
    access_token: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    List all Custom Audiences for an ad account.

    Args:
        account_id: Ad account ID (e.g., 'act_523933962063921' or '523933962063921')
        access_token: Meta API access token (optional)
        limit: Maximum number of audiences to return (default: 50)

    Returns:
        JSON string with list of custom audiences including id, name, subtype, approximate_count, data_source, delivery_status
    """
    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/customaudiences"
    params = {
        "fields": "id,name,subtype,description,data_source,delivery_status,operation_status,time_created,time_updated,customer_file_source",
        "limit": limit,
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def get_audience_details(
    audience_id: str,
    access_token: Optional[str] = None,
) -> str:
    """
    Get detailed information about a specific Custom Audience.

    Args:
        audience_id: The Custom Audience ID
        access_token: Meta API access token (optional)

    Returns:
        JSON string with audience details including size, status, data source, and delivery status
    """
    endpoint = audience_id
    params = {
        "fields": "id,name,subtype,description,data_source,delivery_status,operation_status,time_created,time_updated,customer_file_source,lookalike_spec,rule,retention_days",
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def create_custom_audience(
    account_id: str,
    name: str,
    description: str = "",
    customer_file_source: str = "USER_PROVIDED_ONLY",
    access_token: Optional[str] = None,
) -> str:
    """
    Create a new Custom Audience (customer list) for uploading phone numbers, emails, etc.

    Args:
        account_id: Ad account ID (e.g., 'act_523933962063921' or '523933962063921')
        name: Name of the audience (e.g., 'VIP CRAFTBE 12m')
        description: Description of the audience
        customer_file_source: Source of customer data. One of: USER_PROVIDED_ONLY, PARTNER_PROVIDED_ONLY, BOTH_USER_AND_PARTNER_PROVIDED
        access_token: Meta API access token (optional)

    Returns:
        JSON string with the created audience ID
    """
    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/customaudiences"
    params = {
        "name": name,
        "subtype": "CUSTOM",
        "description": description,
        "customer_file_source": customer_file_source,
    }
    data = await make_api_request(endpoint, access_token, params, method="POST")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def add_users_to_audience(
    audience_id: str,
    phones: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
    first_names: Optional[List[str]] = None,
    last_names: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    access_token: Optional[str] = None,
) -> str:
    """
    Add users to an existing Custom Audience by uploading PII (phone numbers, emails, etc.).
    All data is SHA-256 hashed locally before sending to Meta.
    Polish phone numbers (9 digits) automatically get '48' country prefix.
    Maximum 10,000 users per call — for larger lists call multiple times.

    Args:
        audience_id: The Custom Audience ID to add users to
        phones: List of phone numbers (e.g., ['501234567', '+48501234567'])
        emails: List of email addresses
        first_names: List of first names
        last_names: List of last names
        cities: List of cities
        access_token: Meta API access token (optional)

    Returns:
        JSON string with upload result including num_received and num_invalid_entries
    """
    phones = [p for p in (phones or []) if p and p.strip()]
    emails = [e for e in (emails or []) if e and e.strip()]

    if not phones and not emails:
        return json.dumps({"error": "At least phones or emails must be provided (non-empty)"}, indent=2)

    payload = _build_user_schema_and_data(
        phones or None, emails or None, first_names, last_names, cities
    )

    if len(payload["data"]) > MAX_BATCH_SIZE:
        return json.dumps({
            "error": f"Batch too large: {len(payload['data'])} users. Maximum is {MAX_BATCH_SIZE} per call. Split into multiple calls."
        }, indent=2)

    if not payload["data"]:
        return json.dumps({"error": "No valid users after normalization (all phone numbers/emails were invalid)"}, indent=2)

    endpoint = f"{audience_id}/users"
    params = {
        "payload": payload,
    }
    data = await make_api_request(endpoint, access_token, params, method="POST")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def remove_users_from_audience(
    audience_id: str,
    phones: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
    access_token: Optional[str] = None,
) -> str:
    """
    Remove users from a Custom Audience.
    All data is SHA-256 hashed locally before sending to Meta.
    Uses POST with payload containing the users to remove (Meta's recommended approach for DELETE operations with body).

    Args:
        audience_id: The Custom Audience ID to remove users from
        phones: List of phone numbers to remove
        emails: List of email addresses to remove
        access_token: Meta API access token (optional)

    Returns:
        JSON string with removal result including num_received and num_invalid_entries
    """
    phones = [p for p in (phones or []) if p and p.strip()]
    emails = [e for e in (emails or []) if e and e.strip()]

    if not phones and not emails:
        return json.dumps({"error": "At least phones or emails must be provided (non-empty)"}, indent=2)

    payload = _build_user_schema_and_data(phones or None, emails or None)

    if not payload["data"]:
        return json.dumps({"error": "No valid users after normalization"}, indent=2)

    endpoint = f"{audience_id}/users"
    params = {
        "payload": payload,
    }
    data = await make_api_request(endpoint, access_token, params, method="DELETE")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def replace_users_in_audience(
    audience_id: str,
    phones: Optional[List[str]] = None,
    emails: Optional[List[str]] = None,
    first_names: Optional[List[str]] = None,
    last_names: Optional[List[str]] = None,
    cities: Optional[List[str]] = None,
    session_id: Optional[int] = None,
    estimated_num_total: Optional[int] = None,
    batch_seq: int = 1,
    is_last_batch: bool = True,
    access_token: Optional[str] = None,
) -> str:
    """
    Replace all users in a Custom Audience (full refresh). Uses Meta's replace session API.
    For multi-batch uploads: use the same session_id across all batches, set estimated_num_total
    to the TOTAL number of users across ALL batches, increment batch_seq, and set is_last_batch=True
    only on the final batch.

    Args:
        audience_id: The Custom Audience ID
        phones: List of phone numbers
        emails: List of email addresses
        first_names: List of first names
        last_names: List of last names
        cities: List of cities
        session_id: Session ID for multi-batch replace (use same ID across batches; omit to auto-generate)
        estimated_num_total: Total number of users across ALL batches (not just this batch). Required for multi-batch.
        batch_seq: Batch sequence number starting from 1 (increment for each batch)
        is_last_batch: Set to True on the final batch to finalize the session
        access_token: Meta API access token (optional)

    Returns:
        JSON string with upload result and session info
    """
    phones = [p for p in (phones or []) if p and p.strip()]
    emails = [e for e in (emails or []) if e and e.strip()]

    if not phones and not emails:
        return json.dumps({"error": "At least phones or emails must be provided (non-empty)"}, indent=2)

    import time
    if session_id is None:
        session_id = int(time.time() * 1000) % (2**31)

    payload = _build_user_schema_and_data(
        phones or None, emails or None, first_names, last_names, cities
    )

    if len(payload["data"]) > MAX_BATCH_SIZE:
        return json.dumps({
            "error": f"Batch too large: {len(payload['data'])} users. Maximum is {MAX_BATCH_SIZE} per call."
        }, indent=2)

    if not payload["data"]:
        return json.dumps({"error": "No valid users after normalization"}, indent=2)

    total = estimated_num_total if estimated_num_total else len(payload["data"])

    endpoint = f"{audience_id}/usersreplace"
    params = {
        "payload": payload,
        "session": {
            "session_id": session_id,
            "estimated_num_total": total,
            "batch_seq": batch_seq,
            "last_batch_flag": is_last_batch,
        },
    }
    data = await make_api_request(endpoint, access_token, params, method="POST")
    result = data if isinstance(data, dict) else {"response": data}
    result["session_id"] = session_id
    result["batch_seq"] = batch_seq
    result["is_last_batch"] = is_last_batch
    return json.dumps(result, indent=2)


@mcp_server.tool()
@meta_api_tool
async def delete_custom_audience(
    audience_id: str,
    access_token: Optional[str] = None,
) -> str:
    """
    Delete a Custom Audience.

    Args:
        audience_id: The Custom Audience ID to delete
        access_token: Meta API access token (optional)

    Returns:
        JSON string confirming deletion
    """
    endpoint = audience_id
    data = await make_api_request(endpoint, access_token, method="DELETE")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def create_lookalike_audience(
    account_id: str,
    name: str,
    source_audience_id: str,
    country: str = "PL",
    ratio: float = 0.01,
    access_token: Optional[str] = None,
) -> str:
    """
    Create a Lookalike Audience from an existing Custom Audience.

    Args:
        account_id: Ad account ID (e.g., 'act_523933962063921' or '523933962063921')
        name: Name of the lookalike audience (e.g., 'LAL 1% - VIP CRAFTBE')
        source_audience_id: ID of the source Custom Audience to base the lookalike on
        country: Target country code (default: 'PL')
        ratio: Lookalike ratio from 0.01 (1%, most similar) to 0.20 (20%, broader). Common: 0.01, 0.02, 0.03
        access_token: Meta API access token (optional)

    Returns:
        JSON string with the created lookalike audience ID
    """
    account_id = ensure_act_prefix(account_id)
    endpoint = f"{account_id}/customaudiences"

    lookalike_spec = {
        "type": "custom_ratio",
        "ratio": ratio,
        "country": country,
        "origin": [{"id": source_audience_id, "type": "custom_audience"}],
    }

    params = {
        "name": name,
        "subtype": "LOOKALIKE",
        "lookalike_spec": lookalike_spec,
    }
    data = await make_api_request(endpoint, access_token, params, method="POST")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def create_website_audience(
    account_id: str,
    name: str,
    pixel_id: str,
    event_name: str = "PageView",
    retention_days: int = 180,
    exclusion_event: Optional[str] = None,
    exclusion_retention_days: Optional[int] = None,
    description: str = "",
    prefill: bool = True,
    access_token: Optional[str] = None,
) -> str:
    """
    Create a Website Custom Audience based on pixel events (retargeting).
    Uses v24.0 rule-based format with event_sources (NOT subtype=WEBSITE which is deprecated).

    Args:
        account_id: Ad account ID (e.g., 'act_523933962063921' or '523933962063921')
        name: Name of the audience (e.g., 'WCA — Wszyscy odwiedzający 180d')
        pixel_id: Meta Pixel ID (e.g., '1587798942251611')
        event_name: Pixel event to match (PageView, ViewContent, AddToCart, InitiateCheckout, Purchase, Lead, CompleteRegistration, etc.)
        retention_days: How many days to retain users (1-180, default 180)
        exclusion_event: Optional event to exclude (e.g., 'Purchase' to create cart abandoners)
        exclusion_retention_days: Retention days for exclusion rule (defaults to same as retention_days)
        description: Description of the audience
        prefill: Whether to backfill with existing pixel data (default True)
        access_token: Meta API access token (optional)

    Returns:
        JSON string with the created audience ID
    """
    account_id = ensure_act_prefix(account_id)
    retention_seconds = min(retention_days, 180) * 86400

    rule: Dict[str, Any] = {
        "inclusions": {
            "operator": "or",
            "rules": [
                {
                    "event_sources": [{"id": pixel_id, "type": "pixel"}],
                    "retention_seconds": retention_seconds,
                    "filter": {
                        "operator": "and",
                        "filters": [{"field": "event", "operator": "=", "value": event_name}],
                    },
                }
            ],
        }
    }

    if exclusion_event:
        excl_seconds = min(exclusion_retention_days or retention_days, 180) * 86400
        rule["exclusions"] = {
            "operator": "or",
            "rules": [
                {
                    "event_sources": [{"id": pixel_id, "type": "pixel"}],
                    "retention_seconds": excl_seconds,
                    "filter": {
                        "operator": "and",
                        "filters": [{"field": "event", "operator": "=", "value": exclusion_event}],
                    },
                }
            ],
        }

    endpoint = f"{account_id}/customaudiences"
    params: Dict[str, Any] = {
        "name": name,
        "rule": json.dumps(rule),
        "prefill": 1 if prefill else 0,
    }
    if description:
        params["description"] = description

    data = await make_api_request(endpoint, access_token, params, method="POST")
    return json.dumps(data, indent=2)


@mcp_server.tool()
@meta_api_tool
async def get_audience_share_status(
    audience_id: str,
    access_token: Optional[str] = None,
) -> str:
    """
    Check the sharing and delivery status of a Custom Audience (useful to verify if audience is ready for ads).

    Args:
        audience_id: The Custom Audience ID
        access_token: Meta API access token (optional)

    Returns:
        JSON string with delivery_status, operation_status, and approximate_count
    """
    endpoint = audience_id
    params = {
        "fields": "id,name,delivery_status,operation_status,data_source,time_updated",
    }
    data = await make_api_request(endpoint, access_token, params)
    return json.dumps(data, indent=2)
