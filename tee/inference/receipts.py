"""
Inference receipt verification.

Each response from the Phala Confidential Inference API includes a
signed receipt confirming the upstream inference provider was verified
as running inside a TEE. This module validates those receipts.
"""


def verify_receipt_response(receipt: dict) -> dict:
    """
    Verify that a receipt confirms TEE-protected inference.

    Checks:
    - upstream.verified is present and true
    - request_hash and response_hash are present (integrity)

    Returns a structured result with passed/failed status.
    """
    upstream = receipt.get("upstream", {})
    upstream_verified = upstream.get("verified", False) if isinstance(upstream, dict) else False

    has_request_hash = bool(receipt.get("request_hash"))
    has_response_hash = bool(receipt.get("response_hash"))

    passed = upstream_verified and has_request_hash and has_response_hash

    if not upstream_verified:
        details = "upstream.verified is false or missing — inference may not have run in a TEE"
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
