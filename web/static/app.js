// Shared client helpers: auth token storage, fetch wrapper, status bar, verdict cells.
const CC = {
  tokenKey: "codecoach_token",
  getToken() { return localStorage.getItem(this.tokenKey) || ""; },
  setToken(t) { localStorage.setItem(this.tokenKey, t); },
  clearToken() { localStorage.removeItem(this.tokenKey); },

  async api(path, { method = "GET", body = null } = {}) {
    const headers = { "Content-Type": "application/json" };
    const tok = this.getToken();
    if (tok) headers["Authorization"] = "Bearer " + tok;
    const res = await fetch(path, {
      method, headers, body: body ? JSON.stringify(body) : null,
    });
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || ("HTTP " + res.status);
      throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
  },

  esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  },

  // map a verdict status -> css class bucket
  vclass(status) {
    if (status === "OK") return "ok";
    if (status === "TLE" || status === "MLE" || status === "OLE") return "warn";
    return "fail"; // WA / RE / CE / IE
  },

  verdictStrip(outcomes) {
    if (!outcomes || !outcomes.length) return '<div class="muted small">No tests run.</div>';
    const cells = outcomes.map((o, i) => {
      const cls = this.vclass(o.status);
      const hid = o.hidden ? " hidden-tc" : "";
      const tip = `${this.esc(o.name)} — ${o.status} · ${o.runtime_ms}ms`;
      return `<div class="vcell ${cls}${hid}"><span class="code">${o.status}</span>` +
             `<span class="idx">#${i + 1}</span><span class="tip">${tip}</span></div>`;
    }).join("");
    return `<div class="verdict-strip">${cells}</div>`;
  },

  badge(status) {
    return `<span class="badge ${this.vclass(status)}">${status}</span>`;
  },

  pct(x) { return (x == null) ? "—" : (Math.round(x * 1000) / 10) + "%"; },
  fx(x, d = 3) { return (x == null || x === "") ? "—" : Number(x).toFixed(d); },

  async loadStatusBar(elId) {
    const el = document.getElementById(elId);
    if (!el) return;
    try {
      const s = await this.api("/api/system");
      const sb = s.sandbox;
      const net = sb.network_isolation;
      const priv = sb.privilege_drop;
      const aiOn = s.ai.available;
      const langs = (s.languages || []).filter(l => l.available).map(l => l.key).join(" ");
      el.innerHTML =
        `<span class="brand">code<b>coach</b></span>` +
        seg("sandbox", `${sb.platform}${sb.running_as_root ? " · root" : ""}`) +
        segDot("net-isolation", net ? "on" : "off", net ? "on" : "off") +
        segDot("priv-drop", priv ? "on" : "off", priv ? "on" : "off") +
        seg("rlimits", sb.resource_limits ? "on" : "off") +
        seg("langs", langs || "none") +
        `<span class="spacer"></span>` +
        segDot("ai", aiOn ? "llm:" + s.ai.hint_model : "heuristic (offline)", aiOn ? "on" : "warn");
    } catch (e) {
      el.innerHTML = `<span class="brand">code<b>coach</b></span><span class="seg">offline</span>`;
    }
    function seg(k, v) {
      return `<span class="seg"><span class="k">${k}</span><span class="v">${CC.esc(v)}</span></span>`;
    }
    function segDot(k, v, state) {
      return `<span class="seg"><span class="dot ${state}"></span><span class="k">${k}</span><span class="v">${CC.esc(v)}</span></span>`;
    }
  },

  requireToken(redirect = "/") {
    if (!this.getToken()) { window.location.href = redirect; return false; }
    return true;
  },
};

// allow Tab key to insert a tab in code textareas
document.addEventListener("keydown", function (e) {
  if (e.key === "Tab" && e.target.classList && e.target.classList.contains("code")) {
    e.preventDefault();
    const t = e.target;
    const s = t.selectionStart, en = t.selectionEnd;
    t.value = t.value.slice(0, s) + "    " + t.value.slice(en);
    t.selectionStart = t.selectionEnd = s + 4;
  }
});
