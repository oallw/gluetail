# CLI

`./gluetail` is a single Python 3 file with no dependencies. It needs the `docker` CLI and finds VPN nodes
through a label on their gluetun container. A node can be given by its name or its tailnet name.

```
./gluetail up                    render docker-compose.yml, docker compose up -d, recreate attached containers
./gluetail nodes                 configured nodes: tailnet name, provider, countries, state
./gluetail status                state, exit IP and location of each VPN node
./gluetail options [node]        filters the node's provider supports and what each can still be set to
./gluetail set <node> key=value  change filters live, e.g. countries=Japan cities=Tokyo
./gluetail set-country <node> <country>...
./gluetail countries [node]      the country list
./gluetail dependents [node]     containers attached to the node's network namespace
./gluetail render                only generate docker-compose.yml
./gluetail serve                 run the web UI (normally via the `ui` profile)
```

`up` flags: `--dry-run`, `--force-recreate`, `--no-dependents`. `set` flag: `--no-persist` to try a change
without saving it. `key=` (empty) clears a filter.

## Filters

`options` is generated from gluetun's own server list for the node's provider, so it follows gluetun
updates and works for any provider:

- multi-selects for country, city, region and ISP, with the number of matching servers;
- toggles for any server attribute that is a flag (for Proton, for example, secure core and port forwarding;
  for Mullvad, owned servers);
- with `FREE_ONLY=on`, only free servers are offered and toggles with no free servers are marked unavailable.

Geography is one-way: choosing a city never narrows the country list, and choosing a country drops any
selected city that does not exist there.

## Applying changes

A change is applied through gluetun's control API; the VPN restarts and clients on that node reconnect after a
few seconds. The choice is saved to `nodes/<name>.env`, so recreating the containers keeps it.

- A combination no server matches is refused before anything is sent. Otherwise gluetun tears the tunnel
  down and retries with growing delays.
- If the VPN does not come back, the previous selection is restored.
- If gluetun's public-IP lookup was already failing before the change, the change is applied and reported
  as unverified instead of rolled back (see [troubleshooting.md](troubleshooting.md)).

Tests: `python3 -m unittest discover -s tests`.
