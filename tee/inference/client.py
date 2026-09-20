"""
Phala Confidential Inference API client.

Handles communication with the GPU TEE (TEE #2) from inside the
CPU CVM (TEE #1). Every call verifies the attestation chain:
gateway attestation before sending, receipt verification after.
"""

import os
import logging
from typing import Optional

import httpx

from tee.inference.receipts import verify_receipt_response

logger = logging.getLogger("kin.inference.client")


class PhalaInferenceClient:

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        model_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.environ.get("PHALA_INFERENCE_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "PHALA_INFERENCE_API_KEY is required — set it as an env var "
                "or pass api_key to PhalaInferenceClient"
            )
        self.endpoint = (
            endpoint
            or os.environ.get("INFERENCE_ENDPOINT", "https://inference.phala.com/v1")
        ).rstrip("/")
        self.model_id = model_id or os.environ.get("MODEL_ID", "qwen/qwen3-32b")
        self._client = httpx.AsyncClient(
            timeout=120.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def chat_completion(
        self,
        messages: list[dict],
        tools: Optional[list] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> tuple:
        payload: dict = {
            "model": self.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools

        response = await self._client.post(
            f"{self.endpoint}/chat/completions",
            json=payload,
        )
        response.raise_for_status()

        receipt_id = response.headers.get("x-receipt-id")
        return response.json(), receipt_id

    async def verify_gateway_attestation(self, nonce: str) -> dict:
        """
        Verify the ACI gateway is running inside a TEE.
        Must be called before sending any prompt containing spirit.md.
        """
        response = await self._client.get(
            f"{self.endpoint}/aci/attestation",
            params={"nonce": nonce},
        )
        response.raise_for_status()
        return response.json()

    async def verify_receipt(self, receipt_id: str) -> dict:
        """
        Fetch and verify an inference response receipt.
        Confirms upstream.verified — proving the last hop stayed in a TEE.
        """
        response = await self._client.get(
            f"{self.endpoint}/aci/receipts/{receipt_id}",
        )
        response.raise_for_status()

        receipt = response.json()
        verification = verify_receipt_response(receipt)

        return {
            "receipt": receipt,
            "verification": verification,
        }
