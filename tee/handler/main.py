"""
Kin TEE Request Handler

This is the core application that runs INSIDE the CPU CVM (TEE #1).
It handles the complete lifecycle of a Kin conversation:

1. Loads the user's spirit.md from the dstack-encrypted volume
2. Constructs the full system prompt (including spirit.md contents)
3. Verifies the ACI gateway attestation (GPU TEE)
4. Sends the prompt to the Phala Confidential Inference API (TEE #2)
5. Verifies the response receipt (upstream.verified)
6. Parses the response for [SPIRIT]...[/SPIRIT] blocks
7. Appends spirit entries to the encrypted spirit.md
8. Returns ONLY the clean response (spirit blocks stripped)

Nothing in spirit.md ever leaves TEE #1 in plaintext. The prompt is
sent over attested TLS to TEE #2. The clean response is the only
data that crosses the trust boundary to the proxy.
"""

import json
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from tee.handler.spirit import (
    load_spirit,
    get_recent_entries,
    get_compressed_history,
    get_metadata,
    append_spirit_entries,
    extract_spirit_blocks,
    SpiritMetadata,
)
from tee.prompts.system_prompt import (
    build_system_prompt,
    VERIFICATION_TOOLS,
)
from tee.inference.client import PhalaInferenceClient
from tee.inference.receipts import verify_receipt_response
from tee.verification.attestation import verify_attestation
from tee.verification.encryption import verify_encryption
from tee.verification.network import verify_network
from tee.verification.code_hash import verify_code_hash

logger = logging.getLogger("kin.tee")

MAX_SPIRIT_RECENT = int(os.environ.get("KIN_SPIRIT_RECENT_ENTRIES", "20"))

_inference_client: Optional[PhalaInferenceClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _inference_client
    _inference_client = PhalaInferenceClient()
    logger.info("Kin TEE handler starting inside CPU CVM trust boundary")
    yield
    logger.info("Kin TEE handler shutting down")


app = FastAPI(
    title="Kin TEE Handler",
    description=(
        "Runs inside the CPU CVM (TEE #1). Manages spirit.md and routes "
        "inference to the Phala Confidential Inference API (TEE #2)."
    ),
    lifespan=lifespan,
)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    conversation_history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    metadata: dict


class VerificationResponse(BaseModel):
    tool_name: str
    result: dict
    passed: bool


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Handle a chat message. This is the main endpoint called by the proxy.

    The full flow:
    1. Load user's spirit.md
    2. Build system prompt with spirit.md injected
    3. Verify ACI gateway attestation
    4. Call Phala Confidential Inference API
    5. Verify response receipt (upstream.verified)
    6. Parse response, extract spirit blocks
    7. Save spirit entries to encrypted disk (only if receipt verified)
    8. Return clean response + metadata only
    """
    spirit_content = load_spirit(request.user_id)
    compressed = get_compressed_history(request.user_id)
    recent = get_recent_entries(request.user_id, n=MAX_SPIRIT_RECENT)

    prompt_spirit = recent if recent else spirit_content
    if compressed:
        prompt_spirit = f"{compressed}\n\n--- RECENT ENTRIES ---\n\n{prompt_spirit}"

    system_prompt = build_system_prompt(
        spirit_content=prompt_spirit,
        compressed_history="",
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in request.conversation_history:
        messages.append({
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        })
    messages.append({"role": "user", "content": request.message})

    nonce = os.urandom(16).hex()
    try:
        await _inference_client.verify_gateway_attestation(nonce)
    except Exception as e:
        logger.error("ACI gateway attestation failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Could not verify inference API TEE attestation",
        )

    result, receipt_id, receipt_verified = await _call_inference(messages)
    raw_response = result["choices"][0]["message"]["content"]

    tool_calls = result["choices"][0]["message"].get("tool_calls", [])
    tool_results = await _handle_tool_calls(tool_calls)

    if tool_results:
        messages.append(result["choices"][0]["message"])
        for tool_result in tool_results:
            messages.append(tool_result)

        result, follow_receipt_id, follow_receipt_verified = await _call_inference(messages)
        raw_response = result["choices"][0]["message"]["content"]
        receipt_verified = receipt_verified and follow_receipt_verified

    clean_response, spirit_entries = extract_spirit_blocks(raw_response)

    if receipt_verified:
        metadata = append_spirit_entries(request.user_id, spirit_entries)
    else:
        logger.warning(
            "Skipping spirit.md writes — receipt verification failed for user %s",
            request.user_id,
        )
        metadata = get_metadata(request.user_id)

    response_metadata = metadata.to_dict()
    response_metadata["receipt_verified"] = receipt_verified

    return ChatResponse(
        response=clean_response,
        metadata=response_metadata,
    )


async def _call_inference(messages: list) -> tuple:
    """Call the inference API and verify the response receipt."""
    try:
        result, receipt_id = await _inference_client.chat_completion(
            messages=messages,
            tools=VERIFICATION_TOOLS,
            temperature=0.7,
            max_tokens=4096,
        )
    except Exception as e:
        logger.error("Inference API request failed: %s", e)
        raise HTTPException(status_code=502, detail="Inference failed")

    receipt_verified = False
    if receipt_id:
        try:
            receipt_result = await _inference_client.verify_receipt(receipt_id)
            verification = receipt_result["verification"]
            receipt_verified = verification["passed"]
            _cache_receipt(receipt_result)
            if not receipt_verified:
                logger.warning("Receipt verification failed: %s", verification["details"])
        except Exception as e:
            logger.warning("Could not verify receipt %s: %s", receipt_id, e)
    else:
        logger.warning("No receipt ID in inference response — cannot verify TEE chain")

    return result, receipt_id, receipt_verified


def _cache_receipt(receipt_result: dict):
    """Cache the latest receipt so the verify_attestation tool can read it."""
    try:
        cache = {
            "upstream_verified": receipt_result.get("verification", {}).get("upstream_verified", False),
            "passed": receipt_result.get("verification", {}).get("passed", False),
            "receipt": receipt_result.get("receipt", {}),
        }
        Path("/tmp/kin-last-receipt.json").write_text(
            json.dumps(cache), encoding="utf-8"
        )
    except OSError:
        pass


async def _handle_tool_calls(tool_calls: list) -> list[dict]:
    """Execute verification tool calls requested by the model."""
    if not tool_calls:
        return []

    results = []
    for call in tool_calls:
        fn_name = call["function"]["name"]
        call_id = call["id"]

        if fn_name == "verify_attestation":
            result = verify_attestation()
        elif fn_name == "verify_encryption":
            result = verify_encryption()
        elif fn_name == "verify_network":
            result = verify_network()
        elif fn_name == "verify_code_hash":
            result = verify_code_hash()
        else:
            result = {"error": f"Unknown tool: {fn_name}"}

        results.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": json.dumps(result),
        })

    return results


@app.get("/metadata/{user_id}")
async def spirit_metadata(user_id: str) -> dict:
    """
    Return spirit.md metadata for the constellation visualization.

    This endpoint returns ONLY metadata: entry count, timestamps,
    abstract categories, and depth scores. NEVER content.

    This is the only spirit-related data that leaves the TEE.
    """
    metadata = get_metadata(user_id)
    return metadata.to_dict()


@app.get("/health")
async def health():
    return {"status": "ok", "inside_tee": True}
