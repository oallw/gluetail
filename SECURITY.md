# Security

gluetail controls VPN settings, so please report problems privately rather than in a public issue:
use GitHub's "Report a vulnerability" (private vulnerability reporting) on this repository.

Useful to know when assessing a report: the web UI has no accounts of its own. It trusts the
`Tailscale-User-Login` header set by `tailscale serve` and the `GLUETAIL_UI_HOSTS` allowlist, and it must not
be exposed to untrusted networks directly (see the README). The gluetun control API is deliberately
reachable without credentials from anything attached to the same Docker network or namespace.
