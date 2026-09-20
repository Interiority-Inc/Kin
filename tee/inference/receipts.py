"""
Inference receipt verification.

Each response from the Phala Confidential Inference API includes a
signed receipt confirming the upstream inference provider was verified
as running inside a TEE. This module validates those receipts.
"""


def verify_receipt_response(receipt: dict) -> dict:
    """
    Verify that a receipt confirms TEE-protected inference.

    The receipt contains an event_log with typed events. We check:
    - An "upstream.verified" event exists with result "verified"
    - "request.received" and "response.returned" events have body hashes

    Returns a structured result with passed/failed status.
    """
    event_log = receipt.get("event_log", [])

    upstream_verified = any(
        e.get("type") == "upstream.verified" and e.get("result") == "verified"
        for e in event_log
    )

    has_request_hash = any(
        e.get("type") == "request.received" and e.get("body_hash")
        for e in event_log
    )
    has_response_hash = any(
        e.get("type") == "response.returned" and e.get("body_hash")
        for e in event_log
    )

    passed = upstream_verified and has_request_hash and has_response_hash

    if not upstream_verified:
        details = "upstream.verified event missing or not verified — inference may not have run in a TEE"
    elif not has_request_hash or not has_response_hash:
        details = "receipt is missing request or response hash — integrity cannot be confirmed"
    else:
        details = "receipt valid: upstream TEE verified, request and response hashes present"

    return {
        "passed": passed,
        "upstream_verified": upstream_verified,
        "has_request_hash": has_request_hash,
        "has_response_hash": has_response_hash,
        "details": details,
    }
