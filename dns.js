/* Optional DNS section of the FTrap dashboard.
   Reads data/dns_top.json and data/dns_live.json (format: docs/dns_contract.md), written by the companion
   capture collector. The section (#dns) stays hidden until one of the files loads successfully.
   Self-contained: own texts (DE/EN), follows <html lang> / <html data-lang>. All data goes into the DOM via
   textContent / createElementNS only (never innerHTML). */
(function () {
  "use strict";
  var TOP_MS = 60000, LIVE_MS = 5000, RETRY_MS = 300000, STALE_S = 180, DEMO_STEP = 600;
  var SVG_NS = "http://www.w3.org/2000/svg";
  var OTHER = "(other)";                      /* catch-all domain of the collector, see contract */
  var TXT = {
    de: { dns_title: "DNS-Auswertung", p_today: "Heute", p_7d: "7 Tage", p_30d: "30 Tage",
      h_series: "Abfragen der letzten 24 Stunden", n_series: "Abfragen pro Stunde, lokale Zeit",
      h_clients: "Geräte-Aktivität 24 Stunden", n_clients: "Abfragen je Gerät und Stunde, gemeinsame Skala",
      h_clients_top: "Geräte-Aktivität – {x} verursacht {y} % der Abfragen",
      series_head: "{x} Abfragen, {y} blockiert – Spitze {z}",
      h_share: "Abfragetypen und Antwortstatus", h_qtypes: "Abfragetypen", h_status: "Antwortstatus",
      n_qtypes: "Anteil je Abfragetyp", n_status: "Anteil je Antwortstatus",
      h_tables: "Top-Listen", l_permitted: "Top erlaubte Domains", l_blocked: "Top blockierte Domains",
      l_clients_all: "Top-Geräte (gesamt)", l_clients_blocked: "Top-Geräte (nur blockiert)",
      log_title: "Abfrageprotokoll", search_ph: "Domain / Gerät suchen",
      pause: "Anhalten", resume: "Fortsetzen", f_all: "Alle Status", rows_n: "{x} Zeilen",
      a_period: "Zeitraum", a_status: "Status", a_rows: "Anzahl der Zeilen",
      c_time: "Zeit", c_type: "Typ", c_domain: "Domain", c_device: "Gerät", c_status: "Status",
      c_reply: "Antwort", c_ms: "Dauer (ms)", c_hits: "Treffer", c_freq: "Häufigkeit",
      stale: "Mitschnitt-Daten veraltet", since: "Mitschnitt seit {x}", connected: "verbunden",
      disconnected: "getrennt", conn_since: "verbunden seit {x}", reconnects: "Neuverbindungen: {x}",
      err_fmt: "Fehler: {x}",
      no_pkt: "Mitschnitt liefert seit {x} min keine Pakete",
      empty: "Noch keine Daten – sie erscheinen, sobald der Mitschnitt Anfragen liefert",
      t_total: "Abfragen", t_blocked: "Blockiert", t_pct: "Blockiert (%)", t_clients: "Geräte aktiv",
      st_allowed: "Erlaubt", st_blocked: "Blockiert", st_nxdomain: "NXDOMAIN", st_error: "Fehler",
      st_no_answer: "Ohne Antwort", rest: "Rest", other: "Andere", dom_other: "(andere)",
      r_ip: "IP", r_cname: "CNAME", r_nxdomain: "NXDOMAIN", r_blocked: "blockiert", r_nodata: "NODATA",
      r_error: "Fehler", r_none: "–", no_series: "Noch keine Daten",
      peak: "Spitze {x}", hours_range: "{x} Uhr", hour_tick: "{x}", thousands: "{x} Tsd.",
      of_nx: "davon NXDOMAIN", running: "Stunde läuft noch", partial: "Stunde unvollständig",
      col_dev: "Gerät", col_n: "Abfragen 24 h", col_blk: "blockiert", col_trend: "Verlauf (max. {x}/h)",
      share_of: "der Abfragen", queries_l: "Abfragen", blocked_l: "blockiert", at_least: "mind.",
      log_meta: "{x} Einträge · letzte 5 min: {y} Abfragen, {z} blockiert",
      no_qtypes: "Abfragetypen werden erst seit dem Neustart des Mitschnitts gezählt",
      e_auth_failed: "Die Box hat Benutzername oder Kennwort abgelehnt",
      e_login_failed: "Anmeldung an der Box fehlgeschlagen",
      e_credentials_error: "Zugangsdaten fehlen oder sind unsicher gespeichert",
      e_tls_error: "Zertifikatsprüfung fehlgeschlagen",
      e_connect_failed: "Verbindung zur Box fehlgeschlagen",
      e_http_error: "Die Box hat den Mitschnitt abgelehnt (HTTP-Fehler)",
      e_capture_busy: "Mitschnitt leer – läuft an der Box schon ein anderer Mitschnitt?",
      e_stream_truncated: "Datenstrom zu früh beendet",
      e_not_pcap: "Antwort der Box ist kein Mitschnitt",
      e_idle_timeout: "Zeitüberschreitung: keine Daten",
      e_read_error: "Lesefehler im Datenstrom",
      e_pcap_error: "Mitschnitt-Datenstrom nicht synchron",
      e_page_error: "Hilfeseite der Box nicht abrufbar",
      e_internal_error: "Interner Fehler",
      e_capture_failed: "Mitschnitt fehlgeschlagen",
      e_unknown: "Unbekannter Fehler" },
    en: { dns_title: "DNS analysis", p_today: "Today", p_7d: "7 days", p_30d: "30 days",
      h_series: "Queries in the last 24 hours", n_series: "Queries per hour, local time",
      h_clients: "Device activity, 24 hours", n_clients: "Queries per device and hour, shared scale",
      h_clients_top: "Device activity – {x} causes {y} % of queries",
      series_head: "{x} queries, {y} blocked – peak {z}",
      h_share: "Query types and reply status", h_qtypes: "Query types", h_status: "Reply status",
      n_qtypes: "Share per query type", n_status: "Share per reply status",
      h_tables: "Top lists", l_permitted: "Top permitted domains", l_blocked: "Top blocked domains",
      l_clients_all: "Top devices (all)", l_clients_blocked: "Top devices (blocked only)",
      log_title: "Query log", search_ph: "Search domain / device",
      pause: "Pause", resume: "Resume", f_all: "All statuses", rows_n: "{x} rows",
      a_period: "Time range", a_status: "Status", a_rows: "Number of rows",
      c_time: "Time", c_type: "Type", c_domain: "Domain", c_device: "Device", c_status: "Status",
      c_reply: "Reply", c_ms: "Time (ms)", c_hits: "Hits", c_freq: "Frequency",
      stale: "Capture data outdated", since: "Capture since {x}", connected: "connected",
      disconnected: "disconnected", conn_since: "connected since {x}", reconnects: "reconnects: {x}",
      err_fmt: "error: {x}",
      no_pkt: "Capture has delivered no packets for {x} min",
      empty: "No data yet – it appears once the capture delivers queries",
      t_total: "Queries", t_blocked: "Blocked", t_pct: "Blocked (%)", t_clients: "Active devices",
      st_allowed: "Allowed", st_blocked: "Blocked", st_nxdomain: "NXDOMAIN", st_error: "Error",
      st_no_answer: "No answer", rest: "Rest", other: "Other", dom_other: "(other)",
      r_ip: "IP", r_cname: "CNAME", r_nxdomain: "NXDOMAIN", r_blocked: "blocked", r_nodata: "NODATA",
      r_error: "error", r_none: "–", no_series: "No data yet",
      peak: "peak {x}", hours_range: "{x} h", hour_tick: "{x}h", thousands: "{x}k",
      of_nx: "of which NXDOMAIN", running: "hour still running", partial: "partial hour",
      col_dev: "Device", col_n: "Queries 24 h", col_blk: "blocked", col_trend: "Trend (max. {x}/h)",
      share_of: "of queries", queries_l: "queries", blocked_l: "blocked", at_least: "at least",
      log_meta: "{x} entries · last 5 min: {y} queries, {z} blocked",
      no_qtypes: "Query types are only counted since the capture restarted",
      e_auth_failed: "The box rejected the user name or password",
      e_login_failed: "Login to the box failed",
      e_credentials_error: "Credentials are missing or stored insecurely",
      e_tls_error: "Certificate check failed",
      e_connect_failed: "Connection to the box failed",
      e_http_error: "The box refused the capture (HTTP error)",
      e_capture_busy: "Capture stream empty – is another packet capture running on the box?",
      e_stream_truncated: "Stream ended too early",
      e_not_pcap: "The box did not answer with a packet capture",
      e_idle_timeout: "Timeout: no data",
      e_read_error: "Read error in the stream",
      e_pcap_error: "Capture stream out of sync",
      e_page_error: "Helper page of the box not reachable",
      e_internal_error: "Internal error",
      e_capture_failed: "Capture failed",
      e_unknown: "Unknown error" }
  };
  var STATUS = {
    allowed: { icon: "✓", cls: "mut", fill: "allowed" },
    blocked: { icon: "⊘", cls: "blk", fill: "blocked" },
    nxdomain: { icon: "?", cls: "warn", fill: "serious" },
    error: { icon: "!", cls: "err", fill: "critical" },
    no_answer: { icon: "…", cls: "none", fill: "warning" }
  };
  var QTYPE_SLOT = { A: 0, AAAA: 1, HTTPS: 2, PTR: 3, SRV: 4, TXT: 5 };

  function ls(k, v) {
    try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ }
    return null;
  }
  var root = document.documentElement;
  var sec = document.getElementById("dns");
  if (!sec) return;
  var period = ["today", "7d", "30d"].indexOf(ls("ftrap_dns_period")) >= 0 ? ls("ftrap_dns_period") : "today";
  var filter = "all", limit = 100, query = "", paused = false;
  var top = null, live = null, okTop = false, okLive = false, shown = false;

  /* app.js keeps <html lang> current from the start; data-lang only appears after the first toggle. */
  function lang() {
    var l = String(root.lang || root.dataset.lang || "").slice(0, 2).toLowerCase();
    return TXT[l] ? l : "en";
  }
  function loc() { return lang() === "de" ? "de-DE" : "en-GB"; }
  function t(k) { return TXT[lang()][k] || TXT.en[k] || k; }
  function fmt(k, v) {          /* replace {x}, {y}, {z} placeholders (function replacer: no $-patterns in data) */
    return t(k).replace(/\{(\w+)\}/g, function (m, n) { return v && v[n] !== undefined ? String(v[n]) : ""; });
  }
  function $(id) { return document.getElementById(id); }
  function h(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function s(name, attrs, text) {
    var n = document.createElementNS(SVG_NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (text != null) n.textContent = text;
    return n;
  }
  function num(n) { return Math.round(Number(n)).toLocaleString(loc()); }   /* counters are always integers */
  function pct1(x) { return Number(x).toLocaleString(loc(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %"; }
  function isNum(v) { return typeof v === "number" && isFinite(v); }
  function clock(ts) { return new Date(ts * 1000).toLocaleTimeString(loc(), { hour: "2-digit", minute: "2-digit", hour12: false }); }
  function compact(v) { return v >= 10000 ? fmt("thousands", { x: Math.round(v / 1000).toLocaleString(loc()) }) : num(v); }
  function domText(q) { return q === OTHER ? t("dom_other") : q; }
  function errText(code) {      /* known codes only (contract); anything else gets a generic text */
    var k = "e_" + code;
    return typeof code === "string" && /^[a-z_]{1,32}$/.test(code) && Object.prototype.hasOwnProperty.call(TXT.en, k)
      ? t(k) : t("e_unknown");
  }

  /* Precision follows the spread of the column: values above 0 never show as "0". */
  function pctColumn(values) {
    var v = values.filter(isNum), mx = Math.max.apply(null, v.concat([0])), mn = Math.min.apply(null, v.concat([0]));
    var range = mx - mn, dec = range > 0 ? Math.max(0, Math.min(2, 1 - Math.floor(Math.log10(range)))) : 1;
    var floorV = Math.pow(10, -dec);
    return function (x) {
      if (!isNum(x)) return "–";
      if (x > 0 && x < floorV / 2) return "<" + floorV.toLocaleString(loc(), { maximumFractionDigits: dec }) + " %";
      return x.toLocaleString(loc(), { minimumFractionDigits: dec, maximumFractionDigits: dec }) + " %";
    };
  }
  function msColumn(values) {
    var v = values.filter(isNum), range = v.length ? Math.max.apply(null, v) - Math.min.apply(null, v) : 0;
    var dec = range < 10 ? 1 : 0;
    return function (x) { return isNum(x) ? x.toLocaleString(loc(), { minimumFractionDigits: dec, maximumFractionDigits: dec }) : "–"; };
  }

  /* ---- Tooltip: value first, name after, line key ---- */
  var tip = $("tooltip");
  function showTip(title, rows, evt) {
    if (!tip) return;
    tip.replaceChildren();
    var t0 = h("div"); t0.appendChild(h("b", "", title)); tip.appendChild(t0);
    rows.forEach(function (r) {
      var d = h("div", "tk-row");
      d.appendChild(h("span", "tk-key k-" + r.k));
      d.appendChild(h("span", "tk-val", r.val)); d.appendChild(h("span", "tk-name", r.name));
      tip.appendChild(d);
    });
    tip.classList.remove("hidden");
    var pad = 14, r = tip.getBoundingClientRect();
    var x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + r.width > window.innerWidth) x = evt.clientX - r.width - pad;
    if (y + r.height > window.innerHeight) y = evt.clientY - r.height - pad;
    tip.style.left = Math.max(4, x) + "px"; tip.style.top = Math.max(4, y) + "px";
  }
  function hideTip() { if (tip) tip.classList.add("hidden"); }

  /* ---- Hourly aggregation of the 10-minute buckets ---- */
  function hourly(start, step, arrays) {
    var groups = [], idxOf = {}, n = arrays[0].length;
    for (var i = 0; i < n; i++) {
      /* start of the LOCAL hour (not UTC): correct for zones with a 30/45 minute offset */
      var ts = start + i * step, d = new Date(ts * 1000);
      d.setMinutes(0, 0, 0);
      var hr = d.getTime() / 1000;
      var g = idxOf[hr];
      if (g === undefined) { g = groups.length; idxOf[hr] = g; groups.push({ ts: hr, n: 0, valid: 0, v: arrays.map(function () { return 0; }) }); }
      var gr = groups[g]; gr.n++;
      var ok = false;
      arrays.forEach(function (a, k) { var x = a[i]; if (isNum(x)) { gr.v[k] += x; ok = true; } });
      if (ok) gr.valid++;
    }
    var last = groups.length - 1;
    groups.forEach(function (gr, i) {
      gr.empty = gr.valid === 0;
      gr.running = i === last && gr.n < 6;          /* current hour */
      gr.partial = !gr.running && gr.n < 6;         /* first hour, cut off */
    });
    return groups;
  }
  function hourLabel(ts) { return new Date(ts * 1000).getHours(); }

  /* ---- 24 h columns: allowed (neutral) + blocked (accent), one annotation (peak) ---- */
  function niceMax(v) {            /* 4 integer grid intervals (step 1/2/5 x 10^k) */
    var need = Math.max(1, Math.ceil(v / 4)), p = Math.pow(10, Math.floor(Math.log10(need))), f = need / p;
    return 4 * (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
  }
  function topRounded(x, y, w, hh, r) {
    r = Math.min(r, w / 2, hh);
    return "M" + x + "," + (y + hh) + "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) + "V" + (y + hh) + "Z";
  }
  function renderSeries() {
    var card = $("dns-c-series"), sr = top && top.series_24h;
    if (!sr || !Array.isArray(sr.buckets) || !sr.buckets.length) { card.hidden = true; return; }
    card.hidden = false;
    var B = sr.buckets;
    var g = hourly(sr.start, sr.step, [B.map(function (b) { return b.allowed; }),
      B.map(function (b) { return b.blocked; }), B.map(function (b) { return b.nxdomain; })]);
    var svg = $("dns-svg-series");
    var W = Math.max(280, Math.round(svg.clientWidth || 600)), H = Math.max(160, Math.round(svg.clientHeight || 210));
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("aria-label", t("h_series"));
    svg.replaceChildren();
    var tot = 0, blk = 0, peak = -1, peakV = 0;
    g.forEach(function (x, i) {
      if (x.empty) return;
      var sum = x.v[0] + x.v[1];
      tot += sum; blk += x.v[1];
      if (sum > peakV) { peakV = sum; peak = i; }
    });
    var title = $("dns-h-series");
    if (!tot) {
      title.textContent = t("h_series");
      svg.appendChild(s("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, t("no_series")));
      $("dns-leg-series").replaceChildren();
      return;
    }
    var ph0 = hourLabel(g[peak].ts);
    title.textContent = fmt("series_head", { x: num(tot), y: pct1(blk / tot * 100),
      z: fmt("hours_range", { x: ph0 + "–" + (ph0 + 1) }) });
    var L = 34, R = 6, T = 16, B2 = 22, pw = W - L - R, ph = H - T - B2, n = g.length;
    var ymax = niceMax(peakV), base = T + ph, sc = ph / ymax;
    for (var i = 0; i <= 4; i++) {
      var v = ymax / 4 * i, y = base - v * sc;
      svg.appendChild(s("line", { x1: L, x2: W - R, y1: y, y2: y, class: i === 0 ? "ax" : "gl" }));
      svg.appendChild(s("text", { x: L - 5, y: y + 3, "text-anchor": "end", class: "tk" }, compact(v)));
    }
    var slot = pw / n, bw = Math.max(3, Math.min(24, slot - 2)), GAP = 2, every = W >= 560 ? 3 : 6;
    var wash = s("rect", { class: "wash", y: T, height: ph, width: slot, visibility: "hidden" });
    svg.appendChild(wash);
    g.forEach(function (x, i) {
      var x0 = L + i * slot, bx = x0 + (slot - bw) / 2, hr = hourLabel(x.ts);
      if (hr % every === 0 && x0 > L + 8 && x0 < W - R - 8) {
        svg.appendChild(s("text", { x: x0 + slot / 2, y: H - 6, "text-anchor": "middle", class: "tk" }, fmt("hour_tick", { x: hr })));
      }
      if (x.empty) return;
      var al = x.v[0], bl = x.v[1], cls = x.running ? " part" : "";
      var ha = al * sc, hb = bl * sc, ya = base - ha;
      if (al > 0) {
        if (bl <= 0) svg.appendChild(s("path", { d: topRounded(bx, ya, bw, ha, 4), class: "f-allowed" + cls }));
        else svg.appendChild(s("rect", { x: bx, y: ya, width: bw, height: Math.max(1, ha), class: "f-allowed" + cls }));
      }
      if (bl > 0) {
        var yb = ya - hb, hh = Math.max(1, hb - (al > 0 ? GAP : 0));
        svg.appendChild(s("path", { d: topRounded(bx, yb, bw, hh, 4), class: "f-blocked" + cls }));
      }
    });
    /* annotation: exactly one, the peak hour with its value at the column */
    var px = L + peak * slot + slot / 2, py = base - peakV * sc - 4;
    var pk = fmt("peak", { x: num(peakV) }), half = pk.length * 3.4 + 4;   /* rough text width / 2 at 12 px */
    var ax = px, anc = "middle";
    if (px + half > W - R) { ax = W - R; anc = "end"; }
    else if (px - half < L) { ax = L; anc = "start"; }
    svg.appendChild(s("text", { x: ax, y: Math.max(11, py), "text-anchor": anc, class: "ann" }, pk));
    g.forEach(function (x, i) {
      var hit = s("rect", { x: L + i * slot, y: T, width: slot, height: ph, class: "hit" });
      var sum = x.empty ? null : x.v[0] + x.v[1];
      hit.setAttribute("role", "img");
      hit.setAttribute("aria-label", hourLabel(x.ts) + ":00 " + (sum == null ? "–" : num(sum)));
      var move = function (evt) {
        if (x.empty) { hideTip(); wash.setAttribute("visibility", "hidden"); return; }
        wash.setAttribute("x", L + i * slot); wash.setAttribute("visibility", "visible");
        var rows = [{ k: "blocked", val: num(x.v[1]), name: t("st_blocked") },
          { k: "allowed", val: num(x.v[0]), name: t("st_allowed") }];
        if (x.v[2] > 0) rows.push({ k: "serious", val: num(x.v[2]), name: t("of_nx") });
        var ttl = clock(x.ts) + "–" + clock(x.ts + 3600) + (x.running ? " · " + t("running") : x.partial ? " · " + t("partial") : "");
        showTip(ttl, rows, evt);
      };
      hit.addEventListener("pointermove", move); hit.addEventListener("pointerdown", move);
      hit.addEventListener("pointerleave", function () { hideTip(); wash.setAttribute("visibility", "hidden"); });
      svg.appendChild(hit);
    });
    var leg = $("dns-leg-series"); leg.replaceChildren();
    [["allowed", t("st_allowed")], ["blocked", t("st_blocked")]].forEach(function (it) {
      var sp = h("span"); sp.appendChild(h("i", "dns-sw k-" + it[0])); sp.appendChild(h("span", "", it[1])); leg.appendChild(sp);
    });
    $("dns-s-series").textContent = t("n_series");
  }

  /* ---- Small multiples: one row per device, shared scale ---- */
  function renderClients() {
    var card = $("dns-c-clients"), c = top && top.clients_24h, box = $("dns-spark");
    if (!c || !Array.isArray(c.clients) || !c.clients.length || !c.rest) { card.hidden = true; return; }
    card.hidden = false;
    var rows = c.clients.map(function (x) { return { name: x.name, total: x.total, blocked: x.blocked, series: x.series, bser: x.blocked_series }; });
    if (c.rest.total > 0) rows.push({ name: t("rest"), total: c.rest.total, blocked: c.rest.blocked, series: c.rest.series, bser: c.rest.blocked_series });
    rows.forEach(function (r) { r.g = hourly(c.start, c.step, r.bser ? [r.series, r.bser] : [r.series]); });
    var gmax = 0;
    rows.forEach(function (r) { r.g.forEach(function (x) { if (x.v[0] > gmax) gmax = x.v[0]; }); });
    var all = c.clients.reduce(function (a, x) { return a + x.total; }, 0) + (c.rest.total || 0);
    $("dns-h-clients").textContent = all > 0
      ? fmt("h_clients_top", { x: c.clients[0].name, y: Math.round(c.clients[0].total / all * 100) })
      : t("h_clients");
    $("dns-s-clients").textContent = t("n_clients");
    var pf = pctColumn(rows.map(function (r) { return isNum(r.blocked) && r.total ? r.blocked / r.total * 100 : null; }));
    box.replaceChildren();
    var head = h("div", "dns-sp-row dns-sp-head");
    head.appendChild(h("span", "", t("col_dev")));
    head.appendChild(h("span", "num", t("col_n")));
    head.appendChild(h("span", "num", t("col_blk")));
    head.appendChild(h("span", "sp-trend", fmt("col_trend", { x: num(gmax) })));
    box.appendChild(head);
    rows.forEach(function (r) {
      var row = h("div", "dns-sp-row");
      var nm = h("span", "sp-name", r.name); nm.title = r.name; row.appendChild(nm);
      row.appendChild(h("span", "num", num(r.total)));
      row.appendChild(h("span", "num", isNum(r.blocked) && r.total ? pf(r.blocked / r.total * 100) : "–"));
      var W = 250, Hh = 28, n = r.g.length, slot = W / n, bw = Math.max(2, slot - 2);
      var svg = s("svg", { viewBox: "0 0 " + W + " " + Hh, preserveAspectRatio: "none", class: "sp-svg", role: "img" });
      svg.setAttribute("aria-label", r.name + ": " + num(r.total));
      var wash = s("rect", { class: "wash", y: 0, height: Hh, width: slot, visibility: "hidden" });
      svg.appendChild(wash);
      r.g.forEach(function (x, i) {
        var v = x.v[0];
        if (!x.empty && v > 0) {
          var hh = Math.max(1.5, v / (gmax || 1) * (Hh - 2));
          svg.appendChild(s("rect", { x: i * slot + (slot - bw) / 2, y: Hh - hh, width: bw, height: hh, class: "f-allowed" + (x.running ? " part" : "") }));
        }
        var hit = s("rect", { x: i * slot, y: 0, width: slot, height: Hh, class: "hit" });
        var mv = function (evt) {
          if (x.empty) { hideTip(); return; }
          wash.setAttribute("x", i * slot); wash.setAttribute("visibility", "visible");
          var rws = [{ k: "allowed", val: num(v), name: t("queries_l") }];
          if (r.bser) rws.push({ k: "blocked", val: num(x.v[1]), name: t("blocked_l") });
          showTip(r.name + " · " + clock(x.ts) + "–" + clock(x.ts + 3600) + (x.running ? " · " + t("running") : ""), rws, evt);
        };
        hit.addEventListener("pointermove", mv); hit.addEventListener("pointerdown", mv);
        hit.addEventListener("pointerleave", function () { hideTip(); wash.setAttribute("visibility", "hidden"); });
        svg.appendChild(hit);
      });
      row.appendChild(svg);
      box.appendChild(row);
    });
  }

  /* ---- Share as a horizontal 100 % bar, large segments labelled directly ---- */
  function shareBar(box, parts, label, subKey, headId, claim, emptyKey) {
    var svg = box.querySelector("svg"), ul = box.querySelector("ul");
    var total = parts.reduce(function (a, p) { return a + p.n; }, 0);
    ul.replaceChildren(); svg.replaceChildren();
    var sub = box.querySelector(".dns-sub"); if (sub) sub.textContent = t(subKey);
    $(headId).textContent = (total && claim) ? label + " – " + claim(parts, total) : label;
    if (!total) { ul.appendChild(h("li", "dns-empty", t(emptyKey || "empty"))); return; }
    var W = Math.max(200, Math.round(svg.clientWidth || 400)), Hh = 22, GAP = 2;
    svg.setAttribute("viewBox", "0 0 " + W + " " + Hh);
    svg.setAttribute("aria-label", label);
    var pf = pctColumn(parts.map(function (p) { return p.n / total * 100; }));
    var x = 0, vis = parts.filter(function (p) { return p.n > 0; });
    vis.forEach(function (p, i) {
      var w = p.n / total * W, rw = Math.max(1, w - (i < vis.length - 1 ? GAP : 0)), r;
      if (i === vis.length - 1) {
        r = s("path", { d: "M" + x + ",0H" + (x + rw - 4) + "Q" + (x + rw) + ",0 " + (x + rw) + ",4V" + (Hh - 4) +
          "Q" + (x + rw) + "," + Hh + " " + (x + rw - 4) + "," + Hh + "H" + x + "Z", class: "f-" + p.fill });
      } else r = s("rect", { x: x, y: 0, width: rw, height: Hh, class: "f-" + p.fill });
      r.setAttribute("role", "img");
      r.setAttribute("aria-label", p.name + ": " + num(p.n));
      var mv = function (evt) { showTip(p.name, [{ k: p.key, val: num(p.n), name: pf(p.n / total * 100) }], evt); };
      r.addEventListener("pointermove", mv); r.addEventListener("pointerdown", mv);
      r.addEventListener("pointerleave", hideTip);
      svg.appendChild(r);
      var txt = p.name + " " + pf(p.n / total * 100);
      if (rw > txt.length * 6.4 + 14) {                 /* label only if it fits with margin */
        svg.appendChild(s("text", { x: x + rw / 2, y: Hh / 2 + 4, "text-anchor": "middle", class: "seg-t i-" + p.fill }, txt));
      }
      x += w;
    });
    parts.forEach(function (p) {
      var li = h("li");
      li.appendChild(h("i", "k-" + p.key));
      li.appendChild(h("span", "lbl", p.name));
      li.appendChild(h("span", "val", num(p.n) + " · " + pf(p.n / total * 100)));
      ul.appendChild(li);
    });
  }

  function renderShare(p) {
    var card = $("dns-c-share");
    if (!p || !Array.isArray(p.qtypes) || !p.statuses) { card.hidden = true; return; }
    card.hidden = false;
    var qparts = [], other = 0, bySlot = {};
    p.qtypes.forEach(function (q) { if (q.qtype in QTYPE_SLOT) bySlot[q.qtype] = q.n; else other += q.n; });
    Object.keys(QTYPE_SLOT).forEach(function (k) {
      if (bySlot[k]) qparts.push({ name: k, n: bySlot[k], fill: String(QTYPE_SLOT[k]), key: String(QTYPE_SLOT[k]) });
    });
    if (other) qparts.push({ name: t("other"), n: other, fill: "rest", key: "rest" });
    shareBar($("dns-d-qtypes"), qparts, t("h_qtypes"), "n_qtypes", "dns-h-qtypes", function (ps, tot) {
      var a = ps.slice().sort(function (x, y) { return y.n - x.n; }).slice(0, 2);
      return a.map(function (x) { return Math.round(x.n / tot * 100) + " % " + x.name; }).join(", ");
    }, Object.keys(p.statuses).some(function (k) { return p.statuses[k] > 0; }) ? "no_qtypes" : "empty");
    var sparts = Object.keys(STATUS).map(function (k) {
      return { name: t("st_" + k), n: p.statuses[k] || 0, fill: STATUS[k].fill, key: STATUS[k].fill, id: k };
    });
    shareBar($("dns-d-status"), sparts, t("h_status"), "n_status", "dns-h-status", function (ps, tot) {
      var a = ps.slice().sort(function (x, y) { return y.n - x.n; }).slice(0, 2).filter(function (x) { return x.n > 0; });
      return a.map(function (x) { return Math.round(x.n / tot * 100) + " % " + x.name.toLowerCase(); }).join(", ");
    });
  }

  /* ---- Top tables (domain | hits | frequency) ---- */
  function fillTable(id, rows, labelKey, ref, blk) {
    var box = $(id), tb = box.querySelector("table");
    tb.replaceChildren();
    if (!Array.isArray(rows)) { box.hidden = true; return; }
    box.hidden = false;
    var thead = h("thead"), tr = h("tr");
    tr.appendChild(h("th", "", t(labelKey === "qname" ? "c_domain" : "c_device")));
    tr.appendChild(h("th", "num", t("c_hits")));
    tr.appendChild(h("th", "", t("c_freq")));
    thead.appendChild(tr); tb.appendChild(thead);
    var body = h("tbody");
    if (!rows.length) {
      var e = h("tr"), td = h("td", "dns-empty", t("empty")); td.colSpan = 3; e.appendChild(td); body.appendChild(e);
    }
    var max = rows.length ? Math.max.apply(null, rows.map(function (r) { return r.n; })) : 1;
    var pf = pctColumn(rows.map(function (r) { return ref ? r.n / ref * 100 : null; }));
    rows.forEach(function (r, i) {
      var row = h("tr", i === 0 ? "focal" : "");
      var label = labelKey === "qname" ? domText(r[labelKey]) : r[labelKey];
      var d = h("td", "dom", label); d.title = label; row.appendChild(d);
      row.appendChild(h("td", "num", num(r.n)));
      var bc = h("td", "barc"), bar = h("div", "dns-bar" + (blk ? " blk" : ""));
      bar.style.width = Math.max(2, Math.round(r.n / (max || 1) * 100)) + "%";
      if (ref) bar.title = pf(r.n / ref * 100);
      bc.appendChild(bar); row.appendChild(bc);
      body.appendChild(row);
    });
    tb.appendChild(body);
  }

  function toMs(v, isSec) {          /* Unix seconds, milliseconds or ISO string -> ms; otherwise null */
    if (isNum(v)) return isSec || v < 1e11 ? v * 1000 : v;
    if (typeof v === "string") { var d = Date.parse(v); return d || null; }
    return null;
  }

  function tile(label, value, sub) {
    var m = h("div", "metric");
    m.appendChild(h("div", "metric-label", label));
    m.appendChild(h("div", "metric-value", value));
    m.appendChild(h("div", "metric-sub", sub));
    return m;
  }

  function renderTop() {
    var tilesCard = $("dns-c-tiles"), tablesCard = $("dns-c-tables");
    if (!top) return;
    var p = (top.periods || {})[period];
    if (!p) { tilesCard.hidden = tablesCard.hidden = $("dns-c-share").hidden = true; renderSeries(); renderClients(); return; }
    var plabel = t("p_" + period);
    tilesCard.hidden = false;
    var pct = p.total ? p.blocked / p.total * 100 : 0;
    $("dns-tiles").replaceChildren(
      tile(t("t_total"), num(p.total), plabel),
      tile(t("t_blocked"), num(p.blocked), plabel),
      tile(t("t_pct"), pct1(pct), plabel),
      tile(t("t_clients"), p.active_clients == null ? "–" : num(p.active_clients), plabel));
    tablesCard.hidden = false;
    fillTable("dns-t-permitted", p.top_permitted, "qname", (p.total || 0) - (p.blocked || 0), false);
    fillTable("dns-t-blocked", p.top_blocked, "qname", p.blocked, true);
    fillTable("dns-t-clients", p.top_clients, "name", p.total, false);
    fillTable("dns-t-clients-blocked", p.top_clients_blocked, "name", p.blocked, true);
    renderShare(p);
    renderSeries();
    renderClients();
    var hl = top.health || {}, parts = [];
    var cs = toMs(hl.capture_since || top.capture_since), cn = toMs(hl.connected_since);
    if (cs) parts.push(fmt("since", { x: new Date(cs).toLocaleString(loc()) }));
    var connTxt = hl.connected ? t("connected") : t("disconnected");
    if (hl.connected && cn && (!cs || Math.abs(cn - cs) > 60000)) connTxt = fmt("conn_since", { x: new Date(cn).toLocaleString(loc()) });
    parts.push(connTxt);
    parts.push(fmt("reconnects", { x: hl.reconnects || 0 }));
    if (hl.last_error) parts.push(fmt("err_fmt", { x: errText(hl.last_error) }));
    var hbox = $("dns-health");
    hbox.textContent = parts.join(" · ");
    var demo = top.demo === true;
    var lp = toMs(hl.last_packet_ts, true);       /* Unix seconds */
    if (!demo && hl.connected && lp && (Date.now() - lp) > 300000) {
      var wsp = h("span", "dns-hwarn", fmt("no_pkt", { x: Math.floor((Date.now() - lp) / 60000) }));
      hbox.appendChild(document.createTextNode(" · ")); hbox.appendChild(wsp);
    }
    var gen = Date.parse(top.generated);
    $("dns-stale").hidden = demo || !(gen && (Date.now() - gen) / 1000 > STALE_S);
  }

  /* ---- Query log (collapsible; while closed only the summary line is updated) ---- */
  var logBox = $("dns-c-log");
  function renderLogMeta() {
    var meta = $("dns-log-meta");
    if (!live || !Array.isArray(live.events)) { meta.textContent = ""; return; }
    var ev = live.events, ref = Date.parse(live.generated); if (!ref) ref = Date.now();
    var cut = ref / 1000 - 300, n = 0, b = 0;
    ev.forEach(function (e) { if (e.ts >= cut) { n++; if (e.status === "blocked") b++; } });
    var trunc = ev.length >= 200 && ev[ev.length - 1].ts > cut;
    meta.textContent = fmt("log_meta", { x: num(ev.length), y: (trunc ? t("at_least") + " " : "") + num(n), z: num(b) });
  }
  function renderLive() {
    if (!live || !Array.isArray(live.events)) { logBox.hidden = true; return; }
    logBox.hidden = false;
    renderLogMeta();
    if (paused || !logBox.open) return;
    var tb = $("dns-log").tBodies[0];
    tb.replaceChildren();
    var q = query.trim().toLowerCase(), cnt = 0, sel = [];
    for (var i = 0; i < live.events.length && cnt < limit; i++) {
      var e = live.events[i];
      if (filter !== "all" && e.status !== filter) continue;
      if (q && (e.qname || "").toLowerCase().indexOf(q) < 0 && (e.name || "").toLowerCase().indexOf(q) < 0) continue;
      cnt++; sel.push(e);
    }
    var mf = msColumn(sel.map(function (e) { return e.latency_ms; }));
    sel.forEach(function (e) {
      var st = STATUS[e.status] || STATUS.no_answer;
      var tr = h("tr");
      tr.appendChild(h("td", "tnum", new Date(e.ts * 1000).toLocaleTimeString(loc(), { hour12: false })));
      tr.appendChild(h("td", "", e.qtype));
      var dn = domText(e.qname), dm = h("td", "dom", dn); dm.title = dn; tr.appendChild(dm);
      var dv = h("td", "dev", e.name); dv.title = e.name || ""; tr.appendChild(dv);
      var sd = h("td"); sd.appendChild(h("span", "badge " + st.cls, st.icon + " " + t("st_" + (STATUS[e.status] ? e.status : "no_answer")))); tr.appendChild(sd);
      var rk = "r_" + (e.reply || "none");
      tr.appendChild(h("td", "", Object.prototype.hasOwnProperty.call(TXT.en, rk) ? t(rk) : t("r_none")));
      tr.appendChild(h("td", "num tnum", mf(e.latency_ms)));
      tb.appendChild(tr);
    });
  }

  function fillSelects() {
    var f = $("dns-filter"), cur = filter;
    f.replaceChildren();
    [["all", t("f_all")]].concat(["allowed", "blocked", "nxdomain", "no_answer"].map(function (k) { return [k, t("st_" + k)]; }))
      .forEach(function (o) { var op = h("option", "", o[1]); op.value = o[0]; f.appendChild(op); });
    f.value = cur;
    var l = $("dns-limit");
    l.replaceChildren();
    [50, 100, 200].forEach(function (n) { var op = h("option", "", fmt("rows_n", { x: n })); op.value = String(n); l.appendChild(op); });
    l.value = String(limit);
  }

  function applyText() {
    sec.querySelectorAll("[data-dns-i18n]").forEach(function (n) {
      if (n.id === "dns-pause") return;
      n.textContent = t(n.dataset.dnsI18n);
    });
    sec.querySelectorAll("[data-dns-aria]").forEach(function (n) { n.setAttribute("aria-label", t(n.dataset.dnsAria)); });
    $("dns-search").placeholder = t("search_ph");
    $("dns-pause").textContent = t(paused ? "resume" : "pause");
    sec.querySelectorAll("[data-dns-period]").forEach(function (b) {
      b.classList.toggle("active", b.dataset.dnsPeriod === period);
    });
    fillSelects();
  }

  /* ---- Demo mode: shift all timestamps so the static demo never looks stale ---- */
  function shiftIso(o, k, d) {
    if (typeof o[k] !== "string") return;
    var ms = Date.parse(o[k]);
    if (ms) o[k] = new Date(ms + d * 1000).toISOString();
  }
  function shiftNum(o, k, d) { if (o && isNum(o[k])) o[k] += d; }
  function shiftDemo(j) {
    if (!j || j.demo !== true || !isNum(j.exported_at)) return;
    var d = Math.round((Date.now() / 1000 - j.exported_at) / DEMO_STEP) * DEMO_STEP;   /* keeps the 600 s bucket grid */
    if (!d) return;
    shiftIso(j, "generated", d); shiftIso(j, "capture_since", d);
    var hl = j.health;
    if (hl && typeof hl === "object") ["capture_since", "connected_since", "last_packet_ts"].forEach(function (k) { shiftNum(hl, k, d); });
    if (j.series_24h) {
      shiftNum(j.series_24h, "start", d);
      if (Array.isArray(j.series_24h.buckets)) j.series_24h.buckets.forEach(function (b) { shiftNum(b, "ts", d); });
    }
    if (j.clients_24h) shiftNum(j.clients_24h, "start", d);
    if (Array.isArray(j.events)) j.events.forEach(function (e) { shiftNum(e, "ts", d); });
  }

  function renderAll() { renderTop(); renderLive(); }
  /* app.js: "The box provides no top domains or top clients" is wrong while this section is shown. */
  function setExceptionsNote(hide) {
    var n = document.querySelector('[data-i18n="exceptions_note"]');
    if (n) n.hidden = hide;
  }
  function update() {
    var vis = okTop || okLive;
    sec.hidden = !vis;
    if (!vis) { shown = false; setExceptionsNote(false); return; }
    if (!shown) { shown = true; setExceptionsNote(true); renderAll(); }
  }

  /* Polling: a failing endpoint (typically 404 while the collector is not set up) is retried only every
     RETRY_MS until it has worked once; afterwards the normal interval applies again. */
  function poller(file, every, valid, accept, reject) {
    var ever = false, timer = null;
    function again(ms) { clearTimeout(timer); timer = setTimeout(run, ms); }
    function run() {
      if (file === "dns_live.json" && paused) { again(every); return; }
      fetch("data/" + file + "?t=" + Date.now(), { cache: "no-store" })
        .then(function (r) { if (!r.ok) throw new Error("http"); return r.json(); })
        .then(function (j) { if (!valid(j)) throw new Error("shape"); return j; })
        .then(function (j) {
          ever = true; shiftDemo(j);
          try { accept(j); } catch (e) { console.error("dns.js:", e); }
          again(every);
        }, function () {
          reject();
          again(ever ? every : RETRY_MS);
        });
    }
    return { run: run };
  }
  var topPoll = poller("dns_top.json", TOP_MS,
    function (j) { return j && typeof j === "object" && j.periods && typeof j.periods === "object"; },
    function (j) { top = j; okTop = true; update(); if (shown) renderTop(); },
    function () { okTop = false; update(); });
  var livePoll = poller("dns_live.json", LIVE_MS,
    function (j) { return j && typeof j === "object" && Array.isArray(j.events); },
    function (j) { live = j; okLive = true; update(); if (shown) renderLive(); },
    function () { okLive = false; update(); });

  sec.querySelectorAll("[data-dns-period]").forEach(function (b) {
    b.addEventListener("click", function () {
      period = b.dataset.dnsPeriod; ls("ftrap_dns_period", period); applyText(); renderTop();
    });
  });
  $("dns-filter").addEventListener("change", function (e) { filter = e.target.value; renderLive(); });
  $("dns-limit").addEventListener("change", function (e) { limit = parseInt(e.target.value, 10) || 100; renderLive(); });
  $("dns-search").addEventListener("input", function (e) { query = e.target.value; renderLive(); });
  $("dns-pause").addEventListener("click", function () {
    paused = !paused; applyText(); if (!paused) livePoll.run();
  });
  logBox.open = ls("ftrap_dns_log_open") === "1";
  logBox.addEventListener("toggle", function () {
    ls("ftrap_dns_log_open", logBox.open ? "1" : "0");
    if (logBox.open) renderLive();
  });

  /* Language switch: app.js keeps <html lang> current and sets data-lang on toggle; observe both. */
  new MutationObserver(function () { applyText(); if (shown) renderAll(); })
    .observe(root, { attributes: true, attributeFilter: ["lang", "data-lang"] });
  var rt = null;
  window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(function () { if (shown) renderTop(); }, 200); });

  applyText();
  topPoll.run(); livePoll.run();
})();
