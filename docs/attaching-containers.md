# Attaching containers to a VPN node

Any container that should leave through a node's VPN can share its network namespace, exactly like the
Tailscale sidecar does:

```yaml
services:
  my-service:
    image: example/app
    network_mode: "container:gluetail-gluetun-<node>"
```

- **Publish ports on the node.** A container in another container's namespace cannot publish ports itself. List
  them in `nodes/<node>.env`, e.g. `GLUETAIL_PORTS=8081:8080`, and run `./gluetail up`.
- **Shared `localhost`.** Containers in the namespace share `localhost` and see only the node's network, not your
  other Docker networks. A container outside it that needs one of them uses the published host port, for example
  `extra_hosts: ["host.docker.internal:host-gateway"]` plus `http://host.docker.internal:8081`.
- **Start order.** Start gluetail first; `depends_on` cannot cross Compose projects. Under systemd, make the other
  stack's unit `Requires=` and `After=` the gluetail unit (see `systemd/gluetail.service`).
- **Recreating a node strands its dependents.** They keep a reference to the old, now gone, namespace until they
  are recreated too. `./gluetail dependents <node>` lists them, and `./gluetail up` recreates them whenever it
  replaces a node. It finds them, and how to recreate them, from their own Compose labels, so no configuration is
  needed (`--no-dependents` skips this). If a node is recreated some other way, recreate the dependents by hand.
- **Do not publish gluetun's control port (8000) beyond loopback.** The default access role can change the VPN
  settings. gluetail refuses such a mapping; if a dashboard needs the public IP, bind it to loopback:
  `GLUETAIL_PORTS=127.0.0.1:9800:8000`.
