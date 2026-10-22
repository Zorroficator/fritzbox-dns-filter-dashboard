"use strict";

/* FTrap - FRITZ!Box DNS filter dashboard. Vanilla JS, no build step.
   Data source: data/ftrap.json + data/series_{day,week,month}.json
   (written periodically by export.py).
   All values from JSON are put into the DOM via textContent (no innerHTML). */

const POLL_MS = 60_000;
const SVG_NS = "http://www.w3.org/2000/svg";

const I18N = {
  de: {
    title: "FTrap", subtitle: "DNS-Filter der FRITZ!Box", demo_note: "Demo – synthetische Daten",
    connecting: "verbinde …", theme_dark: "Dunkel", theme_light: "Hell", stand: "Stand",
    updated_never: "noch keine Daten", err_fetch: "Daten nicht erreichbar",
    err_db: "Datenbank nicht erreichbar", data_fresh: "Daten aktuell", data_stale: "Daten veraltet",
    sec_overview: "Überblick", sec_history: "Verlauf", sec_lists: "Filterlisten", sec_exceptions: "Ausnahmen",
    pct_note: "Anteil mit einer Nachkommastelle; die FRITZ!Box-Oberfläche rundet auf ganze Prozent auf.",
    exceptions_note: "Nur die Anzahl wird erfasst, keine Inhalte. Die Box liefert keine Top-Domains und keine Top-Clients.",
    footer: "FTrap", footer_info: "Keine Top-Domains/-Clients: nicht von der Box geliefert.",
    footer_beta: "FRITZ!OS-Beta-Schnittstelle (getestet: 8.50, Build 136731) – kann sich mit jedem Update ändern",
    t_req_today: "Anfragen heute", t_blk_today: "Blockiert heute", t_pct_today: "Anteil blockiert heute",
    t_restart: "Seit Box-Neustart", t_entries: "Einträge in Filterlisten", t_filter: "Filter",
    t_filter_sub_on: "DNS-Filter aktiv", t_filter_sub_off: "DNS-Filter ausgeschaltet",
    on: "an", off: "aus", of_requests: "blockiert von", since_midnight: "seit 00:00 Uhr", since_time: "seit {t} Uhr",
    span_day: "24 Std.", span_week: "7 Tage", span_month: "30 Tage",
    title_day: "Anfragen je 15 Minuten", title_week: "Anfragen je Stunde", title_month: "Anfragen je Tag",
    legend_allowed: "erlaubt", legend_blocked: "blockiert", legend_pct: "Anteil blockiert (%)",
    partial: "Verlauf seit {t} (weniger Daten als der Zeitraum).",
    no_series: "Noch keine Verlaufsdaten.",
    tip_allowed: "erlaubt", tip_blocked: "blockiert", tip_total: "gesamt", tip_pct: "Anteil",
    th_name: "Name", th_entries: "Einträge", th_active: "Aktiv", th_last: "Letzte Aktualisierung",
    th_status: "Status", th_url: "Quelle", lists_none: "Keine Filterlisten erfasst.",
    st_ok: "in Ordnung", w_status: "Aktualisierung fehlgeschlagen", w_stale: "Aktualisierung überfällig",
    w_not_ready: "Liste nicht bereit", never: "nie",
    ago_min: "vor {n} Min.", ago_h: "vor {n} Std.", ago_d: "vor {n} Tagen", ago_now: "gerade eben",
    ex_domains: "Ausnahmen (Domains)", ex_allow: "davon erlaubt", ex_deny: "davon gesperrt", ex_disabled: "deaktiviert",
    sec_autoupdate: "Automatische Aktualisierung", au_status: "Status", au_interval: "Intervall",
    au_last_auto: "Letzte automatische", au_last_manual: "Letzte manuelle",
    au_every_8h: "alle 8 Stunden", au_daily: "täglich", au_weekly: "wöchentlich", au_monthly: "monatlich",
    au_every_n_h: "alle {n} Std.", au_note: "Nur Anzeige: Die Aktualisierung der Filterlisten läuft in der FRITZ!Box.",
    sec_listupd: "Filterlisten-Aktualisierung", lu_interval: "Intervall",
    lu_24h: "Läufe 24 Std.", lu_7d: "Läufe 7 Tage", lu_30d: "Läufe 30 Tage",
    lu_counts: "{a} automatisch · {m} manuell", lu_recent: "Letzte Läufe",
    lu_auto: "automatisch", lu_manual: "manuell", lu_none: "Noch kein Lauf beobachtet.",
    lu_next: "Nächster Lauf erwartet: {t}", lu_since: "Gezählt seit {t}",
    b_filter_off: "Der DNS-Filter der FRITZ!Box ist ausgeschaltet.",
    b_stale: "Sammler-Daten veraltet: letzter Stand vor {age}.",
    b_stale_err: "Letzte Fehlernotiz: {note} ({when}).",
    b_table: "Hinweis: Datenquelle unvollständig ({n}).",
    b_drift: "Hinweis: Struktur der Box-Antwort weicht ab (fehlt: {m}; neu: {a}).",
    b_list: "Filterliste „{name}“: {why}.",
    b_collector_none: "Sammler: noch keine Fehlernotiz.",
    u_sec: "{n} s", u_min: "{n} Min.", u_h: "{n} Std.", u_d: "{n} Tage",
  },
  en: {
    title: "FTrap", subtitle: "DNS filter of the FRITZ!Box", demo_note: "Demo – synthetic data",
    connecting: "connecting …", theme_dark: "Dark", theme_light: "Light", stand: "As of",
    updated_never: "no data yet", err_fetch: "Data unreachable",
    err_db: "Database unreachable", data_fresh: "Data current", data_stale: "Data stale",
    sec_overview: "Overview", sec_history: "History", sec_lists: "Filter lists", sec_exceptions: "Exceptions",
    pct_note: "Share with one decimal; the FRITZ!Box UI rounds up to whole percent.",
    exceptions_note: "Only the count is collected, not the contents. The box provides no top domains or top clients.",
    footer: "FTrap", footer_info: "No top domains/clients: not provided by the box.",
    footer_beta: "FRITZ!OS beta API (tested: 8.50, build 136731) – may change with any update",
    t_req_today: "Requests today", t_blk_today: "Blocked today", t_pct_today: "Share blocked today",
    t_restart: "Since box restart", t_entries: "Entries in filter lists", t_filter: "Filter",
    t_filter_sub_on: "DNS filter active", t_filter_sub_off: "DNS filter switched off",
    on: "on", off: "off", of_requests: "blocked of", since_midnight: "since 00:00", since_time: "since {t}",
    span_day: "24 h", span_week: "7 days", span_month: "30 days",
    title_day: "Requests per 15 minutes", title_week: "Requests per hour", title_month: "Requests per day",
    legend_allowed: "allowed", legend_blocked: "blocked", legend_pct: "Share blocked (%)",
    partial: "History since {t} (less data than the period).",
    no_series: "No history data yet.",
    tip_allowed: "allowed", tip_blocked: "blocked", tip_total: "total", tip_pct: "share",
    th_name: "Name", th_entries: "Entries", th_active: "Active", th_last: "Last update",
    th_status: "Status", th_url: "Source", lists_none: "No filter lists recorded.",
    st_ok: "OK", w_status: "update failed", w_stale: "update overdue",
    w_not_ready: "list not ready", never: "never",
    ago_min: "{n} min ago", ago_h: "{n} h ago", ago_d: "{n} days ago", ago_now: "just now",
    ex_domains: "Exceptions (domains)", ex_allow: "of which allowed", ex_deny: "of which blocked", ex_disabled: "disabled",
    sec_autoupdate: "Automatic update", au_status: "Status", au_interval: "Interval",
    au_last_auto: "Last automatic", au_last_manual: "Last manual",
    au_every_8h: "every 8 hours", au_daily: "daily", au_weekly: "weekly", au_monthly: "monthly",
    au_every_n_h: "every {n} h", au_note: "Display only: the filter lists are updated by the FRITZ!Box itself.",
    sec_listupd: "Filter list updates", lu_interval: "Interval",
    lu_24h: "Runs 24 h", lu_7d: "Runs 7 days", lu_30d: "Runs 30 days",
    lu_counts: "{a} automatic · {m} manual", lu_recent: "Latest runs",
    lu_auto: "automatic", lu_manual: "manual", lu_none: "No run observed yet.",
    lu_next: "Next run expected: {t}", lu_since: "Counted since {t}",
    b_filter_off: "The FRITZ!Box DNS filter is switched off.",
    b_stale: "Collector data stale: last snapshot {age} ago.",
    b_stale_err: "Last error note: {note} ({when}).",
    b_table: "Note: data source incomplete ({n}).",
    b_drift: "Note: box response structure differs (missing: {m}; new: {a}).",
    b_list: "Filter list “{name}”: {why}.",
    b_collector_none: "Collector: no error note yet.",
    u_sec: "{n} s", u_min: "{n} min", u_h: "{n} h", u_d: "{n} days",
  },
};

