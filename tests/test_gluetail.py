import importlib.machinery, importlib.util, os, tempfile, unittest
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
    "NetworkSettings": {"Networks": {"gluetail": {"IPAddress": "172.29.0.3"}}},
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
        self.assertEqual((n.name, n.state, n.ip), ("proton", "running", "172.29.0.3"))
        self.assertEqual((n.provider, n.free_only), ("protonvpn", True))
        self.assertEqual(n.working_dir, "/opt/gluetail")
        self.assertEqual(n.servers_json, "/var/lib/gluetail/proton/gluetun/servers.json")

    def test_secrets_are_not_retained(self):
        self.assertNotIn("SUPERSECRET", repr(g.parse_node(INSPECT)))

    def test_not_on_network_has_no_ip(self):
        i = dict(INSPECT, NetworkSettings={"Networks": {}})
        self.assertIsNone(g.parse_node(i).ip)


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
        return {"status": "running"} if path.endswith("status") else {"public_ip": "9.9.9.9", "country": "Japan", "city": "Tokyo"}

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

    def test_flag_with_no_servers_explains_why(self):
        with self.assertRaises(g.GluetailError) as cm:
            g.set_filters(self.NODE, ["secure_core_only=on"])
        self.assertIn("no servers on your plan", str(cm.exception))
        self.assertEqual(self.puts(), [])

    def test_clear_filter_writes_empty_value(self):
        self.current["cities"] = ["Tokyo"]
        g.set_filters(self.NODE, ["cities="])
        self.assertEqual(self.writes, [("SERVER_CITIES", "")])


if __name__ == "__main__":
    unittest.main()
