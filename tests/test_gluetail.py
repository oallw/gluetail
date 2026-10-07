import importlib.machinery, importlib.util, json, os, tempfile, threading, unittest
from unittest import mock

_path = os.path.join(os.path.dirname(__file__), "..", "gluetail")
_loader = importlib.machinery.SourceFileLoader("gluetail_cli", _path)
_spec = importlib.util.spec_from_loader("gluetail_cli", _loader)
g = importlib.util.module_from_spec(_spec)
_loader.exec_module(g)

INSPECT = {
    "Name": "/gluetail-gluetun-proton",
    "State": {"Status": "running"},
    "Config": {
        "Labels": {
            "gluetail.node": "proton",
            "com.docker.compose.project.working_dir": "/opt/gluetail",
        },
        "Env": [
            "VPN_SERVICE_PROVIDER=protonvpn",
            "FREE_ONLY=on",
            "WIREGUARD_PRIVATE_KEY=SUPERSECRETKEY",
        ],
    },
    "NetworkSettings": {"Networks": {"gluetail": {"IPAddress": "172.18.0.3"}}},
    "Mounts": [{"Destination": "/gluetun", "Source": "/var/lib/gluetail/proton/gluetun"}],
}

SERVERS = {
    "protonvpn": {"servers": [
        {"country": "Netherlands", "vpn": "wireguard", "free": True},
        {"country": "Netherlands", "vpn": "wireguard"},
        {"country": "Switzerland", "vpn": "wireguard", "free": True},
        {"country": "Germany", "vpn": "wireguard"},
        {"country": "Japan", "vpn": "openvpn", "free": True},
    ]}
}


class ParseNode(unittest.TestCase):
    def test_fields(self):
        n = g.parse_node(INSPECT)
        self.assertEqual((n.name, n.state, n.host), ("proton", "running", "172.18.0.3"))
        self.assertEqual((n.provider, n.free_only), ("protonvpn", True))
        self.assertEqual(n.working_dir, "/opt/gluetail")
        self.assertEqual(n.servers_json, "/var/lib/gluetail/proton/gluetun/servers.json")

    def test_secrets_are_not_retained(self):
        self.assertNotIn("SUPERSECRET", repr(g.parse_node(INSPECT)))

    def test_not_on_network_has_no_ip(self):
        i = dict(INSPECT, NetworkSettings={"Networks": {}})
        self.assertIsNone(g.parse_node(i).host)


class DecodeBody(unittest.TestCase):
    def test_json(self):
        self.assertEqual(g.decode_body(b'{"status":"running"}'), {"status": "running"})

    def test_plain_text(self):
        self.assertEqual(g.decode_body(b"running\n"), "running")

    def test_empty(self):
        self.assertEqual(g.decode_body(b""), "")


class Countries(unittest.TestCase):
    def test_free_only_wireguard(self):
        self.assertEqual(g.list_countries(SERVERS, "protonvpn", True), ["Netherlands", "Switzerland"])

    def test_all_wireguard(self):
        self.assertEqual(g.list_countries(SERVERS, "protonvpn", False), ["Germany", "Netherlands", "Switzerland"])

    def test_unknown_provider(self):
        with self.assertRaises(g.GluetailError):
            g.list_countries(SERVERS, "nope", False)

    def test_resolve_case_insensitive(self):
        self.assertEqual(g.resolve_countries(["switzerland", "NETHERLANDS"], ["Netherlands", "Switzerland"]),
                         ["Switzerland", "Netherlands"])

    def test_resolve_suggests_close_match(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.resolve_countries(["Switzerlnd"], ["Netherlands", "Switzerland"])
        self.assertIn("Switzerland", str(cm.exception))


class EnvFile(unittest.TestCase):
    def _write(self, text):
        f = tempfile.NamedTemporaryFile("w", delete=False)
        f.write(text); f.close()
        self.addCleanup(lambda: os.path.exists(f.name) and os.unlink(f.name))
        return f.name

    def _read(self, path):
        with open(path) as f:
            return f.read()

    def test_replaces_existing_and_keeps_rest(self):
        p = self._write("# c\nA=1\nPROTON_COUNTRIES=Netherlands\nB=2\n")
        g.update_env_file(p, "PROTON_COUNTRIES", "Japan,Norway")
        self.assertEqual(self._read(p), "# c\nA=1\nPROTON_COUNTRIES=Japan,Norway\nB=2\n")

    def test_appends_when_missing(self):
        p = self._write("A=1")
        g.update_env_file(p, "PROTON_COUNTRIES", "Japan")
        self.assertEqual(self._read(p), "A=1\nPROTON_COUNTRIES=Japan\n")

    def test_creates_missing_file(self):
        p = self._write("")
        os.unlink(p)
        g.update_env_file(p, "K", "v")
        self.assertEqual(self._read(p), "K=v\n")

    def test_rejects_newlines(self):
        p = self._write("A=1\n")
        with self.assertRaises(g.GluetailError):
            g.update_env_file(p, "K", "x\nEVIL=1")


TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "templates")


