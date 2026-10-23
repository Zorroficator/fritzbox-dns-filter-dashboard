<img src="docs/banner.svg" alt="FTrap banner" width="100%">

# FTrap – FRITZ!Box-DNS-Filter-Dashboard

🇬🇧 [English](README.md) &nbsp;|&nbsp; 🇩🇪 Deutsch

[![Tests](https://github.com/Zorroficator/fritzbox-dns-filter-dashboard/actions/workflows/tests.yml/badge.svg)](https://github.com/Zorroficator/fritzbox-dns-filter-dashboard/actions/workflows/tests.yml)

Pi-hole-artige Statistik für den eingebauten DNS-Filter von FRITZ!OS 8.4x/8.50: ein kleiner Sammler, eine SQLite-Datenbank und ein statisches Web-Dashboard. Das Dashboard und sein Sammler arbeiten gegenüber der Box rein lesend. Ein optionaler Begleit-Sammler ergänzt ein Protokoll der einzelnen DNS-Anfragen (siehe [Optional: DNS-Abfrageprotokoll](#optional-dns-abfrageprotokoll)); dieser Begleiter startet einen Paketmitschnitt an der Box, das Dashboard selbst nicht.

> [!WARNING]
> **Beta-Schnittstelle.** Den DNS-Filter gibt es ab FRITZ!OS 8.50 (final seit 29.09.2026, zunächst für 7690/5690/5630, weitere Modelle folgen) sowie in Labor-Versionen von 8.4x. Entwickelt wurde mit FRITZ!OS 8.40 Labor (Build 136730), getestet ist mit **FRITZ!OS 8.50 (Build 136731)**; dort funktioniert derselbe Pfad (`/api/v0/beta/dnsfilter`). Die Schnittstelle bleibt undokumentierte Beta und kann sich mit jedem Firmware-Update ändern oder wegfallen. Das Projekt ist daher experimentell – mit Vorsicht zu genießen.

**🔴 [Live-Demo-Dashboard](https://zorroficator.github.io/fritzbox-dns-filter-dashboard/)** – statische Seite mit synthetischen Daten, kein Backend nötig.

> Nicht mit AVM verbunden. FRITZ! ist eine Marke des jeweiligen Inhabers (AVM / FRITZ! GmbH); der Name dient hier nur der Beschreibung der Kompatibilität.

## Verwandte Projekte

- **[FritzHole](https://github.com/Milinator/fritzhole-ha)** – Home-Assistant-App für denselben DNS-Filter. Sie liest über den Paketmitschnitt der Box jede einzelne DNS-Anfrage mit (pro Gerät und Domain) und kann den Filter auch verwalten (Allow-/Blocklist, Pause, Filterlisten). FritzHole passt, wenn du Home Assistant nutzt und Einzelanfragen oder die Filterverwaltung brauchst; FTrap, wenn du ein kleines eigenständiges Dashboard willst, das gegenüber der Box rein lesend arbeitet und den Paketmitschnitt nicht braucht. Der optionale DNS-Abschnitt kann ebenfalls Einzelabfragen zeigen, aber nur über einen separaten Begleit-Sammler, der den Paketmitschnitt der Box belegt.

## Architektur

```
FRITZ!Box ──► Sammler (alle 180 s) ──► SQLite ──► export.py (ca. alle 5 Min., cron / launchd / systemd-Timer)
                                                      │
                                                      ▼
                                     statische JSON  ──►  Browser (index.html, app.js)
```

- `collector/ftrap_collector.py` fragt die Box ab und schreibt Zähler und Filterlisten-Metadaten nach SQLite.
- `export.py` liest die Datenbank nur lesend und schreibt statische JSON-Dateien nach `data/`.
- `index.html` / `app.js` / `style.css` stellen daraus das Dashboard dar (DE/EN, hell/dunkel).

## Voraussetzungen

- Python >= 3.11, nur Standardbibliothek (nichts zu installieren).
- Eine FRITZ!Box mit FRITZ!OS 8.50 oder einer 8.4x-Laborversion, die den DNS-Filter anbietet.
- Ein FRITZ!Box-Benutzer mit dem Recht „FRITZ!Box Einstellungen“. FRITZ!OS kennt keine reine Leseberechtigung, dieses Recht **schließt Schreibrechte ein**. Lege einen eigenen Benutzer nur für FTrap an, schalte für ihn „Zugang aus dem Internet“ aus und behandle seine Zugangsdaten wie ein Admin-Passwort.

## Schnellstart

```sh
cp collector/config.example.toml collector/config.toml
# collector/config.toml bei Bedarf anpassen (box_url ist standardmäßig http://fritz.box)

# Zugangsdaten: Datei wird zuerst mit Rechten 600 angelegt, dann trägst du die Daten ein
mkdir -p ~/.config/ftrap && install -m 600 /dev/null ~/.config/ftrap/credentials && ${EDITOR:-nano} ~/.config/ftrap/credentials
# Format: Benutzername in Zeile 1, Passwort in Zeile 2 (oder „username: ...“ / „password: ...“)
# eine für Gruppe/Andere lesbare Datei wird abgelehnt (Exit 2), außer mit --allow-insecure-credentials
# ...oder per Umgebung: FTRAP_USER / FTRAP_PASSWORD

# einzelner Testlauf mit Debug-Ausgabe
python3 collector/ftrap_collector.py --config collector/config.toml --once -v

# Dauerbetrieb (als Dienst nach Wahl einrichten)
python3 collector/ftrap_collector.py --config collector/config.toml

# JSON-Dateien für das Dashboard schreiben (z. B. alle 5 Minuten planen)
python3 export.py
```

Die Datenbank liegt standardmäßig **außerhalb** des Repositorys unter `$XDG_DATA_HOME/ftrap/ftrap.db` (meist `~/.local/share/ftrap/ftrap.db`). `FTRAP_DB` hat Vorrang; ein relativer `db_path` in der Konfiguration wird relativ zur Repository-Wurzel aufgelöst.

### Dashboard ausliefern

Liefere **nur die Webdateien** aus – nie den Repository-Ordner selbst, sonst werden auch `.git/` und deine Konfiguration ausgeliefert. Kopiere sie in einen eigenen Webordner:

```sh
WEB=~/ftrap-web
mkdir -p "$WEB/data"
cp index.html app.js dns.js theme-init.js style.css fonts.css "$WEB/" && cp -r fonts "$WEB/"
python3 export.py --out "$WEB/data"        # regelmäßig planen, z. B. alle 5 Minuten

# nur für einen lokalen Blick:
python3 -m http.server 8080 --bind 127.0.0.1 --directory "$WEB"    # http://localhost:8080/
```

Ausgelieferte Dateien: `index.html`, `app.js`, `dns.js`, `theme-init.js`, `style.css`, `fonts.css`, `fonts/`, `data/*.json`. Startest du `http.server` stattdessen im Repository-Ordner, werden auch `.git/` und die Sammler-Konfiguration ausgeliefert.

## Optional: DNS-Abfrageprotokoll

Die Box liefert keine Werte pro Domain oder Gerät, deshalb zeigt das Kern-Dashboard nur Zähler. Für Top-Domains, Top-Geräte und ein Live-Abfrageprotokoll gibt es im Dashboard einen optionalen DNS-Abschnitt (`dns.js`, der Block `#dns` in `index.html`). Er bleibt **verborgen**, bis `data/dns_top.json` oder `data/dns_live.json` geladen werden kann; ohne diese Dateien ändert sich nichts.

Die Dateien schreibt ein separates Begleitprojekt, der DNS-Mitschnitt-Sammler: [fritzbox-dns-capture-collector](https://github.com/Zorroficator/fritzbox-dns-capture-collector). Er liest den DNS-Verkehr aus dem Paketmitschnitt der Box – ein anderer Mechanismus mit anderen Folgen als der Rest von FTrap:

- er belegt den Paketmitschnitt der Box (manuelle Mitschnitte in der Box-Oberfläche sind währenddessen gesperrt),
- er braucht einen eigenen FRITZ!Box-Benutzer mit dem Recht „FRITZ!Box Einstellungen“, praktisch also ein Admin-Recht (siehe Voraussetzungen oben).

Lass den Begleiter in dasselbe `data/`-Verzeichnis schreiben, das auch das Dashboard ausliefert (sein `out_dir`), oder kopiere die beiden Dateien dorthin. Der Sammler legt seine Dateien standardmäßig mit Modus 600 / 700 an; läuft der Webserver unter einem anderen Benutzer, meldet er „403 Forbidden“. Betreibe beide unter demselben Benutzer, setze im Abschnitt `[output]` des Sammlers `file_mode = 0o640` / `dir_mode = 0o750` plus eine gemeinsame Gruppe, oder kopiere nur `dns_*.json` (siehe „Webserver unter anderem Benutzer“ im README des Sammlers). Das JSON-Format steht in [`docs/dns_contract.md`](docs/dns_contract.md) (Kopie des Vertrags aus dem Begleit-Repository, englisch); `python3 demo/make_sample.py` schreibt passende Beispieldateien mit erfundenen Geräten und Domains, ein Test prüft sie gegen dieses Dokument.

> [!WARNING]
> **Datenschutz.** Das DNS-Protokoll zeigt, welches Gerät wann welche Domain angefragt hat – für **alle Geräte des Haushalts**. Es ist das Surfverhalten aller, die in deinem Netz wohnen oder zu Besuch sind. Informiere Mitbewohner und Gäste. Halte die Dateien im lokalen Netz und liefere sie nie über einen öffentlichen Webserver aus. Das Dashboard hat keine Anmeldung, schütze `data/dns_*.json` daher selbst (Dateirechte, Authentifizierung im Reverse-Proxy) und halte die Aufbewahrung kurz.

## Umgebungsvariablen

| Variable | Bedeutung |
|---|---|
| `FTRAP_DB` | SQLite-Pfad; überschreibt `db_path` der Konfiguration (Sammler) und ist Standard für `export.py` (sonst `$XDG_DATA_HOME/ftrap/ftrap.db` bzw. `~/.local/share/ftrap/ftrap.db`) |
| `FTRAP_TZ` | IANA-Zeitzone (z. B. `Europe/Berlin`) für die Tageswerte in `export.py`; Standard: lokale Zeit des Rechners |
| `FTRAP_USER` | FRITZ!Box-Benutzername (hat Vorrang vor der Zugangsdaten-Datei) |
| `FTRAP_PASSWORD` | FRITZ!Box-Passwort (hat Vorrang vor der Zugangsdaten-Datei) |

Sind die Zugangsdaten-Variablen gesetzt, kann `--config` entfallen.

## Was die API liefert

`GET /api/v0/beta/dnsfilter` mit dem Header `Authorization: AVM-SID <sid>`. Verwendete Felder:

- `enabled` – Filter an oder aus
- `statistics.dnsQueryCount.blocked` / `.total` – Zähler **seit dem letzten Neustart der Box**
- `filterlists[]` – je Liste `status` und `latestUpdate`
- `automaticUpdate`, `manualUpdate` – an/aus, Intervall und Zeitpunkte der letzten Aktualisierung; das Dashboard zeigt sie an (nur Anzeige, FTrap ändert nichts). Auf der getesteten Box bleibt `manualUpdate.lastTimestamp` auch nach einer manuellen Aktualisierung 0; manuelle Läufe werden daher aus `latestUpdate` der Listen übernommen (siehe unten)
- `clients`, `domains`, `profiles` – Konfigurationslisten (Ausnahmen, Profile); gespeichert wird nur die Anzahl der Einträge
- `domains[].action` (`allow` / `deny`) und `domains[].enabled` – werden nur genutzt, um erlaubte, gesperrte und deaktivierte Ausnahmen getrennt zu zählen; deaktivierte Einträge zählen weiterhin als allow/deny, unbekannte Aktionen zählen nur in der Gesamtzahl, ein fehlendes oder leeres (null) `enabled` gilt nicht als deaktiviert
- `statistics` – gespeichert werden nur die **Feldnamen** (`stats_keys`, nie Werte). Fügt die Box Statistikfelder hinzu oder lässt welche weg, zeigt das Dashboard einen Hinweis auf geänderte Struktur

### Filterlisten-Aktualisierung

Die Dashboard-Karte „Filterlisten-Aktualisierung“ zeigt automatische und manuelle Läufe, die Anzahl in 24 Stunden / 7 Tagen / 30 Tagen und den nächsten erwarteten automatischen Lauf. Da die Box `manualUpdate.lastTimestamp` nicht füllt, hält der Sammler jeden verschiedenen `latestUpdate.timestamp` je Liste in der Tabelle `dnsfilter_list_updates` fest (`uid`, `latest_ts`, `latest_cause`, `latest_status`, `last_success_ts`, `first_seen_ts`). Läufe mit der Ursache `manual` bilden die manuelle Historie. Diese Historie wird fest **90 Tage** aufbewahrt, unabhängig von `retention_days`; die jeweils neueste Zeile je Liste bleibt immer stehen.

## Erkenntnisse und Grenzen

- Die Box liefert **keine Werte pro Domain oder pro Gerät**, daher gibt es keine Top-Listen. Geprüfte Unterpfade wie `/statistics`, `/top` und `/log` antworten mit HTTP 400.
- Blockierte Domains werden mit `0.0.0.0` beantwortet.
- Es handelt sich um eine Beta-Schnittstelle: Der Pfad kann sich ändern. Die Box antwortet auch für unbekannte Pfade mit HTTP 400 „permission denied“, ein falscher Pfad sieht also wie ein Rechteproblem aus. Fehlercodes unter FRITZ!OS 8.50: **3001** = Sitzungskennung abgelaufen (der Sammler meldet sich einmal neu an und wiederholt die Abfrage), **3002** = „bad path“ (unbekannter Unterpfad, keine Neuanmeldung). Alternative Pfade lassen sich in `paths` der Konfiguration eintragen; sie werden der Reihe nach probiert, der erste Erfolg gilt.
- Zuwachs: Die Zähler sind Summen seit dem Neustart der Box. Der Zuwachs ist die Differenz zum vorherigen Messpunkt; springt ein Zähler zurück (Neustart), ist der Zuwachs der neue Wert selbst, da der Zähler bei 0 begann. Lücken werden nicht interpoliert.
- Die Box-Oberfläche rundet den Blockier-Anteil auf ganze Prozent auf; FTrap zeigt eine Nachkommastelle.

## Datenschutz

- Die Rohantwort der API wird nie gespeichert, protokolliert oder ausgegeben.
- Von `clients`, `domains` und `profiles` wird nur die Anzahl der Einträge behalten, nie der Inhalt.
- Das Passwort wird nie protokolliert.

## Sicherheit

Das Dashboard hat **keine Anmeldung**. Betreibe es nur im lokalen Netz oder hinter einem Reverse-Proxy mit Authentifizierung. Nicht ungeschützt ins Internet stellen.

- Der Sammler folgt nie HTTP-Weiterleitungen der Box, Passwort und Sitzungs-ID können also nicht an einen anderen Host gehen.
- `box_url` darf `https://…` sein. Zertifikate werden immer geprüft; für das selbstsignierte Zertifikat der Box `ca_file = "/pfad/zum/box-zertifikat.pem"` in der Konfiguration setzen. Die Prüfung lässt sich nicht abschalten.
- Fehlernotizen in der Datenbank (`poller_health.note`) enthalten nie die Box-URL.

### Content Security Policy

Die Seite braucht keine Inline-Skripte oder -Stile, daher funktioniert eine strenge Richtlinie. Beispiel für einen Reverse-Proxy:

```
Content-Security-Policy: default-src 'self'; style-src 'self'; font-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'
```

## Demo

```sh
python3 demo/make_sample.py              # schreibt synthetische Daten nach ./data
python3 demo/make_sample.py --out DIR    # oder in ein anderes Verzeichnis
```

Erzeugt 30 Tage erfundener Zähler inklusive eines simulierten Box-Neustarts, automatischer Listen-Aktualisierungen alle 8 Stunden und zwei manueller Läufe (füllt die Karte „Filterlisten-Aktualisierung“). `ftrap.json` ist mit `demo: true` markiert; in diesem Modus verschiebt die Seite alle Zeitstempel im Browser, damit die statische Demo nie veraltet wirkt. Außerdem entstehen `dns_top.json` und `dns_live.json` mit acht erfundenen Geräten und erfundenen Domains (`example.*`, `*.invalid`), sodass die Demo den optionalen DNS-Abschnitt zeigt. Der GitHub-Pages-Workflow baut die Live-Demo so.

## Tests

```sh
python3 -m unittest discover -s tests
python3 -m unittest discover -s collector/tests
```

Die Tests laufen bei jedem Push per GitHub Actions (Python 3.11–3.13).

## Lizenz

MIT – siehe [LICENSE](LICENSE). Die mitgelieferten Schriften stehen unter der SIL OFL, siehe `fonts/OFL.txt`.
