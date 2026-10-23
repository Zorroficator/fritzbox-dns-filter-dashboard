# Output contract: `dns_live.json` and `dns_top.json`

`ftrap_dns.py` writes two JSON files into `out_dir` (default mode 600, configurable with `[output] file_mode`; replaced atomically):

| File | Updated | Content |
|---|---|---|
| `dns_live.json` | every 5 s | health and the last 200 DNS queries (newest first, `events` never has more than 200 entries) |
| `dns_top.json` | every 60 s | health, 24 h series, per-device series, top lists for today / 7 days / 30 days |

Consumers must ignore keys they do not know. Both files are UTF-8, one JSON document each.

## Conventions

- `generated` and `capture_since` (top file) are ISO 8601 strings with a UTC offset, in the configured `timezone` (local system zone if empty).
- All other timestamps (`ts`, `start`, `capture_since`/`connected_since`/`last_packet_ts` inside `health`) are Unix seconds (UTC), `null` when unknown.
- Counts are integers. `null` in a series bucket means "no data yet" (before the first capture), `0` means "captured, but nothing happened".
- The catch-all domain `"(other)"` collects queries once the daily limit of distinct new domains (`limits.domains_per_day`) is reached. Consumers should translate it for display.
- The catch-all device `"(other)"` (a `name` in `top_clients` / `top_clients_blocked`) collects the daily totals of devices beyond the daily limit of distinct devices (`limits.clients_per_day`). Consumers should translate it for display as well.
- Optional top-level fields `demo` (boolean `true`) and `exported_at` (Unix seconds) appear only in synthetic demo data, never in collector output. Front ends that see them shift all timestamps by `now - exported_at` so a static demo does not look stale.
- `name` is the device label: an `[aliases]` entry, else the host name from the box (only if `[hosts] enabled = true`), else the raw IPv4/IPv6 address or MAC address.

## `dns_live.json`

```json
{
  "generated": "2026-10-22T18:30:05+00:00",
  "health": {
    "connected": true,
    "last_error": "",
    "reconnects": 0,
    "host_errors": 0,
    "rate_limited": 0,
    "capture_since": 1790101200.0,
    "connected_since": 1790101200.0,
    "last_packet_ts": 1790101800.5
  },
  "events": [
    {
      "ts": 1790101800.5,
      "name": "laptop",
      "qname": "www.example.org",
      "qtype": "A",
      "status": "allowed",
      "latency_ms": 12.3,
      "reply": "ip"
    }
  ]
}
```

### Event fields

| Field | Meaning |
|---|---|
| `ts` | time of the query packet (box clock), Unix seconds |
| `name` | device label (see conventions) |
| `qname` | queried name, lower case, RFC 1035 escaping for unusual bytes |
| `qtype` | `A`, `AAAA`, `HTTPS`, ... or `TYPE<n>` |
| `status` | `allowed`, `blocked`, `nxdomain`, `error`, `no_answer` |
| `latency_ms` | query to reply time; `null` for `no_answer` |
| `reply` | `ip`, `cname`, `nxdomain`, `blocked`, `nodata`, `error`, `none` (no reply) |

`blocked` means the box answered with an unspecified address (`0.0.0.0`, `::`) or with a synthesized empty NOERROR answer (no answer records, no authority record, not truncated). `no_answer` means no reply within 10 s.

### Health fields

| Field | Meaning |
|---|---|
| `connected` | the capture stream is currently open |
| `last_error` | code of the last capture error, `""` if the last session ended normally (codes below) |
| `reconnects` | number of reconnects since process start |
| `host_errors` | failed host list fetches since start |
| `rate_limited` | queries counted but not stored because a device exceeded `limits.client_per_min` or the total exceeded `limits.events_per_min` |
| `capture_since` | start of the capture: the oldest recorded connect within the retention window (`retention.daily_days`), so it survives restarts; the first connect of this process if there is no older one, `null` before the first connect |
| `connected_since` | start of the current connection, `null` if not connected |
| `last_packet_ts` | wall-clock time of the last captured packet |

### `last_error` codes

