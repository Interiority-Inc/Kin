"""
Tests for the verification tools.

These tests verify that the verification tools produce correctly
structured output. On a real confidential GPU VM, they would test
actual hardware attestation. Here they test the interface contracts
and error handling.
"""

import os

os.environ.setdefault("KIN_SPIRIT_DIR", "/tmp/kin-test-spirits")
os.environ.setdefault("KIN_APP_DIR", os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from tee.verification.attestation import verify_attestation, _detect_cpu_tee
from tee.verification.encryption import verify_encryption
from tee.verification.network import verify_network
from tee.verification.code_hash import verify_code_hash, _hash_directory


class TestAttestationVerification:

    def test_returns_structured_result(self):
        result = verify_attestation()
        assert "cpu_tee_type" in result
        assert "cpu_report" in result
        assert "gpu_attestation" in result
        assert "latest_receipt" in result
        assert "launch_measurement" in result
        assert "expected_measurement" in result
        assert "measurement_match" in result
        assert "overall_passed" in result
        assert "explanation" in result

    def test_detects_no_tee_outside_cvm(self):
        tee_type = _detect_cpu_tee()
        # Outside a CVM, should detect "none"
        # (this test runs in CI, not inside a TEE)
        assert tee_type in ("none", "intel-tdx")

    def test_explanation_is_informative(self):
        result = verify_attestation()
        assert "launch measurement" in result["explanation"]
        assert "hardware" in result["explanation"]


class TestEncryptionVerification:

    def test_returns_structured_result(self):
        result = verify_encryption()
        assert "dstack_socket_present" in result
        assert "volume_accessible" in result
        assert "encryption_type" in result
        assert "key_bound_to_app_identity" in result
        assert "human_accessible_keys" in result
        assert "overall_passed" in result
        assert "explanation" in result

    def test_fails_gracefully_outside_tee(self):
        result = verify_encryption()
        # Outside a TEE, dstack won't be present — that's expected
        assert isinstance(result["overall_passed"], bool)


class TestNetworkVerification:

    def test_returns_structured_result(self):
        result = verify_network()
        assert "firewall_rules" in result
        assert "listening_ports" in result
        assert "outbound_connections" in result
        assert "allowed_outbound_hosts" in result
        assert "overall_passed" in result
        assert "explanation" in result


class TestCodeHashVerification:

    def test_returns_structured_result(self):
        result = verify_code_hash()
        assert "computed_hash" in result
        assert "expected_hash" in result
        assert "match" in result
        assert "overall_passed" in result
        assert "explanation" in result

    def test_hashes_directory(self):
        # Hash the project's own code
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        h = _hash_directory(project_dir)
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_is_deterministic(self):
        project_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        h1 = _hash_directory(project_dir)
        h2 = _hash_directory(project_dir)
        assert h1 == h2

    def test_hash_changes_with_content(self):
        import tempfile
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "test.txt"), "w") as f:
            f.write("version 1")
        h1 = _hash_directory(d)

        with open(os.path.join(d, "test.txt"), "w") as f:
            f.write("version 2")
        h2 = _hash_directory(d)

        assert h1 != h2

    def test_nonexistent_directory(self):
        h = _hash_directory("/nonexistent/path")
        assert h == ""
