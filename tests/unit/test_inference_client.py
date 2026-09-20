"""
Tests for the Phala Confidential Inference API client.

Verifies that the client:
1. Correctly initializes from env vars or explicit params
2. Sends properly structured requests to the inference API
3. Extracts receipt IDs from response headers
4. Verifies receipts for upstream.verified status
5. Handles errors gracefully
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("PHALA_INFERENCE_API_KEY", "test-key")
os.environ.setdefault("KIN_SPIRIT_DIR", "/tmp/kin-test-spirits")

from tee.inference.client import PhalaInferenceClient
from tee.inference.receipts import verify_receipt_response


class TestPhalaInferenceClient:

    def test_client_init_with_env_vars(self):
        client = PhalaInferenceClient()
        assert client.api_key == "test-key"
        assert "inference.phala.com" in client.endpoint
        assert client.model_id == "qwen/qwen3-32b"

    def test_client_init_with_explicit_params(self):
        client = PhalaInferenceClient(
            api_key="custom-key",
            endpoint="https://custom.endpoint/v1",
            model_id="qwen/qwen3-14b",
        )
        assert client.api_key == "custom-key"
        assert client.endpoint == "https://custom.endpoint/v1"
        assert client.model_id == "qwen/qwen3-14b"

    def test_client_raises_without_api_key(self):
        env_without_key = {k: v for k, v in os.environ.items() if k != "PHALA_INFERENCE_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with pytest.raises(ValueError):
                PhalaInferenceClient()

    @pytest.mark.asyncio
    async def test_chat_completion_returns_response_and_receipt(self):
        client = PhalaInferenceClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!", "role": "assistant"}}],
        }
        mock_response.headers = {"x-receipt-id": "receipt-123"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result, receipt_id = await client.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert result["choices"][0]["message"]["content"] == "Hello!"
            assert receipt_id == "receipt-123"

    @pytest.mark.asyncio
    async def test_chat_completion_handles_missing_receipt(self):
        client = PhalaInferenceClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!", "role": "assistant"}}],
        }
        mock_response.headers = {}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_client") as mock_client:
            mock_client.post = AsyncMock(return_value=mock_response)
            result, receipt_id = await client.chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
            )
            assert receipt_id is None

    @pytest.mark.asyncio
    async def test_verify_receipt_calls_correct_endpoint(self):
        client = PhalaInferenceClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "upstream": {"verified": True},
            "request_hash": "abc",
            "response_hash": "def",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            result = await client.verify_receipt("receipt-123")
            mock_client.get.assert_called_once()
            call_url = mock_client.get.call_args[0][0]
            assert "receipt-123" in call_url
            assert result["verification"]["passed"] is True

    @pytest.mark.asyncio
    async def test_verify_gateway_attestation_sends_nonce(self):
        client = PhalaInferenceClient()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"attestation": "quote-data"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_client") as mock_client:
            mock_client.get = AsyncMock(return_value=mock_response)
            await client.verify_gateway_attestation("test-nonce-123")
            call_kwargs = mock_client.get.call_args
            assert call_kwargs[1]["params"]["nonce"] == "test-nonce-123"


class TestReceiptVerification:

    def test_passes_when_upstream_verified(self):
        receipt = {
            "upstream": {"verified": True},
            "request_hash": "abc123",
            "response_hash": "def456",
        }
        result = verify_receipt_response(receipt)
        assert result["passed"] is True
        assert result["upstream_verified"] is True

    def test_fails_when_upstream_not_verified(self):
        receipt = {
            "upstream": {"verified": False},
            "request_hash": "abc123",
            "response_hash": "def456",
        }
        result = verify_receipt_response(receipt)
        assert result["passed"] is False
        assert result["upstream_verified"] is False

    def test_fails_when_upstream_missing(self):
        receipt = {"request_hash": "abc123"}
        result = verify_receipt_response(receipt)
        assert result["passed"] is False

    def test_fails_on_empty_receipt(self):
        result = verify_receipt_response({})
        assert result["passed"] is False

    def test_includes_hash_fields_in_result(self):
        receipt = {
            "upstream": {"verified": True},
            "request_hash": "abc123",
            "response_hash": "def456",
        }
        result = verify_receipt_response(receipt)
        assert result["has_request_hash"] is True
        assert result["has_response_hash"] is True
