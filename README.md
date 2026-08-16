<p align="center">
  <img src="assets/social/flowbridge-readme-banner.png" alt="FlowBridge" width="820">
</p>

<p align="center">
  <strong>MQTT bridge for portable power stations by EcoFlow.</strong><br>
  <em>MQTT-Brücke für mobile Energiespeicher von EcoFlow.</em>
</p>

<p align="center">
  <strong>English</strong> · <a href="README.de.md">Deutsch</a>
</p>

<p align="center">
  <a href="https://hub.docker.com/r/cheetahlab/flowbridge"><img src="https://img.shields.io/docker/pulls/cheetahlab/flowbridge?label=Docker%20Hub&color=0A6BFF" alt="Docker Hub"></a>
  <a href="https://hub.docker.com/r/cheetahlab/flowbridge/tags"><img src="https://img.shields.io/docker/v/cheetahlab/flowbridge?sort=date&label=Version&color=0A6BFF" alt="Version"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-0A6BFF" alt="License: AGPL-3.0"></a>
</p>

---

FlowBridge reads your EcoFlow power station through the official
[EcoFlow IoT Open Platform](https://developer-eu.ecoflow.com/) and mirrors it
onto **your own MQTT broker** — Mosquitto, Home Assistant, EisBär SCADA,
whatever you run. Plus a web dashboard with live readings and control.

**Your data stays in the house.** FlowBridge talks to the EcoFlow cloud and to
your broker. To nobody else — except the update check, which fetches a public
list of versions and can be switched off.

> The interface is bilingual (English and German) and this README exists in
> both languages. The in-depth guides in `docs/` and the source comments are
> German only.

## Quick start

The image is on **Docker Hub** and can be pulled directly:

```bash
docker pull cheetahlab/flowbridge:latest
```

Or straight away as a `compose.yaml`:

```yaml
services:
  flowbridge:
    image: cheetahlab/flowbridge:latest
    container_name: flowbridge
    restart: unless-stopped
    ports:
      - "8081:8080"
    environment:
      FLOWBRIDGE_CONFIG: /config/config.yaml
      TZ: Europe/Berlin
      FLOWBRIDGE_PASSWORD: "a-good-password"
    volumes:
      - ./data:/config
```

```bash
docker compose up -d
```

Then open `http://<host>:8081` — the setup dialog takes care of the rest. You
need an **access key and a secret key** from the EcoFlow developer portal;
those are not your app credentials, they are generated there specifically.

`FLOWBRIDGE_PASSWORD` protects the interface from the very first start.
FlowBridge can switch outputs — without a password anyone on the same network
could. The line may go once it has run; the password is then stored hashed in
the data folder.

> **Synology:** there is a detailed step-by-step guide —
> [`docs/inbetriebnahme-synology.html`](docs/inbetriebnahme-synology.html)
> (German). GitHub only shows HTML files as source, so download the file and
> open it in a browser.
> In Container Manager, the registry search finds `cheetahlab/flowbridge`
> directly.

## Supported devices

| Model | State |
|---|---|
| **RIVER 2 Pro** | verified against real hardware |
| **DELTA 2** | prepared from documentation, never run on a device |

Other models will show their readings but may not accept commands. The
diagnostics report says so explicitly (`documented` instead of `verified`)
rather than glossing over it.

## What it does

- **Live readings over MQTT push** instead of polling — seconds, not minutes
- **Control**: AC output, 12 V output, X-Boost, charge limit, discharge limit,
  charging power, charge pause — through the interface or over MQTT, both
  through the same code
- **Home Assistant discovery** — devices appear on their own
- **Topic export for EisBär SCADA** (channel CSV + payload profile XML)
- **Field inventory**: records over months which fields your device actually
  delivers — this is what makes visible when a firmware quietly adds or drops one
- **Diagnostics package**: report, masked configuration, topics and log in one
  ZIP — keys redacted, serial numbers replaced by placeholders
- **Interface in English and German**, light and dark, persistently configurable

## How it fits together

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/topology/flowbridge-topology-dark.png">
    <img src="assets/topology/flowbridge-topology-light.png" alt="Topology: EcoFlow cloud → FlowBridge → local broker" width="760">
  </picture>
</p>

## What the device will not give you

Honesty belongs in the picture: some things the official interface simply does
not provide, and FlowBridge does not pretend the fault is its own.

- **Battery temperature and charge cycles** are not delivered by the EcoFlow
  IoT Open Platform — neither over REST nor over the push channel. Confirmed
  across a full charge cycle (eight hours, not a single new field). *The device
  knows these values; the official interface just does not pass them on* — an
  old payload set from the unofficial app protocol did contain them.
- **Setpoints that have been written** cannot be read back on the River 2 Pro.
  FlowBridge therefore remembers what it last set.
- **The backup reserve** is not accepted by the River 2 Pro over the open
  interface (measured on the device). It is therefore only displayed, not
  operated.
- **EcoFlow reports success even when** the device silently discards a command.
  A green result is not proof — only a visible effect is.

Details in [`docs/quota-fields-river2.md`](docs/quota-fields-river2.md) (German).

## Documentation

| | |
|---|---|
| [Commissioning on a Synology](docs/inbetriebnahme-synology.html) | step by step (German, HTML — download and open in a browser) |
| [MQTT topics](docs/mqtt-topics.md) | complete topic list (German) |
| [Field comparison River 2 Pro](docs/quota-fields-river2.md) | what the interface delivers — and what it does not (German) |

This repository is a **mirror**, not a working directory: every published
version stands here as one commit, the actual development happens elsewhere.
What changed between two versions is therefore shown by comparing two commits —
the number for it is in [`VERSION`](VERSION) and, as an immutable tag, on the
matching image on Docker Hub.

## Local development

### Where things live

| | |
|---|---|
| `src/app.py` | FastAPI: endpoints, supervisor loop, state, serves the built frontend |
| `src/ecoflow_client.py` | REST client (HMAC-SHA256 signing, certificate and quota retrieval) |
| `src/ecoflow_mqtt.py` | push channel of the EcoFlow cloud |
| `src/mqtt_bridge.py` | publish to the local broker + subscribe to commands |
| `src/device.py` | normalisation of the quota fields — missing fields are left out, not invented |
| `src/commands_*.py` | commands per model; what a device does not accept is marked `NUR_LESBAR` there |
| `src/diagnostics.py` | log, redaction, diagnostics package |
| `src/inventar.py` | field inventory |
| `src/exporters.py`, `src/ha_discovery.py` | EisBär export, Home Assistant discovery |
| `frontend/` | React + Vite + TypeScript |
| `tests/` | 341 tests, `pytest` |

```bash
pip install -r requirements.txt
cd src && uvicorn app:app --reload --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

### Enable the version hook (once per clone)

```bash
git config core.hooksPath scripts/githooks
```

The `pre-commit` hook writes the version number to `VERSION` and puts it into
the same commit. Scheme `YEAR.MONTH.DAY-COUNTER` (e.g. `2026.08.13-02`), the
counter being how many commits that day. Without the hook enabled the number
stays put and the interface reports an outdated version.

Before that, the hook runs every script in `scripts/pre-commit.d/`, if that
folder exists — intended for your own additional steps. It is not needed for
building or contributing; if it is absent, the step is skipped.

## Access protection

FlowBridge is protected by **one password** (no user accounts — it is a device
on your own network, not a multi-user service). On first start the interface
requires you to set one; as long as none is set, the HTTP interface delivers
**no data at all**.

In the container the password can be set on the very first start:

```yaml
environment:
  - FLOWBRIDGE_PASSWORD=your-password
```

This removes the window in which FlowBridge is running but no password has been
set yet. An existing password is **not** overwritten by it.

Forgotten it? Delete the `auth` block from `config.yaml` and restart.

**Important:** FlowBridge speaks HTTP. On your own LAN that is acceptable; over
the internet it belongs behind a reverse proxy with TLS — otherwise the
password travels in the clear.

This does **not** protect the MQTT side: whoever may write to your broker may
also send commands. That is a matter of broker permissions (Mosquitto ACL), and
that is where it belongs.

## Diagnostics

If something does not work, the **diagnostics package** in the settings
provides everything needed for remote analysis: version, masked configuration,
the state of all three connections, field count per device and the log — as a
single ZIP file to send.

The order matters: *switch logging on → reproduce the fault → download the
package*.

The most recent lines are **always** kept in memory, even with logging switched
off. Otherwise the switch would not help: whoever sees the fault switches on
afterwards — and then it does not come back for an hour.

The log file sits next to `config.yaml` (inside the container therefore at
`/config/flowbridge.log`), capped at 5 × 5 MB with rotation.

Rotation is by **size**, not by time. At the measured write rate it reaches
back about **three to four days**; guaranteed are the four full files (~85 h),
because right after a rotation the newest file is empty. Older states are
deleted silently — an event from the week before last is no longer in there.

**Keys, passwords and signatures are redacted** before anything is written —
already in the file on disk, not only when packing. That is not incidental:
this file travels through the internet by e-mail, and with the EcoFlow keys the
recipient would have control over the power station.

**Serial number and EcoFlow account identifier appear as `<GERAET-1>` and
`<KONTO>`**, not in the clear. The package remains analysable regardless: which
model is behind which placeholder is included as a separate mapping — that is
the detail needed for analysis, and it identifies no device.

## Field inventory

A second, independent record — not for troubleshooting but for long-term
observation: **which fields does EcoFlow actually deliver?**

The occasion was a comparison on 13.08.2026: of 168 fields in an old payload
set, 27 still arrive over the official interface. Such shifts happen quietly —
EcoFlow rolls out firmware, and the data stream gets wider or narrower.

The trick: this does not need the data stream, it needs an inventory. Per field
only *first seen*, *last seen*, *count*, *value range* — that is a few
kilobytes, permanently. The file only grows when a **new** field appears; the
first raw message is then recorded alongside.

- New field → `zuerst` carries today's date
- Field gone → `zuletzt` stays put and ages

**Both** channels are recorded with a note of origin (`push` / `rest`). That is
not cosmetic: the MQTT push demonstrably delivers more fields than `quota/all`
(29 against 20, measured on 13.08.2026).

Switched on in the settings, stored as `feldinventar.json` next to
`config.yaml` — so it survives restarts and container updates.

**Not redacted**, unlike the diagnostics package: what is in here are field
names and readings, no credentials.

## Building it yourself

```bash
docker compose -f docker/flowbridge/compose.build.yaml up -d --build
```

Builds the image from this directory without touching a registry. For the
version number inside the image the version hook must be active (see above) —
otherwise the interface will report an outdated build.

## Configuration

See `src/config.example.yaml` for reference. `config.yaml` is normally produced
exclusively through the setup UI and is gitignored.

## License

**GNU AGPL v3** — see [`LICENSE`](LICENSE), copyright notice and exceptions in
[`NOTICE.md`](NOTICE.md).

Using it, running it and adapting it for yourself: free and without conditions.
Anyone who **distributes a modified version or operates it as a service** must
make the modified source available under the same license — even if they never
hand out the software itself. That is the difference between the AGPL and the
ordinary GPL, and for a web interface like this one the decisive difference.

There is no second license, not even for payment — the AGPL applies equally to
everyone, commercial or private. Which conversely means: contributions come in
under the same license, and nobody has to sign over any rights for them (see
[`NOTICE.md`](NOTICE.md)).

The libraries used are all permissively licensed (MIT, BSD-3, Apache-2.0, PSF)
— which is what made the choice possible in the first place: permissive
licenses impose no condition on the license of the whole work. `paho-mqtt` is
dual-licensed and is used here under BSD-3-Clause, `certifi` is under MPL-2.0
(file-level copyleft) and is shipped unmodified. The complete list with
versions is in [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md) and is to be
updated whenever `requirements.txt` or `frontend/package.json` changes.

**Name and logo** are not covered by the license. A derivative is welcome but
should be called something else — otherwise two different programs carry the
same name.

FlowBridge is an independent project and is not affiliated with EcoFlow. Use of
the EcoFlow IoT Open Platform is subject to their own terms; the license of
this project does not change that.
