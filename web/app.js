"use strict";

// Minimal, dependency-free UI. Everything shown is built from the server's generated
// schema (/api/nodes/<n>/options), so new providers or filters need no changes here.
// All data goes through textContent / setAttribute, never innerHTML.

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const lower = (s) => String(s).toLowerCase();
const sameValue = (a, b) => lower(a) === lower(b);
const normalized = (sel) => JSON.stringify(Object.keys(sel).sort().map(
  (k) => [k, Array.isArray(sel[k]) ? sel[k].map(lower).sort() : sel[k]]));

function initialSelection(opts) {
  const sel = {};
  for (const f of opts.facets) {
    if (f.kind === "multi") {
      sel[f.key] = f.selected.map((v) => (f.options.find((o) => sameValue(o.value, v)) || { value: v }).value);
    } else {
      sel[f.key] = !!f.selected;
    }
  }
  return sel;
}

function vpnCard(info) {
  const card = h("section", { class: "card" });
  const state = { opts: null, sel: {}, saved: {}, open: new Set(), busy: false, message: null };
  let previewSeq = 0;

  async function load() {
    state.opts = await api(`/api/nodes/${encodeURIComponent(info.node)}/options`);
    state.sel = initialSelection(state.opts);
    state.saved = JSON.parse(JSON.stringify(state.sel));
    render();
  }

  async function preview() {
    const seq = ++previewSeq;
    try {
      const opts = await api(`/api/nodes/${encodeURIComponent(info.node)}/preview`, { selection: state.sel });
      if (seq !== previewSeq) return;
      state.opts = opts;
      state.sel = initialSelection(opts);  // the server may have dropped choices that no longer fit
      const dropped = Object.entries(opts.pruned || {});
      if (dropped.length) {
        const label = (key) => (opts.facets.find((f) => f.key === key) || {}).label || key;
        state.message = { text: "Removed " + dropped.map(([k, v]) => `${label(k)} ${v.join(", ")}`).join("; ") +
          " (not available with your other choices)." };
      } else if (state.message && !state.message.bad) {
        state.message = null;
      }
      render();
    } catch (e) { state.message = { bad: true, text: e.message }; render(); }
  }

  async function apply() {
    state.busy = true;
    state.message = { text: "Applying… the VPN restarts, this can take up to a minute." };
    render();
    try {
      const res = await api(`/api/nodes/${encodeURIComponent(info.node)}/set`, { selection: state.sel });
      state.message = { ok: true, text: res.unchanged ? "Already set that way." :
        `Now exiting via ${res.city || "?"}, ${res.country || "?"}.` };
      Object.assign(info, await statusFor(info.node));
      await load();
    } catch (e) {
      state.message = { bad: true, text: e.message };
      await load().catch(() => {});
    }
    state.busy = false;
    render();
  }

  function multiFacet(f) {
    const values = new Map(f.options.map((o) => [o.value, o.count]));
    for (const v of state.sel[f.key]) {
      if (![...values.keys()].some((k) => sameValue(k, v))) values.set(v, 0);  // selected but now unavailable
    }
    const chosen = state.sel[f.key];
    const box = h("details", { ontoggle: (ev) => (ev.target.open ? state.open.add(f.key) : state.open.delete(f.key)) },
      h("summary", {}, f.label, " ", h("span", { class: "muted" }, chosen.length ? chosen.join(", ") : "any")),
      h("div", { class: "opts" }, [...values].map(([value, count]) => {
        const checked = chosen.some((c) => sameValue(c, value));
        return h("label", { class: count ? "" : "gone" },
          h("input", { type: "checkbox", checked, disabled: state.busy, onchange: (ev) => {
            const rest = state.sel[f.key].filter((c) => !sameValue(c, value));
            state.sel[f.key] = ev.target.checked ? [...rest, value] : rest;
            preview();
          } }), value, count ? h("span", { class: "muted" }, `(${count})`) : "");
      })));
    if (state.open.has(f.key)) box.setAttribute("open", "");
    return box;
  }

  function boolFacet(f) {
    const on = !!state.sel[f.key];
    const locked = !!f.disabled_reason && !on;
    return h("div", { class: "toggle" }, h("label", {},
      h("input", { type: "checkbox", checked: on, disabled: locked || state.busy, onchange: (ev) => {
        state.sel[f.key] = ev.target.checked; preview();
      } }), f.label, " ",
      h("small", {}, f.disabled_reason ? `(${f.disabled_reason})` : `(${f.count} servers)`)));
  }

  function render() {
    const o = state.opts;
    const changed = o && normalized(state.sel) !== normalized(state.saved);
    const where = [info.city, info.country].filter(Boolean).join(", ");
    card.replaceChildren(
      h("div", { class: "row" },
        h("h2", {}, info.hostname || info.node),
        h("span", { class: "badge" }, `${info.provider}${o ? " · " + o.plan + " plan" : ""}`)),
      h("p", { class: "status" },
        h("span", { class: "state " + (info.vpn === "running" ? "ok" : "bad") }, info.vpn || "unreachable"),
        info.public_ip ? ` · ${info.public_ip}` : "", where ? ` · ${where}` : "",
        info.error ? h("span", { class: "bad" }, ` ${info.error}`) : ""),
      ...(o ? o.facets.map((f) => (f.kind === "multi" ? multiFacet(f) : boolFacet(f))) : [h("p", { class: "muted" }, "Loading options…")]),
      o && o.unsupported.length ? h("p", { class: "muted" }, `No control yet for: ${o.unsupported.join(", ")}`) : "",
      h("div", { class: "actions" },
        h("button", { type: "button", disabled: !changed || state.busy || !o || o.match_count === 0, onclick: apply },
          o ? `apply · ${o.match_count} server${o.match_count === 1 ? "" : "s"}` : "apply"),
        h("button", { type: "button", class: "secondary", disabled: !changed || state.busy, onclick: () => {
          state.sel = JSON.parse(JSON.stringify(state.saved)); preview();
        } }, "reset")),
      h("p", { class: "msg " + (state.message && (state.message.bad ? "bad" : state.message.ok ? "ok" : "muted")) },
        o && o.match_count === 0 ? "No server matches this combination." : (state.message ? state.message.text : "")));
  }

  load().catch((e) => { state.message = { bad: true, text: e.message }; render(); });
  render();
  return card;
}

function directCard(info) {
  return h("section", { class: "card" },
    h("div", { class: "row" }, h("h2", {}, info.hostname || info.node), h("span", { class: "badge" }, "no VPN")),
    h("p", { class: "muted" }, "Exits through this server's own connection. Nothing to configure."));
}

async function statusFor(node) {
  const rows = await api("/api/nodes");
  return rows.find((r) => r.node === node) || {};
}

async function main() {
  const root = document.getElementById("nodes");
  try {
    const [rows, me] = await Promise.all([api("/api/nodes"), api("/api/me")]);
    document.getElementById("me").textContent = me.user ? `Signed in as ${me.user}` : "";
    root.replaceChildren(...rows.map((r) => (r.type === "vpn" ? vpnCard(r) : directCard(r))));
    if (!rows.length) root.replaceChildren(h("p", { class: "muted" }, "No nodes configured."));
  } catch (e) {
    root.replaceChildren(h("p", { class: "bad" }, e.message));
  }
}

document.getElementById("refresh").addEventListener("click", main);
main();
