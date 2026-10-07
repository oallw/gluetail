# Troubleshooting and implementation notes

## Tailscale inside gluetun needs two workarounds

Both are included; do not remove them.

1. `gluetun/post-rules.txt`: gluetun's firewall drops forwarded traffic by default, so tailnet traffic is silently
   dropped unless forwarding between `tailscale0` and `tun0` is allowed. Gluetun loads this file at startup and
   after VPN restarts.
2. An `ip rule` sending `100.64.0.0/10` to Tailscale's routing table (added by the Tailscale container's start
   command). Gluetun sends all unmarked traffic into the VPN, so replies to tailnet clients would otherwise leave
   through the tunnel. Symptom without it: connections hang and TCP SYN-ACKs repeat.

## Do not set `TS_DEBUG_FIREWALL_MODE=nftables`

On a Tailscale container that shares gluetun's namespace it looks like a fix for the dropped forwarding, but
Tailscale's nft rules cannot be parsed by gluetun's `iptables-save`. Gluetun then can never restart its VPN
(country changes, health restarts) and stays `crashed`.

## Latency

Behind a VPN with no forwarded port, Tailscale cannot establish direct connections and relays traffic (DERP).
Choose a VPN server close to you (`SERVER_COUNTRIES`); both the nearest relay and the exit server matter. Check
the path with `docker exec <tailscale container> tailscale ping <device>`.

## Gluetun's public-IP lookup (known issue)

Gluetun's own lookup (`/v1/publicip/ip`) can stop returning an address after an in-place VPN restart
(log: `all fetchers failed`) while the tunnel itself works. Rate limiting and the Tailscale container were ruled
out; the cause is not identified. A fresh container start works again until the next restart. When the lookup is
down before a change, `gluetail set` and the web UI apply it, wait for `running`, and report the exit location as
unverified instead of rolling back.

## Gluetun control API

It listens on port 8000 and is reachable, without credentials, by anything on the `gluetail` network or attached
to a node. `gluetun/auth.toml` limits it to the routes gluetail needs. Never allow `GET /v1/vpn/settings`: its
response includes your WireGuard private key.

## Platform

Linux with Docker and Compose v2 only. The CLI talks to containers on their bridge addresses, which Docker
Desktop on macOS and Windows does not expose.