function safeLS(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function setLS(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

const browserLang = /^de\b/i.test(navigator.language || "") ? "de" : "en";
let currentLang = I18N[safeLS("ftrap_lang")] ? safeLS("ftrap_lang") : browserLang;
function t(key, vars) {
  let s = (I18N[currentLang] && I18N[currentLang][key]) ?? I18N.en[key] ?? key;
  if (vars) for (const k in vars) s = s.split(`{${k}}`).join(String(vars[k]));
  return s;
}

/* === Formatters ===================================================== */
const isNum = (v) => typeof v === "number" && !Number.isNaN(v);
const locale = () => (currentLang === "en" ? "en-GB" : "de-DE");
function num(v, digits = 0) {
  if (!isNum(v)) return "–";
  return v.toLocaleString(locale(), { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function pct(v) { return isNum(v) ? `${num(v, 1)} %` : "–"; }
function fmtAge(s) {
  if (!isNum(s)) return "–";
  if (s < 90) return t("u_sec", { n: Math.round(s) });
  if (s < 5400) return t("u_min", { n: Math.round(s / 60) });
  if (s < 172800) return t("u_h", { n: Math.round(s / 3600) });
  return t("u_d", { n: Math.round(s / 86400) });
}
function fmtAgo(tsSec, nowSec) {
  if (!tsSec) return t("never");
  const s = Math.max(0, nowSec - tsSec);
  if (s < 90) return t("ago_now");
  if (s < 5400) return t("ago_min", { n: Math.round(s / 60) });
  if (s < 172800) return t("ago_h", { n: Math.round(s / 3600) });
  return t("ago_d", { n: Math.round(s / 86400) });
}
function fmtDateTime(tsSec) {
  if (!tsSec) return "–";
  return new Date(tsSec * 1000).toLocaleString(locale(), {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/* === DOM helpers (textContent only) ==================================== */
function h(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}
function metric(label, value, sub, cls, lead) {
  const d = h("div", "metric" + (lead ? " lead" : ""));
  d.appendChild(h("div", "metric-label", label));
  d.appendChild(h("div", "metric-value" + (cls ? " " + cls : ""), value));
  if (sub) d.appendChild(h("div", "metric-sub", sub));
  return d;
}
function fill(id, nodes) {
  const c = document.getElementById(id);
  c.replaceChildren(...nodes);
}

/* === SVG ============================================================= */
function el(name, attrs, text) {
  const n = document.createElementNS(SVG_NS, name);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
}
function size(svg) {
  const W = Math.max(280, Math.round(svg.clientWidth || 600));
  const H = Math.max(60, Math.round(svg.clientHeight || 220));
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  return { W, H };
}

const tip = document.getElementById("tooltip");
function showTip(lines, evt) {
  tip.replaceChildren(...lines.map((l, i) => {
    const d = document.createElement("div");
    if (i === 0) { const b = document.createElement("b"); b.textContent = l; d.appendChild(b); }
    else d.textContent = l;
    return d;
  }));
  tip.classList.remove("hidden");
  const pad = 14, r = tip.getBoundingClientRect();
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + r.width > window.innerWidth) x = evt.clientX - r.width - pad;
  if (y + r.height > window.innerHeight) y = evt.clientY - r.height - pad;
  tip.style.left = `${Math.max(4, x)}px`;
  tip.style.top = `${Math.max(4, y)}px`;
}
function hideTip() { tip.classList.add("hidden"); }

function fmtBucket(ts, kind) {
  const d = new Date(ts * 1000);
  if (kind === "day") return d.toLocaleDateString(locale(), { weekday: "short", day: "2-digit", month: "2-digit" });
  return d.toLocaleString(locale(), { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function axisLabel(ts, kind, spanKey) {
  const d = new Date(ts * 1000);
  if (spanKey === "day") return d.toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  if (spanKey === "week") return d.toLocaleDateString(locale(), { weekday: "short", day: "2-digit" });
  return d.toLocaleDateString(locale(), { day: "2-digit", month: "2-digit" });
}

/* Stacked bars (allowed + blocked) + percent line (right axis) */
function drawChart(svg, series, spanKey) {
  const { W, H } = size(svg);
  svg.replaceChildren();
  const pts = (series && series.points) || [];
  const any = pts.some((p) => isNum(p.total));
  if (!any) {
    svg.appendChild(el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "empty" }, t("no_series")));
    return;
  }
  const L = 48, R = 44, T = 10, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const maxTot = Math.max(1, ...pts.map((p) => p.total || 0));
  const maxPct = Math.max(5, Math.ceil(Math.max(...pts.map((p) => p.pct || 0)) / 5) * 5);
  const n = pts.length, slot = pw / n, bw = Math.max(1, slot * 0.78);
  const Y = (v) => T + ph - (v / maxTot) * ph;
  const YP = (v) => T + ph - (v / maxPct) * ph;
  for (let i = 0; i <= 4; i++) {
    const v = (maxTot / 4) * i, y = Y(v);
    svg.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, class: "grid-line" }));
    svg.appendChild(el("text", { x: L - 5, y: y + 3, "text-anchor": "end", class: "axis-tick" }, num(Math.round(v))));
    svg.appendChild(el("text", { x: W - R + 5, y: y + 3, class: "axis-tick" }, `${num((maxPct / 4) * i, 0)} %`));
  }
  const ticks = Math.min(W < 480 ? 4 : 6, n);
  for (let i = 0; i < ticks; i++) {
    const idx = Math.round((i * (n - 1)) / Math.max(1, ticks - 1));
    svg.appendChild(el("text", {
      x: L + slot * idx + slot / 2, y: H - 8, "text-anchor": "middle", class: "axis-tick",
    }, axisLabel(pts[idx].ts, series.kind, spanKey)));
  }
  const line = [];
  pts.forEach((p, i) => {
    if (!isNum(p.total)) return;
    const x = L + slot * i + (slot - bw) / 2;
    const yBlk = Y(p.blocked), yTot = Y(p.total);
    svg.appendChild(el("rect", { x, y: yTot, width: bw, height: Math.max(0, yBlk - yTot), class: "bar-allowed" }));
    svg.appendChild(el("rect", { x, y: yBlk, width: bw, height: Math.max(0, T + ph - yBlk), class: "bar-blocked" }));
    if (isNum(p.pct)) line.push([L + slot * i + slot / 2, YP(p.pct)]);
  });
  if (line.length > 1) {
    svg.appendChild(el("polyline", { points: line.map((q) => q.join(",")).join(" "), class: "line-pct" }));
  }
  line.forEach((q) => svg.appendChild(el("circle", { cx: q[0], cy: q[1], r: 2, class: "dot-pct" })));

  const hit = el("rect", { x: L, y: T, width: pw, height: ph, fill: "transparent" });
  const move = (evt) => {
    const r = svg.getBoundingClientRect();
    const x = ((evt.clientX - r.left) / r.width) * W;
    const i = Math.floor((x - L) / slot);
    if (i < 0 || i >= n || !isNum(pts[i].total)) { hideTip(); return; }
    const p = pts[i];
    showTip([fmtBucket(p.ts, series.kind),
      `${t("tip_total")}: ${num(p.total)}`, `${t("tip_allowed")}: ${num(p.allowed)}`,
      `${t("tip_blocked")}: ${num(p.blocked)}`, `${t("tip_pct")}: ${pct(p.pct)}`], evt);
  };
  hit.addEventListener("pointermove", move);
  hit.addEventListener("pointerdown", move);
  hit.addEventListener("pointerleave", hideTip);
  svg.appendChild(hit);
}

/* === Render ========================================================== */
let lastData = null;
const seriesStore = { day: null, week: null, month: null };
let curSpan = ["day", "week", "month"].includes(safeLS("ftrap_span")) ? safeLS("ftrap_span") : "day";

function setStatus(kind, text) {
  document.getElementById("status-dot").className = `status-dot ${kind}`;
  document.getElementById("status-text").textContent = text;
}
function applyI18n() {
  document.documentElement.lang = currentLang;
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  updateThemeButton();
  document.getElementById("btn-lang-de").classList.toggle("active", currentLang === "de");
  document.getElementById("btn-lang-en").classList.toggle("active", currentLang === "en");
  document.querySelectorAll("[data-span]").forEach((b) =>
    b.classList.toggle("active", b.dataset.span === curSpan));
}

function listWarnText(w) {
  return t({ status: "w_status", stale: "w_stale", not_ready: "w_not_ready" }[w] || "w_status");
}

function renderBanners(d, nowSec) {
  const out = [];
  const add = (cls, text) => out.push(h("div", `banner ${cls}`, text));
  if (d.available && d.filter_enabled === false) add("err", t("b_filter_off"));
  const c = d.collector;
  if (c && c.stale) {
    let txt = t("b_stale", { age: fmtAge(c.age_s) });
    const e = c.last_error;
    if (e) txt += " " + t("b_stale_err", { note: e.note || "–", when: fmtDateTime(e.ts) });
    add("err", txt);
  }
  ((d.lists && d.lists.items) || []).forEach((li) => {
    if (li.warnings && li.warnings.length) {
      add("warn", t("b_list", { name: li.name || "?", why: li.warnings.map(listWarnText).join(", ") }));
    }
  });
  (d.notes || []).forEach((n) => add("warn", t("b_table", { n })));
  if (d.drift) {
    const sp = (k) => "statistics." + k;
    const miss = (d.drift.missing || []).concat((d.drift.stats_missing || []).map(sp));
    const added = (d.drift.added || []).concat((d.drift.stats_added || []).map(sp));
    add("info", t("b_drift", { m: miss.join(", ") || "–", a: added.join(", ") || "–" }));
  }
  document.getElementById("banners").replaceChildren(...out);
}

function renderTiles(d) {
  if (!d.available) { fill("tiles", []); return; }
  const td = d.today || {}, sr = d.since_restart || {};
  let since = t("since_midnight");
  if (td.effective_since_ts && td.since_ts && td.effective_since_ts > td.since_ts) {
    const hm = new Date(td.effective_since_ts * 1000).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
    since = t("since_time", { t: hm });
  }
  const tiles = [
    metric(t("t_req_today"), num(td.total), since),
    metric(t("t_blk_today"), num(td.blocked), since),
    metric(t("t_pct_today"), pct(td.pct), since, null, true),
    metric(t("t_restart"), pct(sr.pct), `${num(sr.blocked)} ${t("of_requests")} ${num(sr.total)}`),
    metric(t("t_entries"), num(d.lists && d.lists.entries_active)),
    metric(t("t_filter"), d.filter_enabled ? t("on") : t("off"),
      d.filter_enabled ? t("t_filter_sub_on") : t("t_filter_sub_off"),
      d.filter_enabled ? "on" : "off"),
  ];
  fill("tiles", tiles);
}

function renderLists(d, nowSec) {
  const tb = document.getElementById("lists-table");
  const items = (d.lists && d.lists.items) || [];
  if (!items.length) { tb.replaceChildren(h("tbody", null)); const tr = h("tr"); tr.appendChild(h("td", null, t("lists_none"))); tb.firstChild.appendChild(tr); return; }
  const head = h("tr");
  ["th_name", "th_entries", "th_active", "th_last", "th_status", "th_url"].forEach((k) =>
    head.appendChild(h("th", k === "th_entries" ? "num" : null, t(k))));
  const thead = h("thead"); thead.appendChild(head);
  const body = h("tbody");
  items.forEach((li) => {
    const tr = h("tr", li.enabled ? "" : "inactive");
    tr.appendChild(h("td", null, li.name || "–"));
    const ne = h("td", "num", num(li.entry_count)); tr.appendChild(ne);
    tr.appendChild(h("td", null, li.enabled ? t("on") : t("off")));
    const last = h("td", null, fmtAgo(li.last_success_ts, nowSec));
    if (li.last_success_ts) last.title = fmtDateTime(li.last_success_ts);
    tr.appendChild(last);
    const st = h("td");
    if (li.warnings && li.warnings.length) {
      st.appendChild(h("span", "badge warn", li.warnings.map(listWarnText).join(", ")));
      const err = [li.latest_error, li.latest_cause && li.latest_status !== "success" ? li.latest_cause : null]
        .filter(Boolean).join(" · ");
      if (li.latest_status && li.latest_status !== "success") {
        st.appendChild(h("div", "err-text", `${li.latest_status}${err ? ": " + err : ""}`));
      } else if (li.latest_error) {
        st.appendChild(h("div", "err-text", li.latest_error));
      }
    } else {
      st.appendChild(h("span", "badge ok", t("st_ok")));
    }
    tr.appendChild(st);
    const u = h("td", "url-cell", shortUrl(li.url));
    if (li.url) u.title = li.url;
    tr.appendChild(u);
    body.appendChild(tr);
  });
  tb.replaceChildren(thead, body);
}
function shortUrl(u) {
  if (!u) return "–";
  try { const x = new URL(u); return x.host + x.pathname; } catch (e) { return String(u); }
}

function renderExceptions(d) {
  const ex = d.exceptions || {};
  fill("exceptions-grid", d.available ? [
    metric(t("ex_domains"), num(ex.n_domains)),
    metric(t("ex_allow"), num(ex.n_allow)),
    metric(t("ex_deny"), num(ex.n_deny)),
    metric(t("ex_disabled"), num(ex.n_disabled)),
  ] : []);
}

const INTERVAL_KEYS = { 28800: "au_every_8h", 86400: "au_daily", 604800: "au_weekly", 2592000: "au_monthly" };
function fmtInterval(au) {
  if (!au || (au.enabled == null && !isNum(au.interval_s))) return "–";
  if (au.enabled === false || au.interval_s === 0) return t("never");
  if (!isNum(au.interval_s) || au.interval_s < 0) return "–";
  if (INTERVAL_KEYS[au.interval_s]) return t(INTERVAL_KEYS[au.interval_s]);
  return t("au_every_n_h", { n: num(Math.max(1, Math.round(au.interval_s / 3600)), 0) });
}
function renderAutoUpdate(d) {
  const sec = document.getElementById("sec-autoupdate");
  const au = d.auto_update;
  sec.classList.toggle("hidden-sec", !d.available || !au);
  if (!d.available || !au) { fill("autoupdate-grid", []); return; }
  const en = au.enabled;
  const val = (label, ts) => metric(label, ts ? fmtDateTime(ts) : "–", ts ? fmtAgo(ts, d.now_ts || Math.floor(Date.now() / 1000)) : null, "small");
  const tiles = [
    metric(t("au_status"), en == null ? "–" : en ? t("on") : t("off"), null, en == null ? null : en ? "on" : "off"),
    metric(t("au_interval"), fmtInterval(au), null, "small"),
    val(t("au_last_auto"), au.last_ts), val(t("au_last_manual"), au.manual_last_ts),
  ];
  fill("autoupdate-grid", tiles);
}

function renderListUpdates(d) {
  const sec = document.getElementById("sec-listupd");
  const lu = d.list_updates;
  sec.classList.toggle("hidden-sec", !d.available || !lu || !lu.available);
  if (!d.available || !lu || !lu.available) { fill("listupd-grid", []); fill("listupd-recent", []); return; }
  const c = lu.counts || {};
  const cnt = (k, label) => {
    const x = c[k] || {};
    return metric(label, num((x.auto || 0) + (x.manual || 0)),
      t("lu_counts", { a: num(x.auto || 0), m: num(x.manual || 0) }));
  };
  fill("listupd-grid", [
    metric(t("lu_interval"), fmtInterval({ enabled: lu.auto_enabled, interval_s: lu.interval_s }), null, "small"),
    cnt("24h", t("lu_24h")), cnt("7d", t("lu_7d")), cnt("30d", t("lu_30d")),
  ]);
  const rec = lu.recent || [];
  const ul = h("ul", "listupd-list");
  if (!rec.length) ul.appendChild(h("li", null, t("lu_none")));
  rec.forEach((r) => {
    const li = h("li");
    li.appendChild(h("span", "lu-time", fmtDateTime(r.ts)));
    li.appendChild(h("span", "badge " + (r.kind === "manual" ? "mut" : "ok"), t(r.kind === "manual" ? "lu_manual" : "lu_auto")));
    ul.appendChild(li);
  });
  const notes = [];
  if (lu.next_expected_ts) notes.push(t("lu_next", { t: fmtDateTime(lu.next_expected_ts) }));
  if (lu.observed_since) notes.push(t("lu_since", { t: fmtDateTime(lu.observed_since) }));
  const nodes = [h("div", "metric-label", t("lu_recent")), ul];
  notes.forEach((n) => nodes.push(h("p", "card-note after", n)));
  fill("listupd-recent", nodes);
}

function renderChart() {
  const s = seriesStore[curSpan];
  document.getElementById("chart-title").textContent = t("title_" + curSpan);
  const note = document.getElementById("chart-note");
  note.textContent = s && s.partial && s.first_ts ? t("partial", { t: fmtDateTime(s.first_ts) }) : "";
  drawChart(document.getElementById("chart-ftrap"), s, curSpan);
}

function render(d) {
  lastData = d;
  if (!d || d.db_available === false) { setStatus("error", t("err_db")); renderBanners(d || {}, 0); return; }
  const nowSec = d.now_ts || Math.floor(Date.now() / 1000);
  document.getElementById("demo-note").classList.toggle("hidden-sec", !d.demo);
  renderBanners(d, nowSec);
  renderTiles(d);
  renderLists(d, nowSec);
  renderListUpdates(d);
  renderAutoUpdate(d);
  renderExceptions(d);
  renderChart();
  const c = d.collector || {};
  if (c.stale) setStatus("warn", `${t("data_stale")} · ${fmtAge(c.age_s)}`);
  else setStatus("ok", `${t("data_fresh")} · ${fmtAge(c.age_s)}`);
  document.getElementById("updated-at").textContent =
    `${t("stand")}: ${d.generated_at ? new Date(d.generated_at).toLocaleString(locale()) : t("updated_never")}`;
}

/* Demo mode: the static demo data is generated once, so all timestamps are shifted
   client-side by (now - exported_at) to make it always look fresh. Real data is untouched. */
function shiftTimes(o, delta) {
  if (Array.isArray(o)) { o.forEach((x) => shiftTimes(x, delta)); return; }
  if (!o || typeof o !== "object") return;
  for (const k of Object.keys(o)) {
    const v = o[k];
    if ((k === "ts" || k === "observed_since" || k.endsWith("_ts")) && isNum(v)) o[k] = v + delta;
    else if (v && typeof v === "object") shiftTimes(v, delta);
  }
}
function demoDelta(d) {
  return d && d.demo === true && isNum(d.exported_at) ? Math.floor(Date.now() / 1000) - d.exported_at : 0;
}

/* === Loading =========================================================== */
async function loadSeries(delta) {
  const map = { day: "series_day.json", week: "series_week.json", month: "series_month.json" };
  await Promise.all(Object.entries(map).map(async ([k, f]) => {
    try {
      const r = await fetch(`data/${f}?t=${Date.now()}`);
      if (r.ok) {
        seriesStore[k] = await r.json();
        if (delta) shiftTimes(seriesStore[k], delta);
      }
    } catch (e) { console.error("series", f, e); }
  }));
}
async function load() {
  try {
    const r = await fetch(`data/ftrap.json?t=${Date.now()}`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    const delta = demoDelta(data);
    if (delta) { shiftTimes(data, delta); data.generated_at = new Date().toISOString(); }
    await loadSeries(delta);
    render(data);
  } catch (e) {
    setStatus("error", t("err_fetch"));
    console.error("FTrap load:", e);
  }
}

/* === Init ============================================================ */
function setLang(lang) {
  if (!I18N[lang]) return;
  currentLang = lang;
  document.documentElement.dataset.lang = lang;
  setLS("ftrap_lang", lang);
  applyI18n();
  if (lastData) render(lastData);
}
function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  setLS("ftrap_theme", theme);
  updateThemeButton();
}
/* The label names the target theme (light active -> "Dark") */
function updateThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  document.getElementById("btn-theme").textContent = t(dark ? "theme_light" : "theme_dark");
}
function initToolbar() {
  document.getElementById("btn-lang-de").addEventListener("click", () => setLang("de"));
  document.getElementById("btn-lang-en").addEventListener("click", () => setLang("en"));
  document.getElementById("btn-theme").addEventListener("click", () => {
    setTheme((document.documentElement.dataset.theme || "light") === "light" ? "dark" : "light");
  });
  document.querySelectorAll("[data-span]").forEach((b) =>
    b.addEventListener("click", () => {
      curSpan = b.dataset.span; setLS("ftrap_span", curSpan);
      applyI18n(); renderChart();
    }));
  setTheme(document.documentElement.dataset.theme || "light");
  applyI18n();
}

let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (lastData) renderChart(); }, 200);
});

initToolbar();
load();
setInterval(load, POLL_MS);
