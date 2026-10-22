<img src="docs/banner.svg" alt="FTrap banner" width="100%">

# FTrap – FRITZ!Box DNS filter dashboard

🇬🇧 English &nbsp;|&nbsp; 🇩🇪 [Deutsch](README_DE.md)

[![Tests](https://github.com/Zorroficator/fritzbox-dns-filter-dashboard/actions/workflows/tests.yml/badge.svg)](https://github.com/Zorroficator/fritzbox-dns-filter-dashboard/actions/workflows/tests.yml)

Pi-hole-style statistics for the built-in DNS filter of FRITZ!OS 8.4x/8.50: a small collector, a SQLite database and a static web dashboard. All requests to the box are read-only.

> [!WARNING]
> **Beta API.** The DNS filter is available from FRITZ!OS 8.50 (final since 29 Sep 2026, initially for the 7690/5690/5630, more models to follow) and in lab releases of 8.4x. This project was developed with FRITZ!OS 8.40 lab (build 136730) and is tested with **FRITZ!OS 8.50 (build 136731)**, where the same path (`/api/v0/beta/dnsfilter`) works. The API stays undocumented beta and may change or disappear with any firmware update. Treat this project as experimental and use it with caution.

**🔴 [Live demo dashboard](https://zorroficator.github.io/fritzbox-dns-filter-dashboard/)** – static page with synthetic data, no backend required.

> Not affiliated with AVM. FRITZ! is a trademark of its respective owner (AVM / FRITZ! GmbH); the name is used here only to describe compatibility.

## Related projects

- **[FritzHole](https://github.com/Milinator/fritzhole-ha)** – Home Assistant app for the same DNS filter. It reads every single DNS query via the box's packet capture (per device and per domain) and can also manage the filter (allow/block lists, pause, filter lists). Choose FritzHole if you run Home Assistant and want per-query detail or filter management; choose FTrap if you want a small standalone, strictly read-only tool that does not occupy the packet capture.

## Architecture

```
FRITZ!Box ──► collector (every 180 s) ──► SQLite ──► export.py (every ~5 min, cron / launchd / systemd timer)
                                                         │
                                                         ▼
                                       static JSON  ──►  browser (index.html, app.js)
```

- `collector/ftrap_collector.py` polls the box and writes counters and filter list metadata to SQLite.
- `export.py` reads the database read-only and writes static JSON files to `data/`.
- `index.html` / `app.js` / `style.css` render the dashboard from those JSON files (DE/EN, light/dark).

## Requirements

- Python >= 3.11, standard library only (no packages to install).
- A FRITZ!Box with FRITZ!OS 8.50 or a 8.4x lab release that offers the DNS filter.
- A FRITZ!Box user with the right "FRITZ!Box Settings". FRITZ!OS has no read-only permission, so this right **includes write access**. Create a dedicated user for FTrap only, disable "Access from the Internet" for it and treat its credentials like an admin password.

## Quick start

```sh
cp collector/config.example.toml collector/config.toml
# edit collector/config.toml if needed (box_url defaults to http://fritz.box)

# credentials: the file is created with mode 600 first, then you type the secrets into it
mkdir -p ~/.config/ftrap && install -m 600 /dev/null ~/.config/ftrap/credentials && ${EDITOR:-nano} ~/.config/ftrap/credentials
# format: user name on line 1, password on line 2 (or "username: ..." / "password: ...")
# a file readable by group/others is refused (exit 2) unless --allow-insecure-credentials is given
# ...or use the environment: FTRAP_USER / FTRAP_PASSWORD

# single test run with debug output
python3 collector/ftrap_collector.py --config collector/config.toml --once -v

# continuous operation (run as a service of your choice)
python3 collector/ftrap_collector.py --config collector/config.toml

# write the JSON files for the dashboard (schedule e.g. every 5 minutes)
python3 export.py
```

By default the database lives **outside** the repository at `$XDG_DATA_HOME/ftrap/ftrap.db` (usually `~/.local/share/ftrap/ftrap.db`). `FTRAP_DB` takes precedence; a relative `db_path` in the config is resolved relative to the repository root.

### Serving the dashboard

Serve **only the web files** – never the repository folder itself, otherwise `.git/` and your configuration would be served too. Copy them to a separate web folder:

```sh
WEB=~/ftrap-web
mkdir -p "$WEB/data"
cp index.html app.js theme-init.js style.css fonts.css "$WEB/" && cp -r fonts "$WEB/"
python3 export.py --out "$WEB/data"        # schedule this, e.g. every 5 minutes

# local look only:
python3 -m http.server 8080 --bind 127.0.0.1 --directory "$WEB"    # http://localhost:8080/
```

Served files: `index.html`, `app.js`, `theme-init.js`, `style.css`, `fonts.css`, `fonts/`, `data/*.json`. If you start `http.server` inside the repository folder instead, `.git/` and the collector configuration are served as well.

## Environment variables

| Variable | Meaning |
|---|---|
| `FTRAP_DB` | SQLite path; overrides `db_path` of the config (collector) and is the default for `export.py` (otherwise `$XDG_DATA_HOME/ftrap/ftrap.db` or `~/.local/share/ftrap/ftrap.db`) |
| `FTRAP_TZ` | IANA time zone (e.g. `Europe/Berlin`) for the daily buckets in `export.py`; default: host local time |
| `FTRAP_USER` | FRITZ!Box user name (takes precedence over the credentials file) |
| `FTRAP_PASSWORD` | FRITZ!Box password (takes precedence over the credentials file) |

With the credentials variables set, `--config` may be omitted.

## What the API provides

`GET /api/v0/beta/dnsfilter` with the header `Authorization: AVM-SID <sid>`. Fields used:

- `enabled` – filter switched on or off
- `statistics.dnsQueryCount.blocked` / `.total` – counters **since the last box restart**
- `filterlists[]` – per list `status` and `latestUpdate`
- `automaticUpdate`, `manualUpdate` – on/off, interval and last update times; the dashboard shows them (display only, FTrap does not change them). On the tested box `manualUpdate.lastTimestamp` stays 0 even after a manual update, so manual runs are taken from `latestUpdate` of the lists instead (see below)
- `clients`, `domains`, `profiles` – configuration lists (exceptions, profiles); only the number of entries is stored
- `domains[].action` (`allow` / `deny`) and `domains[].enabled` – used only to count allow, deny and disabled exceptions separately; disabled entries are still counted as allow/deny, unknown actions count only in the total, a missing or null `enabled` does not count as disabled
- `statistics` – only the **field names** are stored (`stats_keys`, never values). If the box adds or drops statistics fields, the dashboard shows a structure-change notice

### Filter list updates

The dashboard card "Filter list updates" shows automatic and manual runs, the counts for 24 h / 7 days / 30 days and the next expected automatic run. Because the box does not fill `manualUpdate.lastTimestamp`, the collector records every distinct `latestUpdate.timestamp` per list in the table `dnsfilter_list_updates` (`uid`, `latest_ts`, `latest_cause`, `latest_status`, `last_success_ts`, `first_seen_ts`). Runs with cause `manual` form the manual history. This history is kept for a fixed **90 days**, independent of `retention_days`; the newest row per list always stays.

## Findings and limits

- The box delivers **no values per domain or per device**, so there are no top lists. Probed sub-paths such as `/statistics`, `/top` and `/log` answer HTTP 400.
- Blocked domains are answered with `0.0.0.0`.
- This is a beta API: the path may change. The box also answers unknown paths with HTTP 400 "permission denied", so a wrong path looks like a permission problem. Error codes seen on FRITZ!OS 8.50: **3001** = session ID expired (the collector logs in again once and retries), **3002** = "bad path" (unknown sub-path, no re-login). Alternative paths can be listed in `paths` of the config; they are tried in order, the first success wins.
- Increments: the counters are totals since box restart. The delta is the difference to the previous snapshot; if a counter drops (restart), the delta is the new value itself, because the counter started at 0. Gaps are not interpolated.
- The box UI rounds the blocked percentage up to whole percent; FTrap shows one decimal.

## Privacy

- The raw API response is never stored, logged or printed.
- Of `clients`, `domains` and `profiles` only the number of entries is kept, never their content.
- The password is never logged.

## Security

The dashboard has **no login**. Run it only in your local network, or behind a reverse proxy that enforces authentication. Do not expose it to the internet as is.

- The collector never follows HTTP redirects from the box, so the password and session ID cannot be sent to another host.
- `box_url` may be `https://…`. Certificates are always verified; for the box's self-signed certificate set `ca_file = "/path/to/box-cert.pem"` in the config. Verification cannot be disabled.
- Error notes stored in the database (`poller_health.note`) never contain the box URL.

### Content Security Policy

The page uses no inline scripts or styles, so a strict policy works. Example for a reverse proxy:

```
Content-Security-Policy: default-src 'self'; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'
```

## Demo

```sh
python3 demo/make_sample.py              # writes synthetic data to ./data
python3 demo/make_sample.py --out DIR    # or to another directory
```

It generates 30 days of fake counters including one simulated box restart, automatic list updates every 8 hours and two manual runs (filling the "Filter list updates" card). `ftrap.json` is marked `demo: true`; in this mode the page shifts all timestamps client-side so the static demo never looks stale. The GitHub Pages workflow builds the live demo this way.

## Tests

```sh
python3 -m unittest discover -s tests
python3 -m unittest discover -s collector/tests
```

The tests run on every push via GitHub Actions (Python 3.11–3.13).

## License

MIT – see [LICENSE](LICENSE). The bundled fonts are licensed under the SIL OFL, see `fonts/OFL.txt`.
