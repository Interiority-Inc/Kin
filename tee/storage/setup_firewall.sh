#!/usr/bin/env bash
#
# TEE Firewall Configuration
#
# Locks down network egress so spirit.md content cannot be exfiltrated.
# Only the response handler port (8080) accepts inbound connections,
# and vLLM listens on localhost only.
#
# This is defense-in-depth: even if the response parser has a bug,
# the network configuration prevents spirit.md from leaving the TEE.

set -euo pipefail

log() { echo "[kin-firewall] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

HANDLER_PORT="${KIN_HANDLER_PORT:-8080}"
VLLM_PORT="${KIN_VLLM_PORT:-8000}"

log "Configuring TEE firewall..."

# Flush existing rules
iptables -F 2>/dev/null || true
iptables -X 2>/dev/null || true

# Default policies: drop everything
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

# Allow loopback (needed for handler <-> vLLM communication)
iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Allow established/related connections (responses to inbound requests)
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow inbound to the handler port (from proxy)
iptables -A INPUT -p tcp --dport "$HANDLER_PORT" -j ACCEPT

# Block ALL other outbound traffic
# spirit.md content has no network path out of the TEE
# The only way data exits is through the handler's response,
# which strips [SPIRIT] blocks before sending

log "Firewall configured:"
log "  INPUT:   ACCEPT on port $HANDLER_PORT and loopback; DROP all else"
log "  OUTPUT:  ACCEPT on loopback and established; DROP all else"
log "  FORWARD: DROP all"
log "  vLLM:    localhost:$VLLM_PORT (loopback only)"

iptables -L -n -v 2>/dev/null | while read -r line; do
    log "  $line"
done

log "Network egress locked down"