class ParseEnvText(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(g.parse_env_text("# c\nA=1\n\nB = 'two words'\nC=\"x\"\n"),
                         {"A": "1", "B": "two words", "C": "x"})

    def test_rejects_garbage(self):
        with self.assertRaises(g.GluetailError):
            g.parse_env_text("not a pair")

    def test_inline_comments_match_compose_semantics(self):
        got = g.parse_env_text("A=1   # note\nB=\"x # kept\"\nC=http://h/#frag\nD=   # only a comment\nE=a#b\n")
        self.assertEqual(got, {"A": "1", "B": "x # kept", "C": "http://h/#frag", "D": "", "E": "a#b"})


class Render(unittest.TestCase):
    VPN = {"GLUETAIL_SECRETS": "/s/p.env", "VPN_SERVICE_PROVIDER": "protonvpn", "SERVER_COUNTRIES": "Japan"}

    def test_vpn_and_direct(self):
        out = g.render_compose({"proton": dict(self.VPN, GLUETAIL_HOSTNAME="exit-p"), "plain": {"GLUETAIL_TYPE": "direct"}},
                               TEMPLATES)
        for expected in ("gluetun-proton:", "ts-proton:", "ts-plain:", "gluetail.node=proton",
                         'network_mode: "service:gluetun-proton"', "TS_HOSTNAME=exit-p", "TS_HOSTNAME=exit-plain",
                         '- "/s/p.env"', "- nodes/proton.env"):
            self.assertIn(expected, out)
        self.assertNotIn("@@", out)
        self.assertNotIn("gluetun-plain", out)
        self.assertIn("gluetail-ui", out)
        ui = out.split("\n  ui:\n")[1]  # the UI never gets Tailscale state (node private keys)
        self.assertIn("/proton/gluetun:/data/proton/gluetun:ro", ui)
        self.assertNotIn("tailscale", ui.replace("tailnet", ""))
        self.assertNotIn("/plain", ui)

    def test_no_ui_without_vpn_nodes(self):
        self.assertNotIn("gluetail-ui", g.render_compose({"plain": {"GLUETAIL_TYPE": "direct"}}, TEMPLATES))

    def test_defaults_secrets_path(self):
        out = g.render_compose({"mv": {"VPN_SERVICE_PROVIDER": "mullvad"}}, TEMPLATES)
        self.assertIn('- "./secrets/mv.env"', out)

    def test_rejects_bad_values(self):
        bad = [
            {"VPN_SERVICE_PROVIDER": "x", "GLUETAIL_HOSTNAME": "a\nb"},
            {"VPN_SERVICE_PROVIDER": "x", "GLUETAIL_SECRETS": "/a/$(evil)"},
            {"VPN_SERVICE_PROVIDER": "x", "GLUETAIL_TS_ARGS": "--x; rm -rf /"},
            {"GLUETAIL_TYPE": "other"},
            {},  # vpn node without provider
        ]
        for cfg in bad:
            with self.subTest(cfg=cfg), self.assertRaises(g.GluetailError):
                g.render_compose({"n": cfg}, TEMPLATES)

    def test_ports_are_published_on_the_vpn_container(self):
        cfg = dict(self.VPN, GLUETAIL_PORTS="9080:8080, 127.0.0.1:9800:8000, 5000:5000/udp")
        out = g.render_compose({"p": cfg}, TEMPLATES)
        block = out.split("  gluetun-p:\n")[1].split("\n\n")[0]
        self.assertIn('    ports:\n      - "9080:8080"\n      - "127.0.0.1:9800:8000"\n      - "5000:5000/udp"\n', block)
        self.assertNotIn("@@", out)
        self.assertNotIn("ports:", g.render_compose({"p": self.VPN}, TEMPLATES).split("  ui:")[0])

    def test_bad_ports_are_rejected(self):
        for bad in ("9080", "80:80:80:80", "0:80", "99999:80", "80:8080; rm -rf /", "a:b", "1.2.3:80:80"):
            with self.subTest(bad=bad), self.assertRaises(g.GluetailError):
                g.render_compose({"p": dict(self.VPN, GLUETAIL_PORTS=bad)}, TEMPLATES)

    def test_ports_on_a_direct_node_are_rejected(self):
        with self.assertRaises(g.GluetailError):
            g.render_compose({"d": {"GLUETAIL_TYPE": "direct", "GLUETAIL_PORTS": "80:80"}}, TEMPLATES)

    def test_shipped_example_files_render(self):
        """The quick start copies nodes/*.env.example; every one of them must parse and render."""
        nodes_dir = os.path.join(os.path.dirname(__file__), "..", "nodes")
        examples = sorted(f for f in os.listdir(nodes_dir) if f.endswith(".env.example"))
        self.assertTrue(examples)
        for f in examples:
            with self.subTest(example=f), open(os.path.join(nodes_dir, f)) as fh:
                cfg = g.parse_env_text(fh.read())
                out = g.render_compose({f[:-len(".env.example")]: cfg}, TEMPLATES)
                self.assertNotIn("#", cfg.get("GLUETAIL_HOSTNAME", ""))
                self.assertNotIn("#", cfg.get("GLUETAIL_SECRETS", ""))
                self.assertIn("ts-" + f[:-len(".env.example")], out)

    def test_control_api_port_may_only_be_published_on_loopback(self):
        out = g.render_compose({"p": dict(self.VPN, GLUETAIL_PORTS="127.0.0.1:9800:8000")}, TEMPLATES)
        self.assertIn('"127.0.0.1:9800:8000"', out)
        for bad in ("9800:8000", "0.0.0.0:9800:8000", "192.0.2.9:9800:8000", "8000:8000/tcp"):
            with self.subTest(bad=bad), self.assertRaises(g.GluetailError) as cm:
                g.render_compose({"p": dict(self.VPN, GLUETAIL_PORTS=bad)}, TEMPLATES)
            self.assertIn("control API", str(cm.exception))

    def test_no_nodes(self):
        with self.assertRaises(g.GluetailError):
            g.render_compose({}, TEMPLATES)

    def test_load_node_files_validates_names(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "Bad_Name.env"), "w") as f:
                f.write("A=1\n")
            with self.assertRaises(g.GluetailError):
                g.load_node_files(d)
            os.unlink(os.path.join(d, "Bad_Name.env"))
            with open(os.path.join(d, "ok-1.env"), "w") as f:
                f.write("A=1\n")
            self.assertEqual(g.load_node_files(d), {"ok-1": {"A": "1"}})


