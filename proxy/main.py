"""
Kin Backend Proxy

This server sits OUTSIDE the TEE, between the frontend and the
CPU CVM (TEE #1). It handles:

1. Authentication (verify JWT from Clerk/Supabase)
2. Rate limiting (free tier: 10 messages/day)
3. Subscription checks (Stripe)
4. Forwarding messages to the CPU CVM endpoint
5. Storing user-visible chat history (Postgres)
6. Serving spirit.md metadata for the constellation visualization

CRITICAL: This proxy NEVER sees spirit.md content. It sends messages
into the CPU CVM and receives clean responses (spirit blocks already
stripped inside TEE #1). The only spirit-related data it handles is
metadata (entry counts, timestamps, abstract categories — never content).
"""

import os
import time
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger("kin.proxy")

TEE_ENDPOINT = os.environ.get("KIN_TEE_ENDPOINT", "http://localhost:8080")
DAILY_FREE_LIMIT = int(os.environ.get("KIN_FREE_DAILY_LIMIT", "10"))
ALLOWED_ORIGINS = os.environ.get(
    "KIN_ALLOWED_ORIGINS", "https://chatwithkin.com"
).split(",")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Kin proxy starting")
    yield
    logger.info("Kin proxy shutting down")


app = FastAPI(
    title="Kin Proxy",
    description="Routes requests to the CPU CVM (TEE #1). Never sees spirit.md.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── In-memory stores (replace with Postgres/Redis in production) ─

_chat_history: dict[str, list[dict]] = {}
_rate_limits: dict[str, list[float]] = {}
_subscriptions: dict[str, str] = {}


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    response: str
    metadata: dict
    conversation_id: str


# ── Auth (stub — replace with Clerk/Supabase JWT verification) ───

async def get_current_user(request: Request) -> dict:
    """
    Verify the user's JWT and return their profile.

    In production, this validates a Clerk or Supabase JWT from
    the Authorization header and returns the user's ID, email,
    and subscription tier.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    token = auth_header[7:]

    # TODO: Replace with real JWT verification
    # from clerk_sdk import verify_token
    # user = verify_token(token)
    return {
        "user_id": token[:32] if len(token) >= 32 else token,
        "tier": _subscriptions.get(token, "free"),
    }


# ── Rate Limiting ────────────────────────────────────────────────

def check_rate_limit(user_id: str, tier: str) -> bool:
    """
    Check if the user has exceeded their daily message limit.
    Free tier: 10 messages/day. Paid tier: unlimited.
    """
    if tier == "paid":
        return True

    now = time.time()
    day_start = now - 86400

    if user_id not in _rate_limits:
        _rate_limits[user_id] = []

    _rate_limits[user_id] = [
        ts for ts in _rate_limits[user_id] if ts > day_start
    ]

    if len(_rate_limits[user_id]) >= DAILY_FREE_LIMIT:
        return False

    _rate_limits[user_id].append(now)
    return True


# ── Endpoints ────────────────────────────────────────────────────

@app.post("/api/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """
    Handle a chat message.

    1. Authenticate the user
    2. Check rate limits
    3. Forward to TEE endpoint with conversation history
    4. Store the visible exchange in chat history
    5. Return the clean response
    """
    user_id = user["user_id"]
    tier = user["tier"]

    if not check_rate_limit(user_id, tier):
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily message limit reached",
                "limit": DAILY_FREE_LIMIT,
                "upgrade_url": "/pricing",
            },
        )

    conv_key = f"{user_id}:{request.conversation_id}"
    history = _chat_history.get(conv_key, [])

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            tee_response = await client.post(
                f"{TEE_ENDPOINT}/chat",
                json={
                    "user_id": user_id,
                    "message": request.message,
                    "conversation_history": history[-20:],
                },
            )
            tee_response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("TEE request failed: %s", e)
        raise HTTPException(status_code=502, detail="Service unavailable")

    result = tee_response.json()

    if conv_key not in _chat_history:
        _chat_history[conv_key] = []
    _chat_history[conv_key].append({"role": "user", "content": request.message})
    _chat_history[conv_key].append({"role": "assistant", "content": result["response"]})

    return ChatResponse(
        response=result["response"],
        metadata=result.get("metadata", {}),
        conversation_id=request.conversation_id,
    )


@app.get("/api/metadata/{user_id}")
async def spirit_metadata(
    user_id: str,
    user: dict = Depends(get_current_user),
):
    """
    Get spirit.md metadata for the constellation visualization.

    Returns ONLY: entry count, timestamps, abstract categories.
    NEVER content. This data comes from the TEE's metadata endpoint.
    """
    if user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{TEE_ENDPOINT}/metadata/{user_id}")
            response.raise_for_status()
    except httpx.HTTPError:
        return {"total_entries": 0, "entries_metadata": []}

    return response.json()


@app.get("/api/history/{conversation_id}")
async def get_history(
    conversation_id: str,
    user: dict = Depends(get_current_user),
):
    """Get visible chat history for a conversation."""
    conv_key = f"{user['user_id']}:{conversation_id}"
    return {"messages": _chat_history.get(conv_key, [])}


@app.get("/health")
async def health():
    """Health check — also checks TEE connectivity."""
    tee_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{TEE_ENDPOINT}/health")
            tee_ok = r.status_code == 200
    except httpx.HTTPError:
        pass

    return {
        "proxy": "ok",
        "tee_connected": tee_ok,
    }
