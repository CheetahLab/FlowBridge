<div align="center">

**English · [Deutsch](CHANGELOG.de.md)**

</div>

# Changelog

Every published version is listed here with what changed — and, where it is
worth saying, why.

Version numbers are `YEAR.MM.DD-COUNTER`, the counter running within a day.
Not every number has an image: a build happens only when something changes
that ends up inside the container. A documentation-only change would produce
an identical image and an update prompt that gains nobody anything.

The version your installation runs is shown in the top right of the interface.

---

## 2026.08.25-03

### Added

- **The changelog now lives in the app.** "What's new?" opens a window
  instead of a browser tab, and the version you are running is marked in it —
  the answer to "where in this list am I, actually?". Reachable in two places:
  in the header once an update is pending, and permanently under
  Settings › Updates.
- **Settings › Updates now shows the running version number.** Previously it
  said "Up-to-date" but not what of — the number was one view away.

The text is fetched when you open it rather than shipped inside the image.
There is no other way: a built-in changelog would be frozen at the state of
the installed version and could not answer the very question that prompts it —
what does the update I do not have yet contain. It is fetched from the browser
and only on a click, so it is the same connection a link would have opened.
Without a network the window states the reason and offers the link.

---

## 2026.08.25-02

### Changed

- **The header became a toolbar.** Log out was the last labelled button and
  therefore the only one breaking the row — it now carries an icon like its
  neighbours. All buttons are the same size and square, and moon and sun are
  drawings instead of emoji (some systems render those in colour, leaving a
  blob glowing in a row of grey strokes).
- **"Up-to-date" is a green checkmark.** That state is the absence of news; a
  symbol is enough for it. As soon as there is something to do, there is
  something to read again: when an update is available the version number
  stays, because that is the part you need.
- **Custom tooltips instead of the browser's.** The native one appears only
  after about a second and cannot be styled. On devices without a pointer it
  is dropped — there it could only be triggered by tapping, and that triggers
  the action at the same time.

### Fixed

- The screen reader labels of the language and theme buttons were hardcoded in
  German regardless of the selected language.

---

## 2026.08.25-01

### Fixed

- **After the reporting subscription was renewed, every message arrived
  twice.** Spotted at the first scheduled renewal after twelve hours: 799
  payloads arrived twice, each within the same millisecond. The cause was the
  order of the teardown steps — the network thread was stopped *before* the
  disconnect packet had been sent, so it never went out at all. The broker
  left the old session standing and merged it with the new one on reconnect,
  its subscription included. Displayed values were not wrong — the copies
  were identical — but another copy would have been added every twelve hours.

  Additionally hardened: the two paths that subscribe to a topic can no
  longer duplicate each other.

---

## 2026.08.24-21

### Added

- **Relicensed under the Apache License 2.0.** Use it, run it, adapt it,
  redistribute it, build it into your own software — freely, commercially and
  in closed products too, subject to the three conditions in section 4. In
  the smart home world, integration should not fail over a licence.
- **A section "What you don't see otherwise" in both READMEs.** A power
  station's converter costs more than the vendor app lets you see — measured
  on a RIVER 2 Pro, with the data points, the line fitted to them, and an
  explicit statement of where those numbers stop being valid.
- **Screenshots of the running interface** in light and dark, German and
  English.

### Changed

- **The interface was reviewed and tidied.** Tiles wrap cleanly, the device
  card gained a "Control" section heading and a tightened order, limits and
  reserve sit side by side in pairs, settings moved into four tabs instead of
  one long column, and the slider scale is labelled.
- **The history chart no longer scales with the window width.** On a wide
  screen text and lines were blown up along with it; the drawing now keeps
  its size and uses the space instead.
- **Content width follows the view** — the dashboard may be wider than the
  settings page without the header drifting out of alignment.
- **A reading counts as current for five minutes**, previously two. Two
  minutes was too strict for fields the device reports rarely anyway.
- **Setup explains itself better:** the test button sits with the EcoFlow
  credentials instead of with MQTT, the detected model is named, and a
  signpost points to the EcoFlow developer portal where the keys come from.
- **Efficiency above 100 % is no longer shown.** Where input and output were
  not measured at the same moment, a "–" appears instead of a number that
  only arises by coincidence.

---

## 2026.08.24-05

The version that put the core of the project straight.

### Added

- **Every reading carries its age.** Above the tiles it says how old the most
  recent measurement is; individual stale values are marked. The reason is
  uncomfortable but important: without an age, an unchanged value is
  ambiguous — it can mean "steady" or "dead for twelve minutes". For control
  logic reacting to it, that is the difference between correct and dangerous.
- **The history chart draws gaps instead of lines.** Values older than the
  threshold are no longer carried forward. A continuous line across a dead
  stretch looks like knowledge.
- **The reporting subscription is renewed on schedule.** EcoFlow configures
  the device's reporting rate when a client subscribes — and that
  configuration expires. Measured: after roughly 37 hours the interval
  between two reports went from a median of 3 seconds to 899. FlowBridge
  therefore resubscribes every twelve hours, and immediately whenever reports
  actually do break down.

### Fixed

- **`quota/all` was wrongly treated as a second measurement path.** It is a
  copy of the last push. If the push stops, the request keeps returning the
  same old numbers indefinitely — successfully, with HTTP 200, freshly
  timestamped on every call. A selective field request was measured as an
  alternative and rejected: zero differences across 40 rounds.

---

## 2026.08.17-04

Source and documentation only, no new image.

- Synology guide in both languages, as HTML and PDF in the repository.
- Two installation paths documented.

---

## 2026.08.16

First public release.

### Added

- Live values via MQTT push instead of polling.
- Control of AC output, 12 V output, X-Boost, charge limit, discharge limit,
  charge power and charge pause — from the interface or via MQTT.
- Home Assistant discovery, topic export for EisBär SCADA, field inventory
  and a diagnostics package with keys redacted.
- Interface and guides in German and English.
- Issue templates for bugs and new devices.

### Fixed

- **An AC command silently changed X-Boost, output voltage and frequency
  along with it.** Changing the charge power unintentionally changed three
  other settings.
- The image build updates the base image's Debian packages instead of
  carrying known vulnerabilities forward.