class NodeOverview(unittest.TestCase):
    CFGS = {
        "direct": {"GLUETAIL_TYPE": "direct"},
        "proton": {"VPN_SERVICE_PROVIDER": "protonvpn", "SERVER_COUNTRIES": "Japan", "GLUETAIL_HOSTNAME": "exit-p"},
        "mv": {"VPN_SERVICE_PROVIDER": "mullvad"},
    }

    def test_summarize(self):
        rows = {r["node"]: r for r in g.summarize_nodes(self.CFGS, {"gluetail-ts-proton": "running"})}
        self.assertEqual(rows["direct"], {"node": "direct", "type": "direct", "hostname": "exit-direct",
                                          "provider": "-", "countries": "-", "state": "not created"})
        self.assertEqual(rows["proton"]["state"], "running")
        self.assertEqual((rows["proton"]["hostname"], rows["proton"]["countries"]), ("exit-p", "Japan"))
        self.assertEqual(rows["mv"]["countries"], "any")

    def test_resolve_name_accepts_hostname(self):
        self.assertEqual(g.resolve_name("exit-p", self.CFGS), "proton")
        self.assertEqual(g.resolve_name("proton", self.CFGS), "proton")
        self.assertEqual(g.resolve_name("exit-direct", self.CFGS), "direct")
        self.assertEqual(g.resolve_name("unknown", self.CFGS), "unknown")

    def test_pick_default_single_vpn_node(self):
        self.assertEqual(g.pick_vpn_node(None, {"direct": {"GLUETAIL_TYPE": "direct"},
                                                "proton": {"VPN_SERVICE_PROVIDER": "protonvpn"}}), "proton")

    def test_pick_default_ambiguous_lists_nodes(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.pick_vpn_node(None, self.CFGS)
        self.assertIn("proton", str(cm.exception))
        self.assertIn("mv", str(cm.exception))

    def test_pick_rejects_direct_node(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.pick_vpn_node("direct", self.CFGS)
        self.assertIn("no VPN", str(cm.exception))

    def test_pick_unknown_lists_nodes(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.pick_vpn_node("nope", self.CFGS)
        self.assertIn("proton", str(cm.exception))


def srv(country, city, **flags):
    return dict({"country": country, "city": city, "vpn": "wireguard", "hostname": f"{city}.x", "ips": ["1.1.1.1"]}, **flags)


SCHEMA_SERVERS = [
    srv("Japan", "Tokyo", free=True),
    srv("United States", "Chicago", free=True),
    srv("United States", "Miami", free=True),
    srv("United States", "Denver"),
    srv("Germany", "Berlin", secure_core=True),
    srv("Germany", "Frankfurt", secure_core=True, multihop=True, weird="a"),
    srv("Sweden", "Stockholm", weird="b"),
]


class Schema(unittest.TestCase):
    def setUp(self):
        self.facets, self.unsupported = g.build_facets(SCHEMA_SERVERS)

    def keys(self):
        return {f["key"]: f["kind"] for f in self.facets}

    def test_facets_are_derived_from_data(self):
        self.assertEqual(self.keys(), {"countries": "multi", "cities": "multi", "free_only": "plan",
                                       "secure_core_only": "bool", "multi_hop_only": "bool"})
        env = {f["key"]: f["env"] for f in self.facets}
        self.assertEqual((env["secure_core_only"], env["multi_hop_only"]), ("SECURE_CORE_ONLY", "MULTI_HOP_ONLY"))

    def test_unrecognised_attribute_is_reported_not_dropped(self):
        self.assertEqual(self.unsupported, ["weird"])

    def opts(self, selection, free):
        return g.compute_options(SCHEMA_SERVERS, self.facets, self.unsupported, selection, free)

    def facet(self, opts, key):
        return next(f for f in opts["facets"] if f["key"] == key)

    def test_free_plan_hides_paid_servers_and_disables_flags(self):
        o = self.opts({}, True)
        self.assertEqual(o["match_count"], 3)
        self.assertEqual([x["value"] for x in self.facet(o, "countries")["options"]], ["Japan", "United States"])
        self.assertEqual(self.facet(o, "secure_core_only")["count"], 0)
        self.assertIn("plan", self.facet(o, "secure_core_only")["disabled_reason"])

    def test_all_plan_shows_everything(self):
        o = self.opts({}, False)
        self.assertEqual(o["match_count"], 7)
        self.assertEqual(self.facet(o, "secure_core_only")["count"], 2)
        self.assertNotIn("disabled_reason", self.facet(o, "secure_core_only"))

    def test_cities_cascade_from_country_but_countries_stay_selectable(self):
        o = self.opts({"countries": ["united states"]}, False)
        self.assertEqual([x["value"] for x in self.facet(o, "cities")["options"]], ["Chicago", "Denver", "Miami"])
        self.assertEqual(len(self.facet(o, "countries")["options"]), 4)  # own facet is not self-filtered

    def test_city_does_not_narrow_countries(self):
        o = self.opts({"countries": ["united states"], "cities": ["chicago"]}, False)
        self.assertEqual(len(self.facet(o, "countries")["options"]), 4)
        self.assertEqual([x["value"] for x in self.facet(o, "cities")["options"]], ["Chicago", "Denver", "Miami"])

    def test_orthogonal_filters_still_narrow_countries(self):
        o = self.opts({"secure_core_only": True}, False)
        self.assertEqual([x["value"] for x in self.facet(o, "countries")["options"]], ["Germany"])

    def test_prune_drops_cities_of_other_countries(self):
        sel, removed = g.prune_selection(SCHEMA_SERVERS, self.facets, self.unsupported,
                                         {"countries": ["Japan"], "cities": ["Chicago", "Tokyo"]}, False)
        self.assertEqual((sel["cities"], removed), (["Tokyo"], {"cities": ["Chicago"]}))

    def test_prune_leaves_valid_selection_alone(self):
        sel, removed = g.prune_selection(SCHEMA_SERVERS, self.facets, self.unsupported,
                                         {"countries": ["Germany"], "cities": ["berlin"], "secure_core_only": True}, False)
        self.assertEqual((sel["cities"], removed), (["berlin"], {}))

    def test_impossible_selection_has_zero_matches(self):
        self.assertEqual(self.opts({"countries": ["japan"], "cities": ["chicago"]}, False)["match_count"], 0)

    def test_selection_from_env(self):
        sel = g.selection_from_env({"SERVER_COUNTRIES": "Japan, Norway", "SECURE_CORE_ONLY": "on", "FREE_ONLY": "on"},
                                   self.facets)
        self.assertEqual(sel["countries"], ["Japan", "Norway"])
        self.assertEqual((sel["secure_core_only"], sel["multi_hop_only"], sel["cities"]), (True, False, []))
        self.assertNotIn("free_only", sel)

    def test_parse_changes(self):
        o = self.opts({}, False)
        self.assertEqual(g.parse_changes(["country=germany", "secure_core_only=on", "cities="], self.facets, o),
                         {"countries": ["Germany"], "secure_core_only": True, "cities": []})

    def test_parse_changes_rejects_unknown_key_and_value(self):
        o = self.opts({}, False)
        with self.assertRaises(g.GluetailError):
            g.parse_changes(["bogus=1"], self.facets, o)
        with self.assertRaises(g.GluetailError):
            g.parse_changes(["countries=Atlantis"], self.facets, o)


class SetFilters(unittest.TestCase):
    NODE = g.Node("p", "c", "running", "10.0.0.2", "prov", False, "/w", "/w/servers.json")

    def setUp(self):
        self.facets, self.unsupported = g.build_facets(SCHEMA_SERVERS)
        self.current = {"countries": ["Japan"], "cities": [], "secure_core_only": False, "multi_hop_only": False}
        self.calls, self.writes = [], []
        self.put_reply = "running"
        self.lookup_works = True  # whether gluetun's public-IP lookup returns an address
        patches = [
            mock.patch.object(g, "node_view", lambda n: (SCHEMA_SERVERS, self.facets, self.unsupported,
                                                         dict(self.current), True)),
            mock.patch.object(g, "api", self.fake_api),
            mock.patch.object(g, "update_env_file", lambda path, k, v: self.writes.append((k, v))),
            mock.patch.object(g, "node_file", lambda n: "/w/nodes/p.env"),
            mock.patch.object(g.time, "sleep", lambda s: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_api(self, node, method, path, body=None, timeout=5):
        self.calls.append((method, path, body))
        if method == "PUT":
            return self.put_reply
        if path.endswith("status"):
            return {"status": "running"}
        if not self.lookup_works:
            return {"public_ip": ""}
        return {"public_ip": "9.9.9.9", "country": "Japan", "city": "Tokyo"}

    def puts(self):
        return [c[2] for c in self.calls if c[0] == "PUT"]

    def test_success_applies_and_persists(self):
        res = g.set_filters(self.NODE, ["countries=United States", "cities=Chicago"])
        self.assertEqual(self.puts(), [{"provider": {"server_selection":
                                                      {"countries": ["United States"], "cities": ["Chicago"]}}}])
        self.assertEqual(self.writes, [("SERVER_COUNTRIES", "United States"), ("SERVER_CITIES", "Chicago")])
        self.assertEqual(res["public_ip"], "9.9.9.9")

    def test_impossible_combination_is_refused_before_touching_the_vpn(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.set_filters(self.NODE, ["cities=Chicago"])  # current country is Japan
        self.assertIn("no free-plan server", str(cm.exception))
        self.assertEqual(self.puts(), [])
        self.assertEqual(self.writes, [])

    def test_crash_rolls_back_and_does_not_persist(self):
        self.put_reply = "crashed"
        with self.assertRaises(g.GluetailError) as cm:
            g.set_filters(self.NODE, ["countries=United States"])
        self.assertEqual(self.puts()[0], {"provider": {"server_selection": {"countries": ["United States"]}}})
        self.assertEqual(self.puts()[1], {"provider": {"server_selection": {"countries": ["Japan"]}}})
        self.assertIn("rolled back", str(cm.exception))
        self.assertEqual(self.writes, [])

    def test_unchanged_reply_is_reported(self):
        self.put_reply = "settings left unchanged"
        self.assertTrue(g.set_filters(self.NODE, ["countries=Japan"])["unchanged"])
        self.assertEqual(self.writes, [])

    def test_lookup_down_before_and_after_is_applied_unverified_without_rollback(self):
        self.lookup_works = False
        res = g.set_filters(self.NODE, ["countries=United States", "cities=Chicago"])
        self.assertEqual(len(self.puts()), 1)  # no rollback
        self.assertFalse(res["verified"])
        self.assertEqual(self.writes, [("SERVER_COUNTRIES", "United States"), ("SERVER_CITIES", "Chicago")])

    def test_lookup_that_breaks_only_after_the_change_is_rolled_back(self):
        outer = self.fake_api
        state = {"puts": 0}

        def flaky(node, method, path, body=None, timeout=5):
            if method == "PUT":
                state["puts"] += 1
                self.lookup_works = state["puts"] > 1  # works again only after the rollback PUT
            return outer(node, method, path, body, timeout)

        with mock.patch.object(g, "api", flaky), self.assertRaises(g.GluetailError) as cm:
            g.set_filters(self.NODE, ["countries=United States"], timeout=4)
        self.assertEqual(state["puts"], 2)
        self.assertIn("rolled back", str(cm.exception))
        self.assertEqual(self.writes, [])

    def test_verified_result_flag(self):
        self.assertTrue(g.set_filters(self.NODE, ["countries=United States"])["verified"])

    def test_flag_with_no_servers_explains_why(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.set_filters(self.NODE, ["secure_core_only=on"])
        self.assertIn("no servers on your plan", str(cm.exception))
        self.assertEqual(self.puts(), [])

    def test_only_changed_values_are_persisted(self):
        g.set_filters(self.NODE, ["countries=japan", "secure_core_only=off", "cities=", "multi_hop_only=off"])
        self.assertEqual(self.writes, [])  # everything equals the saved selection (case-insensitively)

    def test_clear_filter_writes_empty_value(self):
        self.current["cities"] = ["Tokyo"]
        g.set_filters(self.NODE, ["cities="])
        self.assertEqual(self.writes, [("SERVER_CITIES", "")])


class WebApp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        os.makedirs(os.path.join(root, "nodes"))
        os.makedirs(os.path.join(root, "web"))
        os.makedirs(os.path.join(root, "web", "fonts"))
        for name, content in (("index.html", "<html>ui</html>"), ("app.js", "//js"), ("style.css", "/*c*/")):
            with open(os.path.join(root, "web", name), "w") as f:
                f.write(content)
        with open(os.path.join(root, "web", "fonts", "jetbrains-mono-400.woff2"), "wb") as f:
            f.write(b"wOF2fake")
        with open(os.path.join(root, "nodes", "p.env"), "w") as f:
            f.write("VPN_SERVICE_PROVIDER=prov\nFREE_ONLY=on\n")
        with open(os.path.join(root, "nodes", "d.env"), "w") as f:
            f.write("GLUETAIL_TYPE=direct\n")
        self.app = g.App(root, os.path.join(root, "data"))
        self.facets, self.unsupported = g.build_facets(SCHEMA_SERVERS)
        view = (SCHEMA_SERVERS, self.facets, self.unsupported, {"countries": ["Japan"], "cities": []}, True)
        for p in (mock.patch.object(g, "node_view", lambda n: view),
                  mock.patch.object(g, "node_status", lambda n: {"node": n.name, "vpn": "running",
                                                                  "public_ip": "9.9.9.9", "country": "Japan"})):
            p.start(); self.addCleanup(p.stop)

    def req(self, method, path, body=None, headers=None, ctype="application/json"):
        h = dict(headers or {})
        if body is not None:
            h["Content-Type"] = ctype
        status, hdrs, payload = self.app.handle(method, path, h, json.dumps(body).encode() if body is not None else b"")
        return status, hdrs, payload

    def test_static_files_and_security_headers(self):
        status, hdrs, body = self.req("GET", "/")
        self.assertEqual((status, body), (200, b"<html>ui</html>"))
        self.assertIn("default-src 'self'", hdrs["Content-Security-Policy"])
        self.assertEqual(self.req("GET", "/static/app.js")[0], 200)
        status, hdrs, body = self.req("GET", "/static/fonts/jetbrains-mono-400.woff2")
        self.assertEqual((status, hdrs["Content-Type"], body), (200, "font/woff2", b"wOF2fake"))
        self.assertIn("max-age", hdrs["Cache-Control"])
        self.assertEqual(self.req("GET", "/static/app.js")[1]["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(self.req("GET", "/static/../gluetail")[0], 404)  # only whitelisted files
        self.assertEqual(self.req("GET", "/static/fonts/../../gluetail")[0], 404)
        self.assertEqual(self.req("GET", "/static/fonts/OFL.txt")[0], 404)
        self.assertEqual(self.req("GET", "/static/secret.txt")[0], 404)

    def test_list_nodes_includes_direct_and_vpn(self):
        status, _, body = self.req("GET", "/api/nodes")
        rows = {r["node"]: r for r in json.loads(body)}
        self.assertEqual(status, 200)
        self.assertEqual(rows["p"]["vpn"], "running")
        self.assertEqual(rows["p"]["plan"], "free")
        self.assertEqual(rows["d"]["type"], "direct")
        self.assertNotIn("state", rows["d"])

    def test_preview_applies_selection_without_touching_the_vpn(self):
        with mock.patch.object(g, "api", side_effect=AssertionError("preview must not call gluetun")):
            status, _, body = self.req("POST", "/api/nodes/p/preview", {"selection": {"countries": ["United States"]}})
        opts = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual({o["value"] for o in next(f for f in opts["facets"] if f["key"] == "cities")["options"]},
                         {"Chicago", "Miami"})

    def test_preview_prunes_conflicting_city_and_reports_it(self):
        _, _, body = self.req("POST", "/api/nodes/p/preview",
                              {"selection": {"countries": ["Japan"], "cities": ["Chicago"]}})
        opts = json.loads(body)
        self.assertEqual(opts["pruned"], {"cities": ["Chicago"]})
        self.assertEqual(next(f for f in opts["facets"] if f["key"] == "cities")["selected"], [])
        self.assertEqual(opts["match_count"], 1)

    def test_preview_ignores_unknown_keys(self):
        status, _, body = self.req("POST", "/api/nodes/p/preview", {"selection": {"__proto__": ["x"], "bogus": True}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["match_count"], 3)

    def test_post_requires_json_content_type(self):
        self.assertEqual(self.req("POST", "/api/nodes/p/preview", {"selection": {}}, ctype="text/plain")[0], 415)

    def test_unknown_or_direct_node_is_a_clean_error(self):
        for name in ("nope", "d"):
            status, _, body = self.req("POST", f"/api/nodes/{name}/preview", {"selection": {}})
            self.assertEqual(status, 400)
            self.assertIn("unknown VPN node", json.loads(body)["error"])

    def test_bad_json_and_bad_body(self):
        status, _, _ = self.app.handle("POST", "/api/nodes/p/set", {"Content-Type": "application/json"}, b"{nope")
        self.assertEqual(status, 400)
        self.assertEqual(self.req("POST", "/api/nodes/p/set", {"selection": "x"})[0], 400)

    def test_set_converts_selection_and_reports_errors(self):
        with mock.patch.object(g, "set_filters", return_value={"node": "p", "unchanged": False}) as sf:
            status, _, _ = self.req("POST", "/api/nodes/p/set", {"selection": {"countries": ["Japan"], "secure_core_only": False}})
        self.assertEqual(status, 200)
        self.assertEqual(sf.call_args[0][1], ["countries=Japan", "secure_core_only=off"])
        with mock.patch.object(g, "set_filters", side_effect=g.GluetailError("no server matches")):
            status, _, body = self.req("POST", "/api/nodes/p/set", {"selection": {"countries": ["Japan"]}})
        self.assertEqual((status, json.loads(body)["error"]), (400, "no server matches"))

    def test_concurrent_change_is_rejected(self):
        self.app._locks["p"] = threading.Lock()
        self.app._locks["p"].acquire()
        status, _, body = self.req("POST", "/api/nodes/p/set", {"selection": {"countries": ["Japan"]}})
        self.assertEqual(status, 409)
        self.assertIn("busy", json.loads(body)["error"])

    def test_internal_errors_do_not_leak_details(self):
        with mock.patch.object(g, "list_nodes_marker", create=True), \
             mock.patch.object(g.App, "list_nodes", side_effect=RuntimeError("secret path /private/x")):
            status, _, body = self.req("GET", "/api/nodes")
        self.assertEqual(status, 500)
        self.assertNotIn("secret", body.decode())

    def test_host_allowlist_blocks_rebinding_but_keeps_loopback(self):
        app = g.App(self.app.root, self.app.data_dir, None, ["ui.example.ts.net"])
        ok = [{"Host": "ui.example.ts.net"}, {"Host": "UI.example.ts.net:8443"}, {"Host": "127.0.0.1:8421"},
              {"Host": "localhost"}, {"Host": "[::1]:8421"}]
        for headers in ok:
            with self.subTest(headers=headers):
                self.assertEqual(app.handle("GET", "/api/me", headers)[0], 200)
        for host in ("evil.example.com", "evil.example.com:8421", "ui.example.ts.net.evil.com", "", "10.0.0.5:8421"):
            with self.subTest(host=host):
                self.assertEqual(app.handle("GET", "/api/me", {"Host": host})[0], 403)
        self.assertEqual(app.handle("GET", "/api/me", {})[0], 403)  # no Host at all

    def test_host_check_is_off_when_not_configured(self):
        self.assertEqual(self.app.handle("GET", "/api/me", {"Host": "anything.example"})[0], 200)

    def test_json_list_body_is_a_400_not_a_500(self):
        status, _, _ = self.app.handle("POST", "/api/nodes/p/preview", {"Content-Type": "application/json"}, b"[1]")
        self.assertEqual(status, 400)

    def test_allowlist(self):
        app = g.App(self.app.root, self.app.data_dir, ["me@example.com"])
        self.assertEqual(app.handle("GET", "/api/me", {})[0], 403)
        self.assertEqual(app.handle("GET", "/api/me", {"Tailscale-User-Login": "other@example.com"})[0], 403)
        status, _, body = app.handle("GET", "/api/me", {"tailscale-user-login": "ME@example.com"})
        self.assertEqual((status, json.loads(body)["user"]), (200, "ME@example.com"))


class OpenAccessWarning(unittest.TestCase):
    def test_quiet_when_loopback_or_restricted(self):
        self.assertIsNone(g.open_access_warning([], "127.0.0.1:8421"))
        self.assertIsNone(g.open_access_warning([], "localhost:8421"))
        self.assertIsNone(g.open_access_warning([], "[::1]:8421"))
        self.assertIsNone(g.open_access_warning(["me@x"], "0.0.0.0:8421"))

    def test_warns_when_published_wide_without_allowlist(self):
        for addr in ("0.0.0.0:8421", "100.64.0.7:8421", "192.0.2.5:80", "0.0.0.0"):
            with self.subTest(addr=addr):
                self.assertIn(addr, g.open_access_warning([], addr))


class RealServer(unittest.TestCase):
    """End-to-end over a real socket: HEAD must mirror GET, minus the body."""

    def test_head_matches_get_without_body(self):
        import http.client
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "web")); os.makedirs(os.path.join(root, "nodes"))
            with open(os.path.join(root, "web", "index.html"), "w") as f:
                f.write("<html>hi</html>")
            httpd = g.ThreadingHTTPServer(("127.0.0.1", 0), g.make_handler(g.App(root, root)))
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            self.addCleanup(httpd.server_close); self.addCleanup(httpd.shutdown)
            seen = {}
            for method in ("GET", "HEAD"):
                c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
                c.request(method, "/")
                r = c.getresponse()
                seen[method] = (r.status, r.getheader("Content-Length"), r.getheader("Content-Security-Policy"), r.read())
                c.close()
            self.assertEqual(seen["GET"][:3], seen["HEAD"][:3])
            self.assertEqual((seen["GET"][3], seen["HEAD"][3]), (b"<html>hi</html>", b""))


class Dependents(unittest.TestCase):
    NODE_ID = "ab" * 32

    @staticmethod
    def c(name, mode, state="running", service="svc"):
        return {"Name": "/" + name, "State": {"Status": state}, "HostConfig": {"NetworkMode": mode},
                "Config": {"Labels": {"com.docker.compose.project": "stack", "com.docker.compose.service": service}}}

    def test_finds_by_id_and_name_ignores_others(self):
        found = g.find_dependents([
            self.c("app-b", "container:" + self.NODE_ID, service="app-b"),
            self.c("app-a", "container:gluetail-gluetun-p", state="exited"),
            self.c("short-id", "container:" + self.NODE_ID[:12]),
            self.c("other-node", "container:" + "cd" * 32),
            self.c("bridge", "bridge"),
            self.c("service-mode", "service:gluetun"),
        ], "gluetail-gluetun-p", self.NODE_ID)
        self.assertEqual([d["container"] for d in found], ["app-a", "app-b", "short-id"])
        self.assertEqual(found[1]["project"], "stack")

    def test_short_unrelated_target_does_not_match(self):
        self.assertEqual(g.find_dependents([self.c("x", "container:ab")], "n", self.NODE_ID), [])


class RequestLimits(unittest.TestCase):
    """Malformed requests must be refused cheaply, before any body is read or auth is evaluated."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "web")); os.makedirs(os.path.join(tmp.name, "nodes"))
        self.httpd = g.ThreadingHTTPServer(("127.0.0.1", 0), g.make_handler(g.App(tmp.name, tmp.name)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close); self.addCleanup(self.httpd.shutdown)

    def raw(self, request, timeout=5):
        import socket
        s = socket.create_connection(("127.0.0.1", self.httpd.server_address[1]), timeout=timeout)
        self.addCleanup(s.close)
        s.sendall(request)
        return s.recv(4096).decode(errors="replace")

    def test_negative_non_numeric_and_huge_content_length(self):
        for value, expected in (("-1", "400"), ("abc", "400"), ("99999999", "413")):
            with self.subTest(value=value):
                reply = self.raw(f"POST /api/nodes/p/set HTTP/1.1\r\nHost: x\r\nContent-Length: {value}\r\n\r\n".encode())
                self.assertIn(f" {expected} ", reply.split("\r\n")[0] + " ")

    def test_handler_has_a_socket_timeout(self):
        self.assertTrue(0 < g.make_handler(g.App("/x", "/x")).timeout <= 60)


def dep(container, project="stack", service="svc", wd="/opt/stack", files="/opt/stack/compose.yml", managed=True):
    labels = {"com.docker.compose.project": project, "com.docker.compose.service": service,
              "com.docker.compose.project.working_dir": wd, "com.docker.compose.project.config_files": files} if managed else {}
    return {"container": container, "state": "running", "project": project, "service": service, "labels": labels}


class Up(unittest.TestCase):
    def test_plan_only_for_replaced_nodes(self):
        before = {"p": {"id": "A", "project": "gt", "deps": [dep("a"), dep("b")]},
                  "q": {"id": "C", "project": "gt", "deps": [dep("c")]},
                  "r": {"id": None, "project": None, "deps": []}}
        after = {"p": {"id": "B"}, "q": {"id": "C"}, "r": {"id": "D"}}
        self.assertEqual([(n, d["container"]) for n, d in g.plan_recreations(before, after)], [("p", "a"), ("p", "b")])
        self.assertEqual(g.plan_recreations(before, {"p": {"id": "A"}, "q": {"id": "C"}, "r": {"id": None}}), [])

    def test_commands_are_grouped_per_compose_project(self):
        steps = [("p", dep("app-a", service="app-a")), ("p", dep("app-b", service="app-b")),
                 ("p", dep("other", project="other", service="x", wd="/opt/o", files="/opt/o/a.yml,/opt/o/b.yml"))]
        commands, unmanaged = g.recreate_commands(steps)
        self.assertEqual(unmanaged, [])
        self.assertEqual(commands[0][0], ["docker", "compose", "--project-directory", "/opt/stack", "-p", "stack",
                                          "-f", "/opt/stack/compose.yml", "up", "-d", "--force-recreate", "--no-deps",
                                          "app-a", "app-b"])
        self.assertEqual(commands[1][0], ["docker", "compose", "--project-directory", "/opt/o", "-p", "other",
                                          "-f", "/opt/o/a.yml", "-f", "/opt/o/b.yml",
                                          "up", "-d", "--force-recreate", "--no-deps", "x"])
        self.assertEqual([names for _, names in commands], [["app-a", "app-b"], ["other"]])

    def test_containers_without_compose_labels_are_reported(self):
        commands, unmanaged = g.recreate_commands([("p", dep("manual", managed=False))])
        self.assertEqual((commands, unmanaged), ([], ["manual"]))

    # -- orchestration with the docker side mocked
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "nodes"))
        with open(os.path.join(self.tmp.name, "nodes", "p.env"), "w") as f:
            f.write("VPN_SERVICE_PROVIDER=prov\n")
        os.makedirs(os.path.join(self.tmp.name, "templates"))
        for name in ("header.yml", "vpn.yml", "ui.yml", "direct.yml"):
            with open(os.path.join(TEMPLATES, name)) as src, open(os.path.join(self.tmp.name, "templates", name), "w") as dst:
                dst.write(src.read())
        self.runs = []
        self.snaps = []
        self.rc = {}
        patches = [mock.patch.object(g, "snapshot_nodes", lambda names: self.snaps.pop(0)),
                   mock.patch.object(g.subprocess, "run", self.fake_run)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.args = g.argparse.Namespace(root=self.tmp.name, force_recreate=False, no_dependents=False, dry_run=False)

    def fake_run(self, argv, **kw):
        self.runs.append(argv)
        return mock.Mock(returncode=self.rc.get(argv[-1] if argv[2] != "--project-directory" else "recreate", 0))

    def test_replaced_node_triggers_recreation_after_compose_up(self):
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("app-a", service="app-a")]}}, {"p": {"id": "B"}}]
        self.assertEqual(g.cmd_up(self.args), 0)
        self.assertEqual(self.runs[0][:5], ["docker", "compose", "up", "-d", "--remove-orphans"])
        self.assertIn("--force-recreate", self.runs[1])
        self.assertEqual(self.runs[1][-1], "app-a")
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "docker-compose.yml")))

    def test_unchanged_node_recreates_nothing(self):
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("app-a")]}}, {"p": {"id": "A"}}]
        self.assertEqual(g.cmd_up(self.args), 0)
        self.assertEqual(len(self.runs), 1)

    def test_compose_failure_leaves_dependents_alone(self):
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("app-a")]}}]
        self.rc["--remove-orphans"] = 3
        self.assertEqual(g.cmd_up(self.args), 3)
        self.assertEqual(len(self.runs), 1)

    def test_no_dependents_flag(self):
        self.args.no_dependents = True
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("app-a")]}}]
        self.assertEqual(g.cmd_up(self.args), 0)
        self.assertEqual(len(self.runs), 1)

    def test_force_recreate_flag_is_passed_to_compose(self):
        self.args.force_recreate = True
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": []}}, {"p": {"id": "A"}}]
        g.cmd_up(self.args)
        self.assertIn("--force-recreate", self.runs[0])

    def test_dry_run_changes_nothing(self):
        self.args.dry_run = True
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("app-a")]}}]
        self.assertEqual(g.cmd_up(self.args), 0)
        self.assertEqual(self.runs, [])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "docker-compose.yml")))

    def test_unmanaged_dependent_makes_the_command_report_failure(self):
        self.snaps = [{"p": {"id": "A", "project": "gt", "deps": [dep("manual", managed=False)]}}, {"p": {"id": "B"}}]
        self.assertEqual(g.cmd_up(self.args), 1)


class SelectionItems(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(g.selection_to_items({"countries": ["A", "B"], "secure_core_only": True, "cities": []}),
                         ["countries=A,B", "secure_core_only=on", "cities="])

    def test_rejects_other_types(self):
        with self.assertRaises(g.GluetailError):
            g.selection_to_items({"countries": "Japan"})


if __name__ == "__main__":
    unittest.main()
