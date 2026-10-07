# Web UI

A small mobile-friendly page on top of the same logic as the CLI: one card per node with its state and exit
location, and controls generated from the provider's filters (countries and cities with server counts, toggles,
free/paid aware). Plain HTML and vanilla JavaScript served by `./gluetail serve` (Python standard library,
no build step).

Enable it by adding `ui` to `COMPOSE_PROFILES` in `.env` and running `./gluetail up`. It listens on
`127.0.0.1:8421` by default (`GLUETAIL_UI_BIND`).

## Access

- **Tailscale (recommended):** on the host, `tailscale serve --bg --https=8443 http://127.0.0.1:8421`. That gives
  `https://<host>.<tailnet>.ts.net:8443` inside the tailnet (use a port other than 443 if something else on the
  host already listens there). It needs HTTPS certificates enabled for the tailnet, and the UI must stay on
  `127.0.0.1`. Serve passes the caller's identity to the page:
  - `GLUETAIL_UI_USERS=you@example.com` allows only those Tailscale logins (the footer shows who is signed in);
  - `GLUETAIL_UI_HOSTS=<host>.<tailnet>.ts.net` serves only requests addressed to that name (plus localhost),
    which blocks DNS-rebinding pages.
- **Reverse proxy** (Caddy, Traefik, ...): proxy to the published port and put your own authentication in front.

The container runs as uid/gid 1000 by default so it can edit `nodes/*.env`. If your user differs, set
`GLUETAIL_UID` and `GLUETAIL_GID` in `.env`, otherwise saving a choice fails.

## Security model

Anyone who can reach the page can change your VPN settings, so do not expose it to the internet without
authentication. `GLUETAIL_UI_USERS` trusts the `Tailscale-User-Login` header that `tailscale serve` sets; do not
publish the port to a network where untrusted clients can reach it directly, since they could send that header
themselves.

What the container can touch is limited: no Docker socket, gluetun's control API only over the private
`gluetail` network, write access to `nodes/*.env` only, and read-only access to each node's gluetun directory
(server list), never Tailscale state or credentials. A strict Content-Security-Policy is set and all data is
inserted into the page as text. The page uses a bundled copy of
[JetBrains Mono](https://www.jetbrains.com/lp/mono/) (SIL Open Font License 1.1, `web/fonts/OFL.txt`) and needs
nothing from the internet.
