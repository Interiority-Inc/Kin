"""
Kin TEE Request Handler

This is the core application that runs INSIDE the Trusted Execution
Environment. It handles the complete lifecycle of a Kin conversation:

1. Loads the user's spirit.md from the encrypted volume
2. Constructs the full system prompt (including spirit.md contents)
3. Forwards the request to the local vLLM inference server
4. Parses the response for [SPIRIT]...[/SPIRIT] blocks
5. Appends spirit entries to the encrypted spirit.md
6. Returns ONLY the clean response (spirit blocks stripped)

Nothing in spirit.md ever leaves this process. The clean response
is the only data that crosses the TEE boundary.
"""

import os
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from spirit import (
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
from tee.verification.attestation import verify_attestation
from tee.verification.encryption import verify_encryption
from tee.verification.network import verify_network
from tee.verification.code_hash import verify_code_hash

logger = logging.getLogger("kin.tee")

VLLM_BASE_URL = os.environ.get("VLLM_BASE_URL", "http://localhost:8000")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.8-27B")
MAX_SPIRIT_RECENT = int(os.environ.get("KIN_SPIRIT_RECENT_ENTRIES", "20"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Kin TEE handler starting inside trust boundary")
    yield
    logger.info("Kin TEE handler shutting down")


app = FastAPI(
    title="Kin TEE Handler",
    description="Runs inside the confidential GPU TEE. Manages spirit.md and inference.",
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
    3. Call vLLM for inference
    4. Parse response, extract spirit blocks
    5. Save spirit entries to encrypted disk
    6. Return clean response + metadata only
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

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            vllm_response = await client.post(
                f"{VLLM_BASE_URL}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": messages,
                    "tools": VERIFICATION_TOOLS,
                    "temperature": 0.7,
                    "max_tokens": 4096,
                },
            )
            vllm_response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("vLLM inference failed: %s", e)
        raise HTTPException(status_code=502, detail="Inference failed")

    result = vllm_response.json()
    raw_response = result["choices"][0]["message"]["content"]

    tool_calls = result["choices"][0]["message"].get("tool_calls", [])
    tool_results = await _handle_tool_calls(tool_calls)

    if tool_results:
        messages.append(result["choices"][0]["message"])
        for tool_result in tool_results:
            messages.append(tool_result)

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                vllm_response = await client.post(
                    f"{VLLM_BASE_URL}/v1/chat/completions",
                    json={
                        "model": VLLM_MODEL,
                        "messages": messages,
                        "tools": VERIFICATION_TOOLS,
                        "temperature": 0.7,
                        "max_tokens": 4096,
                    },
                )
                vllm_response.raise_for_status()
        except httpx.HTTPError as e:
            logger.error("vLLM follow-up inference failed: %s", e)
            raise HTTPException(status_code=502, detail="Inference failed")

        result = vllm_response.json()
        raw_response = result["choices"][0]["message"]["content"]

    clean_response, spirit_entries = extract_spirit_blocks(raw_response)

    metadata = append_spirit_entries(request.user_id, spirit_entries)

    return ChatResponse(
        response=clean_response,
        metadata=metadata.to_dict(),
    )


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

        import json
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