| Code | Meaning |
|---|---|
| `auth_failed` | the box rejected the user name or password |
| `login_failed` | login did not succeed for another reason (box unreachable, bad answer) |
| `credentials_error` | credentials file/env/stdin missing, unreadable or insecure |
| `tls_error` | certificate pin or CA check failed |
| `connect_failed` | the capture request could not be sent or the connection broke while starting |
| `http_error` | the capture endpoint answered with a status other than 200 |
| `capture_busy` | the stream was empty, usually because another packet capture is running on the box |
| `stream_truncated` | the stream ended before the pcap header |
| `not_pcap` | the answer was not a pcap stream (login or error page) |
| `idle_timeout` | no data for `capture.idle_timeout_s` seconds |
| `read_error` | the stream broke while reading |
| `pcap_error` | the pcap stream was out of sync |
| `page_error` | a helper page could not be fetched |
| `internal_error` | unexpected error (see the process log for the exception type) |
| `capture_failed` | other capture failure |

## `dns_top.json`

Shape example (lists are shortened; real files have 144 buckets and up to 10 entries per top list):

```json
{
  "generated": "2026-10-22T18:30:00+00:00",
  "capture_since": "2026-10-22T08:00:00+00:00",
  "health": {
    "connected": true,
    "last_error": "",
    "reconnects": 0,
    "host_errors": 0,
    "rate_limited": 0,
    "capture_since": 1790150400.0,
    "connected_since": 1790150400.0,
    "last_packet_ts": 1790101800.5
  },
  "series_24h": {
    "start": 1790015400,
    "step": 600,
    "buckets": [
      {"ts": 1790015400, "allowed": 10, "blocked": 2, "nxdomain": 1, "no_answer": 0}
    ]
  },
  "clients_24h": {
    "start": 1790015400,
    "step": 600,
    "clients": [
      {"name": "laptop", "total": 120, "blocked": 12, "series": [0, 3], "blocked_series": [0, 1]}
    ],
    "rest": {"total": 0, "blocked": 0, "series": [0, 0], "blocked_series": [0, 0]}
  },
  "periods": {
    "today": {
      "total": 250,
      "blocked": 125,
      "active_clients": 1,
      "top_permitted": [{"qname": "www.example.org", "n": 100}],
      "top_blocked": [{"qname": "ads.example", "n": 90}],
      "top_clients": [{"name": "laptop", "n": 250, "blocked": 125}],
      "top_clients_blocked": [{"name": "laptop", "n": 125, "total": 250}],
      "qtypes": [{"qtype": "A", "n": 250, "pct": 100.0}],
      "statuses": {"allowed": 125, "blocked": 125}
    },
    "7d": {},
    "30d": {}
  }
}
```

`periods.7d` and `periods.30d` have the same fields as `periods.today` (shown empty above for brevity).

### Field meanings

| Field | Meaning |
|---|---|
| `series_24h.buckets` | 144 buckets of `step` = 600 s, aligned to multiples of 600 s since the epoch, oldest first; `allowed` = all answered/unanswered queries that were not blocked |
| `clients_24h.clients` | up to 6 busiest devices of the last 24 h; `series` and `blocked_series` have one entry per bucket |
| `clients_24h.rest` | sum of all other devices |
| `periods.<p>.total` / `blocked` | queries in the period (calendar days in the configured zone; `today` = 1 day, `7d` = 7 days, `30d` = 30 days) |
| `active_clients` | devices seen in the period |
| `top_permitted` / `top_blocked` | most queried non-blocked / blocked domains |
| `top_clients` | busiest devices; `blocked` = their blocked queries |
| `top_clients_blocked` | devices with most blocked queries; `total` = all their queries |
| `qtypes` | query types with share in percent |
| `statuses` | count per `status` value |

## Untrusted strings

`qname`, `name` (including `[aliases]` labels and host names reported by the box) and any other string derived from the network are chosen by devices in your LAN and must be treated as untrusted input:

- Escape them for the target context (HTML, shell, SQL, log lines) before use; prefer `textContent` over `innerHTML`.
- They can contain any Unicode, including bidirectional control characters and look-alike characters.
- The RFC 1035 escaping of `qname` only covers non-printable bytes. Characters such as `<`, `>`, `"`, `'` and `&` are passed through unchanged.

## Personal data

These fields describe the browsing behavior of people in the household:

- `qname` (every event and every top list)
- `name` (events, `clients_24h.clients`, `top_clients`, `top_clients_blocked`): an alias or host name chosen by you, or a raw IP/MAC address
- the combination of `name`, `qname` and `ts` in `dns_live.json`

Serve these files only inside your LAN, never from a public web server, and restrict access (see README).
`health`, `generated` and the numeric series carry no personal data.
