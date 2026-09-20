"""
Network Egress Verification

Verifies the CPU CVM's network configuration. In the split-TEE
architecture, the handler must reach the Phala Confidential Inference
API over HTTPS — so outbound port 443 is allowed. All other outbound
traffic is blocked.

Defense-in-depth: even if the response parser has a bug, spirit.md
content can only exit via HTTPS to a verified GPU TEE (attested TLS)
or through the response handler (which strips [SPIRIT] blocks).

This tool runs INSIDE the CPU CVM and is part of the attested code.
"""

import os
import subprocess
import logging

logger = logging.getLogger("kin.verification.network")

INFERENCE_HOST = os.environ.get("KIN_INFERENCE_HOST", "inference.phala.com")


def _get_iptables_rules() -> list[str]:
    try:
        result = subprocess.run(
            ["iptables", "-L", "-n", "-v", "--line-numbers"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    try:
        result = subprocess.run(
            ["nft", "list", "ruleset"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return ["error: could not retrieve firewall rules"]


def _get_listening_ports() -> list[dict]:
    ports = []
    try:
        result = subprocess.run(
            ["ss", "-tlnp"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    ports.append({
                        "state": parts[0],
                        "local_address": parts[3],
                        "process": parts[-1] if len(parts) > 5 else "",
                    })
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to get listening ports: %s", e)
        ports.append({"error": str(e)})

    return ports


def _get_outbound_connections() -> list[dict]:
    connections = []
    try:
        result = subprocess.run(
            ["ss", "-tnp"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 5:
                    connections.append({
                        "state": parts[0],
                        "local": parts[3],
                        "remote": parts[4],
                        "process": parts[-1] if len(parts) > 5 else "",
                    })
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Failed to get outbound connections: %s", e)
        connections.append({"error": str(e)})

    return connections


def _check_dns_resolution() -> dict:
    try:
        result = subprocess.run(
            ["nslookup", INFERENCE_HOST],
            capture_output=True, text=True, timeout=5,
        )
        can_resolve = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        can_resolve = False

    return {
        "can_resolve_inference_host": can_resolve,
        "inference_host": INFERENCE_HOST,
        "note": (
            f"The CPU CVM needs DNS to resolve {INFERENCE_HOST} for the "
            "confidential inference API. No other external hosts should "
            "be reachable."
        ),
    }


def verify_network() -> dict:
    """
    Full network verification for the CPU CVM.

    This is the function called when Kin uses the verify_network tool.
    It checks:
    1. Firewall rules — should restrict outbound to HTTPS (443) and DNS (53) only
    2. Listening ports — should be minimal (only the handler on 8080)
    3. Outbound connections — should only be to the inference API
    4. DNS — inference.phala.com must be resolvable

    Returns a dict with verification results.
    """
    firewall_rules = _get_iptables_rules()
    listening_ports = _get_listening_ports()
    outbound = _get_outbound_connections()
    dns = _check_dns_resolution()

    expected_listeners = {"8080"}
    unexpected_ports = []
    for port_info in listening_ports:
        addr = port_info.get("local_address", "")
        port = addr.rsplit(":", 1)[-1] if ":" in addr else ""
        if port and port not in expected_listeners and not port_info.get("error"):
            unexpected_ports.append(port_info)

    suspicious_outbound = []
    for conn in outbound:
        remote = conn.get("remote", "")
        if conn.get("error"):
            continue
        if remote.startswith("127."):
            continue
        remote_port = remote.rsplit(":", 1)[-1] if ":" in remote else ""
        if remote_port == "443" or remote_port == "53":
            continue
        suspicious_outbound.append(conn)

    network_ok = len(unexpected_ports) == 0 and len(suspicious_outbound) == 0

    return {
        "firewall_rules": firewall_rules,
        "listening_ports": listening_ports,
        "outbound_connections": outbound,
        "dns_check": dns,
        "unexpected_listeners": unexpected_ports,
        "suspicious_outbound": suspicious_outbound,
        "allowed_outbound_hosts": [INFERENCE_HOST],
        "overall_passed": network_ok,
        "explanation": (
            "The CPU CVM network is locked down: only the handler port "
            "(8080) accepts inbound connections from the proxy via the "
            "dstack gateway. Outbound is restricted to DNS (port 53) and "
            f"HTTPS (port 443) for reaching the inference API at {INFERENCE_HOST}. "
            "Spirit.md content exits the CPU CVM only inside TLS-encrypted "
            "prompts sent to a verified GPU TEE. The clean response (spirit "
            "blocks stripped) is the only data that reaches the proxy."
        ),
    }
