# Tailscale setup

One-time configuration in the [Tailscale admin console](https://login.tailscale.com/admin).

## Tailnet settings

- **MagicDNS**: enabled.
- **HTTPS certificates** (DNS settings): enabled, only needed if you serve the web UI with
  `tailscale serve` (see [web-ui.md](web-ui.md)).

## Auth key

Settings → Keys → *Generate auth key*:

| Option | Value | Why |
|---|---|---|
| Reusable | on | nodes can be recreated with the same key |
| Ephemeral | off | ephemeral nodes disappear when they go offline |
| Pre-approved | on, if your tailnet requires device approval | |
| Tags | optional | see *Auto-approval* below |

Put the key in `secrets/tailscale.env` as `TS_AUTHKEY=...`. It is only used the first time a node starts.
Auth keys expire (90 days at most); that does not affect nodes that are already registered.

## After the first start

Each node shows up under *Machines* (named by `GLUETAIL_HOSTNAME`, default `exit-<node>`).

1. **Disable key expiry** for the machine (⋯ → *Disable key expiry*). Node keys expire after 180 days
   by default, which would silently take the exit node offline.
2. **Approve it as an exit node** (⋯ → *Edit route settings* → *Use as exit node*), unless you use
   auto-approval.

A node's identity lives in `GLUETAIL_DATA_DIR`. Keep and back up that directory: deleting it creates
brand-new nodes that need approving again.

## Auto-approval (optional)

Tag the nodes and let the ACL approve tagged exit nodes (replace the tag with your own):

```json
"tagOwners":     { "tag:exit-node": ["autogroup:admin"] },
"autoApprovers": { "exitNode": ["tag:exit-node"] }
```

Generate the auth key with that tag and add `GLUETAIL_TS_ARGS=--advertise-tags=tag:exit-node` to each node file.

## Verify

On a device in the tailnet, choose the node as exit node (Tailscale app, or
`tailscale set --exit-node=<name>`) and open https://ifconfig.me. It should show the public IP of the
node's egress: the server's own IP for a direct node, the provider's IP for a VPN node. Clear the exit
node and the address should change back. Test from a different network than the server's; on the same
LAN a direct node shows no difference.
