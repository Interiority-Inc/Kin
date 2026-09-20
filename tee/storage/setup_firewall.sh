#!/usr/bin/env bash
#
# CPU CVM Firewall Configuration
#
# Restricts network egress from the CPU CVM. Outbound is limited to
# DNS (port 53) and HTTPS (port 443) — needed for the Phala Confidential
# Inference API. All other outbound traffic is blocked.
#
# Defense-in-depth: spirit.md content exits the CVM only inside
# TLS-encrypted prompts sent to a verified GPU TEE. The response
# handler strips [SPIRIT] blocks before anything reaches the proxy.

set -euo pipefail

log() { echo "[kin-firewall] $(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

HANDLER_PORT="${KIN_HANDLER_PORT:-8080}"
INFERENCE_HOST="${KIN_INFERENCE_HOST:-inference.phala.com}"

log "Configuring CPU CVM firewall..."

if ! iptables -L -n >/dev/null 2>&1; then
    log "WARNING: iptables not available (missing NET_ADMIN capability?)"
    log "Firewall skipped — TEE encryption is the primary privacy guarantee"
    exit 0
fi

iptables -F 2>/dev/null || true
iptables -X 2>/dev/null || true

iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT DROP

iptables -A INPUT -i lo -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

iptables -A INPUT -p tcp --dport "$HANDLER_PORT" -j ACCEPT

iptables -A OUTPUT -p udp --dport 53 -j ACCEPT
iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT

iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT

log "Firewall configured:"
log "  INPUT:   ACCEPT on port $HANDLER_PORT and loopback; DROP all else"
log "  OUTPUT:  ACCEPT on loopback, established, DNS (53), and HTTPS (443); DROP all else"
log "  FORWARD: DROP all"
log "  Inference API: $INFERENCE_HOST (via HTTPS)"

iptables -L -n -v 2>/dev/null | while read -r line; do
    log "  $line"
done

log "Network egress restricted"
