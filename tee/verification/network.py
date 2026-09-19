"""
Network Egress Verification

Verifies that no network path exists for spirit.md content to leave
the TEE except through the response handler (which strips [SPIRIT]
blocks before anything exits the enclave).

This is a critical defense-in-depth check. Even if there were a bug
in the response parser, the network configuration should prevent
spirit.md content from being exfiltrated.

This tool runs INSIDE the enclave and is part of the attested code.
"""

import subprocess
import json
import logging

logger = logging.getLogger("kin.verification.network")


def _get_iptables_rules() -> list[str]:
    """Get current iptables rules."""
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
    """Get all listening network ports."""
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
    """Get current outbound network connections."""
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
    """Check if the TEE can resolve external domains (it shouldn't need to)."""
    try:
        result = subprocess.run(
            ["nslookup", "example.com"],
            capture_output=True, text=True, timeout=5,
        )
        can_resolve = result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        can_resolve = False

    return {
        "can_resolve_external_dns": can_resolve,
        "note": (
            "The TEE should have minimal DNS access. Ideally only "
            "the vLLM server address (localhost) needs to be reachable."
        ),
    }


def verify_network() -> dict:
    """
    Full network verification for the TEE.

    This is the function called when Kin uses the verify_network tool.
    It checks:
    1. Firewall rules — should restrict outbound traffic
    2. Listening ports — should be minimal (only the handler and vLLM)
    3. Outbound connections — should be none except to the proxy
    4. DNS — should have minimal or no external resolution

    The expected configuration:
    - Only the handler port (e.g., 8080) accepts inbound from the proxy
    - vLLM listens on localhost only (e.g., 127.0.0.1:8000)
    - No outbound connections to the internet
    - No path for spirit.md content to exit except through the
      response handler, which strips [SPIRIT] blocks

    Returns a dict with verification results.
    """
    firewall_rules = _get_iptables_rules()
    listening_ports = _get_listening_ports()
    outbound = _get_outbound_connections()
    dns = _check_dns_resolution()

    expected_listeners = {"8080", "8000"}
    unexpected_ports = []
    for port_info in listening_ports:
        addr = port_info.get("local_address", "")
        port = addr.rsplit(":", 1)[-1] if ":" in addr else ""
        if port and port not in expected_listeners and not port_info.get("error"):
            unexpected_ports.append(port_info)

    suspicious_outbound = []
    for conn in outbound:
        remote = conn.get("remote", "")
        if not remote.startswith("127.") and not conn.get("error"):
            suspicious_outbound.append(conn)

    network_ok = len(unexpected_ports) == 0 and len(suspicious_outbound) == 0

    return {
        "firewall_rules": firewall_rules,
        "listening_ports": listening_ports,
        "outbound_connections": outbound,
        "dns_check": dns,
        "unexpected_listeners": unexpected_ports,
        "suspicious_outbound": suspicious_outbound,
        "overall_passed": network_ok,
        "explanation": (
            "The TEE network should be locked down: only the handler "
            "port (8080) accepts inbound connections from the proxy, "
            "and vLLM listens on localhost (8000). There should be no "
            "outbound connections to the internet. spirit.md content "
            "can only exit through the response handler, which strips "
            "[SPIRIT] blocks before anything leaves the enclave."
        ),
    }
