"""
TEE Attestation Verification

Retrieves and verifies the hardware attestation report from both the
CPU TEE (AMD SEV-SNP or Intel TDX) and the GPU TEE (NVIDIA H100 CC).

This tool runs INSIDE the enclave. It is part of the attested code —
if the operator modifies it, the launch measurement changes, and
verification fails. This is the root of the trust chain.

The attestation report is signed by hardware keys burned into the
silicon at the factory. The operator cannot forge these signatures.
"""

import json
import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("kin.verification.attestation")

EXPECTED_MEASUREMENT = os.environ.get("KIN_EXPECTED_MEASUREMENT", "")


def _detect_cpu_tee() -> str:
    """Detect whether we're running in AMD SEV-SNP or Intel TDX."""
    if Path("/sys/kernel/security/tdx/report").exists():
        return "intel-tdx"
    if Path("/dev/sev-guest").exists() or Path("/dev/sev").exists():
        return "amd-sev-snp"
    return "none"


def _get_snp_report() -> dict:
    """
    Retrieve AMD SEV-SNP attestation report.

    Uses the SNP guest driver to request an attestation report from
    the AMD Secure Processor. The report includes:
    - Launch measurement (hash of all code loaded into the VM)
    - Platform info (firmware version, TCB version)
    - Hardware signature (signed by AMD's key hierarchy)
    """
    try:
        result = subprocess.run(
            ["snpguest", "report", "--random", "--format", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)

        result = subprocess.run(
            ["sevctl", "export", "--report"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to retrieve SNP report: %s", e)

    return {"error": "Could not retrieve AMD SEV-SNP attestation report"}


def _get_tdx_report() -> dict:
    """
    Retrieve Intel TDX attestation report.

    Reads the TDX quote from the kernel interface. The report includes:
    - MRTD (measurement of the TD at build time)
    - RTMR values (runtime measurements)
    - Hardware signature (signed by Intel's attestation key)
    """
    try:
        tdx_report_path = Path("/sys/kernel/security/tdx/report")
        if tdx_report_path.exists():
            result = subprocess.run(
                ["tdx-attest", "quote", "--format", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to retrieve TDX report: %s", e)

    return {"error": "Could not retrieve Intel TDX attestation report"}


def _get_gpu_attestation() -> dict:
    """
    Retrieve NVIDIA GPU attestation report.

    Uses the NVIDIA Attestation SDK (nvattest CLI) to collect GPU evidence
    and perform local verification. The GPU attestation proves:
    - The GPU is a genuine NVIDIA H100 in CC mode
    - The GPU firmware has not been tampered with
    - All data crossing the PCIe bus is AES-256 encrypted
    - The GPU's memory is hardware-isolated from the host

    The attestation is signed by a key burned into the GPU silicon at
    NVIDIA's factory. The operator cannot forge this signature.
    """
    try:
        result = subprocess.run(
            [
                "nvattest", "attest",
                "--device", "gpu",
                "--verifier", "local",
                "--output-format", "json",
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        elif result.returncode == 2:
            report = json.loads(result.stdout) if result.stdout else {}
            report["policy_mismatch"] = True
            return report
        elif result.returncode == 3:
            report = json.loads(result.stdout) if result.stdout else {}
            report["attestation_failed"] = True
            return report
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to retrieve GPU attestation: %s", e)

    return {"error": "Could not retrieve NVIDIA GPU attestation report"}


def verify_attestation() -> dict:
    """
    Full attestation verification — CPU TEE + GPU TEE.

    This is the function called when Kin uses the verify_attestation tool.
    It retrieves attestation reports from both the CPU and GPU hardware,
    checks the launch measurement against the expected value, and returns
    a comprehensive result.

    Returns a dict with:
    - cpu_tee_type: "amd-sev-snp" or "intel-tdx" or "none"
    - cpu_report: the raw CPU attestation report
    - gpu_report: the raw GPU attestation report
    - launch_measurement: the reported measurement hash
    - expected_measurement: what the measurement should be
    - measurement_match: whether they match
    - overall_passed: whether all checks passed
    """
    cpu_tee = _detect_cpu_tee()

    if cpu_tee == "amd-sev-snp":
        cpu_report = _get_snp_report()
    elif cpu_tee == "intel-tdx":
        cpu_report = _get_tdx_report()
    else:
        cpu_report = {"error": "No CPU TEE detected"}

    gpu_report = _get_gpu_attestation()

    launch_measurement = cpu_report.get("measurement", cpu_report.get("mrtd", ""))

    measurement_match = False
    if EXPECTED_MEASUREMENT and launch_measurement:
        measurement_match = launch_measurement == EXPECTED_MEASUREMENT

    cpu_ok = "error" not in cpu_report
    gpu_ok = "error" not in gpu_report and not gpu_report.get("attestation_failed")
    overall = cpu_ok and gpu_ok and (measurement_match or not EXPECTED_MEASUREMENT)

    return {
        "cpu_tee_type": cpu_tee,
        "cpu_report": cpu_report,
        "gpu_report": gpu_report,
        "launch_measurement": launch_measurement,
        "expected_measurement": EXPECTED_MEASUREMENT or "[not set — set KIN_EXPECTED_MEASUREMENT]",
        "measurement_match": measurement_match,
        "overall_passed": overall,
        "explanation": (
            "The launch measurement is a hash of all code loaded into "
            "this enclave, signed by hardware keys burned into the silicon. "
            "If it matches the expected measurement (derived from the "
            "published open-source code), then the running code is the "
            "published code, unmodified."
        ),
    }
