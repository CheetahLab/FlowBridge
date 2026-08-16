# Fremdbestandteile / Third-Party Notices

FlowBridge selbst steht unter der **GNU AGPL v3** (siehe [`LICENSE`](LICENSE),
Urhebervermerk in [`NOTICE.md`](NOTICE.md)). Das ausgelieferte Docker-Abbild
enthält daneben Software Dritter unter eigenen Lizenzen. Diese Datei listet
sie auf — MIT und BSD verlangen beide, dass ihre Vermerke mit der Weitergabe
mitgehen.

Dass die Fremdbestandteile durchweg **permissiv** lizenziert sind, ist der
Grund, warum FlowBridge seine eigene Lizenz frei wählen konnte: Permissive
Lizenzen stellen keine Bedingung an das Gesamtwerk. Eine einzige
GPL-Abhängigkeit hätte die Wahl vorweggenommen — deshalb lohnt der Blick in
diese Tabelle, bevor eine neue Abhängigkeit hinzukommt.

Erhoben am 13.08.2026 aus dem tatsächlichen Abbild (`python:3.14.6-slim` +
`requirements.txt`), nicht aus dem Gedächtnis.

## Python — Laufzeit im Container

| Paket | Version | Lizenz |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.14.2 | MIT |
| certifi | 2026.7.22 | **MPL-2.0** |
| click | 8.4.2 | BSD-3-Clause |
| fastapi | 0.139.0 | MIT |
| h11 | 0.16.0 | MIT |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.8.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| idna | 3.18 | BSD-3-Clause |
| paho-mqtt | 2.1.0 | **EPL-2.0 ODER BSD-3-Clause** — hier unter BSD-3-Clause genutzt |
| pydantic | 2.13.4 | MIT |
| pydantic-core | 2.46.4 | MIT |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| PyYAML | 6.0.3 | MIT |
| starlette | 1.6.0 | BSD-3-Clause |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.38.0 | BSD-3-Clause |
| uvloop | 0.22.1 | MIT / Apache-2.0 |
| watchfiles | 1.2.0 | MIT |
| websockets | 17.0.1 | BSD-3-Clause |

Dazu die Standardbibliothek von **CPython 3.14** (PSF-2.0) und die
Debian-Basis des Abbilds mit ihren eigenen Paketlizenzen.

## JavaScript — im Frontend-Bundle enthalten

| Paket | Lizenz |
|---|---|
| react | MIT |
| react-dom | MIT |

## JavaScript — nur beim Bauen, nicht im Abbild

| Paket | Lizenz |
|---|---|
| vite | MIT |
| @vitejs/plugin-react | MIT |
| @types/node, @types/react, @types/react-dom | MIT |
| typescript | Apache-2.0 |
| oxlint | MIT |

## Zwei Fußnoten

**certifi (MPL-2.0)** ist ein schwaches Copyleft auf *Dateiebene*: Wer die
Dateien von certifi verändert und weitergibt, muss diese Dateien unter MPL-2.0
weitergeben. FlowBridge liefert certifi unverändert mit — auf den eigenen Code
wirkt sich das nicht aus.

**paho-mqtt** ist doppelt lizenziert; man darf wählen. FlowBridge nutzt es
unter **BSD-3-Clause**. Damit entstehen keine Pflichten aus der EPL-2.0.

Nichts davon steht unter GPL oder AGPL. Es gibt keine Copyleft-Pflicht, die
auf FlowBridge selbst durchschlägt.

## Aktualisieren

```bash
docker run --rm python:3.14.6-slim sh -c "pip install -q -r - < requirements.txt && pip install -q pip-licenses && pip-licenses --format=markdown"
```

Diese Liste gehört bei jeder Änderung an `requirements.txt` oder
`frontend/package.json` nachgezogen.
