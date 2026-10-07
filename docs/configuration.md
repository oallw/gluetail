# Configuration

## Install-level settings: `.env`

Copy `.env.example` to `.env`. Nothing in it is secret.

| Key | Meaning |
|---|---|
| `COMPOSE_PROFILES` | nodes to run, comma-separated node names, plus `ui` for the web UI |
| `GLUETAIL_DATA_DIR` | where node state is kept (must persist across `compose down`) |
| `GLUETAIL_TS_ENV` | file containing `TS_AUTHKEY=...` |
| `TAILSCALE_TAG`, `GLUETUN_IMAGE` | image versions (see *Versions*) |
| `GLUETAIL_UI_BIND`, `GLUETAIL_UI_USERS`, `GLUETAIL_UI_HOSTS`, `GLUETAIL_UID`, `GLUETAIL_GID` | web UI, see [web-ui.md](web-ui.md) |
| `TZ` | timezone for gluetun logs |

## Nodes: `nodes/<name>.env`

One file per exit node. The name is also the Compose profile. Files in `nodes/` ending in `.env.example` are
templates; real node files are not committed.

| Key | Meaning |
|---|---|
| `GLUETAIL_TYPE` | `vpn` (default) or `direct` (no VPN) |
| `GLUETAIL_HOSTNAME` | name in the tailnet (default `exit-<name>`) |
| `GLUETAIL_SECRETS` | credentials file for a VPN node (default `./secrets/<name>.env`) |
| `GLUETAIL_TS_ARGS` | extra `tailscale up` flags |
| `GLUETAIL_PORTS` | ports published on a VPN node, `[bind-ip:]host:container[/udp]`, see [attaching-containers.md](attaching-containers.md) |
| anything else | passed to gluetun unchanged |

Because everything else goes to gluetun as-is, any option your provider supports works:
`VPN_SERVICE_PROVIDER`, `SERVER_COUNTRIES`, `FREE_ONLY`, ... See the
[gluetun provider docs](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers).

Credentials stay out of node files. A VPN node's `GLUETAIL_SECRETS` file holds only what the provider needs
(for WireGuard: `WIREGUARD_PRIVATE_KEY`, and `WIREGUARD_ADDRESSES` for some providers).

`./gluetail up` re-renders `docker-compose.yml` (generated, not committed) and applies it. Changing only
gluetun options such as `SERVER_COUNTRIES` does not need a re-render; `./gluetail set` changes them live.

## Versions

Images are pinned to what the project was tested with: Tailscale by tag, gluetun by digest (the comment in
`templates/header.yml` explains why), the web UI image by minor version. To update, change the value in
`.env`, run `docker compose pull && ./gluetail up`, then check that a country switch still works.

## Running under systemd

`restart: unless-stopped` already restarts the containers with Docker. To manage the stack as a unit, use
`systemd/gluetail.service`: copy it, set `WorkingDirectory`, then `systemctl enable --now gluetail`.
