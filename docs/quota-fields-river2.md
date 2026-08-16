# Quota-Feldabgleich: River 2 / River 2 Pro (verifiziert 12.08.2026)

Ergebnis eines echten `quota/all`-Aufrufs gegen ein River-2-Gerät (SN-Präfix
`R621`) via `scripts/test_quota.py` — **und** gegenkontrolliert mit der
offiziellen EcoFlow-Dev-Portal-Doku (`GetAllQuotaResponse`, River 2 Pro).
Beide stimmen exakt überein. Werte in der Live-Ausgabe sind ein Snapshot,
relevant sind nur die **Feldnamen**.

`quota/all` liefert für dieses Gerät genau diese 20 Felder — laut offizieller
Doku ist das die vollständige Liste, nicht nur ein Ausschnitt. **Keine
Batterietemperatur und keine Ladezyklen enthalten.**

Der MQTT-Live-Push (`/open/.../quota`, seit 12.08.2026 in
`src/ecoflow_mqtt.py` implementiert) ist **nicht nur schneller, sondern auch
reicher: 29 Felder gegenüber 20.** Neun kommen ausschließlich über MQTT
(Aufstellung weiter unten). Batterietemperatur und Ladezyklen sind auch dort
nicht dabei.

> Hier stand bis 14.08.2026 „er schickt dieselben Felder, nur schneller" —
> im Widerspruch zur Feldliste weiter unten, die 29 gegen 20 schon korrekt
> auswies. Wer nur die Einleitung las, hielt den Push für eine reine
> Beschleunigung und hätte die neun Zusatzfelder nie gesucht.

## MQTT-Live-Push vs. REST-Polling

Der Push ist der eigentliche Live-Kanal: neue Werte kommen in ~2–3 Sekunden
an, während `quota/all` teils über eine Minute hinterherhinkt. FlowBridge
nutzt beides — Push für Echtzeit, REST als träges Sicherheitsnetz.

Jede Push-Nachricht trägt einen Modul-Ausschnitt mit **un-präfigierten**
Feldnamen plus einen `typeCode`, aus dem sich das `quota/all`-Präfix ableitet:

| `typeCode` | Präfix | moduleType |
| --- | --- | --- |
| `pdStatus` | `pd.` | 1 |
| `bmsStatus` | `bms_bmsStatus.` | 2 |
| `emsStatus` | `bms_emsStatus.` | 2 |
| `invStatus` | `inv.` | 3 |
| `mpptStatus` | `mppt.` | 5 |

### Vollständige Feldliste aus dem Live-Push

Aufgezeichnet am 12.08.2026 mit `scripts/capture_mqtt.py` über 3 Minuten
(148 Nachrichten) an einem River 2 Pro, währenddessen wurde am Gerät geladen
und geschaltet, damit auch änderungsabhängige Felder auftauchen.
**29 Felder gegenüber 20 in `quota/all`** — neun zusätzliche (fett).

| Modul (`typeCode`) | Felder |
| --- | --- |
| `pdStatus` (1) | `soc`, `wattsOutSum`, `carState`, `carWatts`, `usb1Watts`, `typec1Watts`, `typecChaWatts`, `bpPowerSoc`, `watchIsConfig`, **`remainTime`** |
| `bmsStatus` (2) | `remainTime`, **`soc`**, **`inputWatts`**, **`outputWatts`** |
| `emsStatus` (2) | `dsgRemainTime`, `maxChargeSoc`, `minDsgSoc` |
| `invStatus` (3) | `inputWatts`, `outputWatts`, **`cfgAcEnabled`**, **`cfgAcXboost`**, **`cfgAcOutVol`**, **`cfgAcOutFreq`** |
| `mpptStatus` (5) | `inWatts`, `cfgAcEnabled`, `cfgAcXboost`, `cfgAcOutVol`, `cfgAcOutFreq`, **`carState`** |

Davon in `src/device.py` neu übernommen: `pd.remainTime` (reagiert im Gegensatz
zu `dsgRemainTime`, das konstant auf `5999` stand, tatsächlich — im Capture
`4742` → `2297` → `10`), `bms_bmsStatus.inputWatts`/`outputWatts`/`soc`.

**Nicht übernommen:** die AC-Felder aus `invStatus` und `mppt.carState`. Das
INV-Modul meldet dieselben Größen wie MPPT, aber abweichend — im selben
Zeitraum meldete `mpptStatus` `cfgAcOutVol: 230`/`cfgAcOutFreq: 50`, während
`invStatus` `0`/`2` lieferte (letzteres offenbar die Enum-Kodierung).
**MPPT ist hier die verlässliche Quelle.** `mppt.carState` dupliziert
`pd.carState`.

**Weder in `quota/all` noch im Push:** Batterietemperatur und Ladezyklen.
Über die offizielle API damit nicht verfügbar — am 14.08.2026 über einen
vollen Ladezyklus bestätigt (siehe unten).

Beobachtete Eigenheiten:
- Es kommen auch Nachrichten **ohne** `typeCode` (z. B.
  `instructCode: "setReportCfg"` mit leeren `params`) — werden ignoriert.
- Verschiedene Module melden teils dieselbe Größe unterschiedlich (siehe
  `cfgAcOutFreq`-Hinweis unten) — deshalb pro Präfix mergen, nicht global.
- **Fallstrick beim Implementieren:** `subscribe()` erst nach erfolgreichem
  `on_connect` aufrufen. Direkt nach `connect()` (während `loop_start()` den
  Handshake noch im Hintergrund macht) schlägt es mit `MQTT_ERR_NO_CONN` fehl
  und wird *nicht* automatisch nachgeholt — es kommt dann schlicht nie eine
  Nachricht an, ohne Fehlermeldung.

## Steuerbefehle (verifiziert gegen Dev-Portal-Doku)

Laufen ebenfalls per REST (`PUT /iot-open/sign/device/quota`), keine eigene
MQTT-Verbindung zum EcoFlow-Broker nötig. Implementiert in
`src/commands_river2.py`:

| FlowBridge-Property | moduleType | operateType | Params |
| --- | --- | --- | --- |
| `car_output_enabled` | 5 (MPPT) | `mpptCar` | `{enabled}` |
| `ac_output_enabled` | 5 (MPPT) | `acOutCfg` | `{enabled}` |
| `xboost_enabled` | 5 (MPPT) | `acOutCfg` | `{xboost}` |
| `charge_limit_percent` | 2 (BMS) | `upsConfig` | `{maxChgSoc}` |
| `discharge_limit_percent` | 2 (BMS) | `dsgCfg` | `{minDsgSoc}` |
| ~~`backup_reserve_percent`~~ | 1 (PD) | `watthConfig` | **wird nicht angenommen** — siehe unten |
| ~~`backup_reserve_enabled`~~ | 1 (PD) | `watthConfig` | **wird nicht angenommen** — siehe unten |

### `watthConfig` ist beim River 2 Pro nicht schreibbar (14.08.2026)

Am Gerät gemessen, in drei Läufen über rund eine Viertelstunde:

| gesendet | `moduleType` | Ergebnis |
| --- | --- | --- |
| `{isConfig: 0, bpPowerSoc: 80}` | 1 | `pd.watchIsConfig` bleibt `1` |
| `{isConfig: 0, bpPowerSoc: 0}` | 1 | `pd.watchIsConfig` bleibt `1` |
| `{isConfig: 0, bpPowerSoc: 80}` | 5 | `pd.watchIsConfig` bleibt `1` |
| `{isConfig: 1, bpPowerSoc: 50}` | 1 | `pd.bpPowerSoc` bleibt `80` |

EcoFlow quittiert jedes Mal ohne Fehler. Auch in der **EcoFlow-App** bewegt
sich dabei nichts — es ist also kein bloßes Anzeigeproblem.

**Der Lesepfad ist einwandfrei:** Wird der Schalter IN der App umgelegt, steht
der neue Wert innerhalb von Sekunden in FlowBridge. Die App benutzt zum
Schreiben offenbar einen anderen Weg als die dokumentierte Schnittstelle.

Konsequenz: Beide Felder stehen in `commands_river2.NUR_LESBAR`. Die
Oberfläche zeigt sie an, bietet sie aber nicht zum Ändern an; Home Assistant
bekommt `binary_sensor`/`sensor` statt `switch`/`number`, und der EisBär-Export
lässt die `cmnd/`-Kanäle weg. Ein Befehl über MQTT wird mit einer Fehlermeldung
abgelehnt, statt spurlos zu verschwinden.

> **Messfalle, zweimal hineingetappt:** `quota/all` antwortet aus dem
> Cloud-Zwischenspeicher und hinkt Sollwert-Änderungen **Minuten** hinterher.
> Eine Gegenprobe mit `dsgCfg` (Entladelimit) galt deshalb zunächst als
> „wirkungslos" — sie wirkte, nur später. Wer hier misst, prüft gegen den
> **Push**, nicht gegen `quota/all`, oder wartet mehrere Minuten.

| Feld | Bedeutung (vermutet) |
| --- | --- |
| `pd.soc` | Haupt-Ladezustand (%) |
| `pd.bpPowerSoc` | Eingestellte **Backup-Reserve** (%) — siehe Korrektur weiter unten |
| `inv.inputWatts` | Eingangsleistung gesamt (W) |
| `mppt.inWatts` | Solar-Eingangsleistung (W) |
| `pd.wattsOutSum` | Ausgangsleistung gesamt (W) |
| `bms_emsStatus.dsgRemainTime` | Restlaufzeit bis leer (Min) |
| `bms_bmsStatus.remainTime` | Restzeit (Kontext unklar, im Test immer 0) |
| `mppt.cfgAcEnabled` | AC-Ausgang aktiviert (0/1) |
| `mppt.cfgAcOutVol` | AC-Ausgangsspannung (V) |
| `mppt.cfgAcOutFreq` | AC-Ausgangsfrequenz (Hz) |
| `mppt.cfgAcXboost` | X-Boost-Modus aktiviert (0/1) |
| `pd.carState` | 12V-KFZ-Ausgang aktiviert (0/1) |
| `pd.carWatts` | KFZ-Ausgangsleistung (W) |
| `pd.usb1Watts` | USB-A-Ausgangsleistung (W) |
| `pd.typec1Watts` | USB-C-Ausgangsleistung (W) |
| `pd.typecChaWatts` | USB-C-Ladeleistung (W) |
| `bms_emsStatus.maxChargeSoc` | Konfiguriertes Lade-Limit (%) |
| `bms_emsStatus.minDsgSoc` | Konfiguriertes Entlade-Limit (%) |
| `pd.watchIsConfig` | **Backup-Reserve ein/aus** (0/1) — verifiziert 14.08.2026 |

## Fallstrick: `acOutCfg` wirkt nur mit ALLEN vier Parametern (gelöst 12.08.2026)

`set_quota(sn, MODULE_MPPT, "acOutCfg", {"xboost": 1})` — also nur ein
einzelnes Feld — quittiert EcoFlow mit `code: "0", message: "Success"`, das
Gerät ignoriert den Befehl aber stillschweigend. Live verifiziert: der Wert
blieb sowohl im MQTT-Push als auch in einer frischen `quota/all`-Abfrage
unverändert.

**Lösung:** immer alle vier Felder mitschicken (`enabled`, `xboost`,
`out_voltage`, `out_freq`); die nicht zu ändernden Werte aus dem zuletzt
gelesenen Status übernehmen. Implementiert in `_ac_out_cfg()` in
`src/commands_river2.py`. Danach schaltete X-Boost sofort und korrekt.

**Kodierungs-Asymmetrie beachten:** `out_freq` ist beim SCHREIBEN ein Enum
(`1` = 50Hz, `2` = 60Hz), beim LESEN meldet `mppt.cfgAcOutFreq` dagegen die
echten Hertz (`50`). Muss also hin- und zurückübersetzt werden. (Kurios:
`invStatus` im MQTT-Push meldet `cfgAcOutFreq: 2`, also die Enum-Variante,
während `mpptStatus` im selben Moment `50` meldet.)

## AC-Ladeleistung: schreibbar, aber nicht lesbar (verifiziert 12.08.2026)

Der Befehl ist **undokumentiert**, funktioniert aber am River 2 Pro — über die
IoT-Open-API wird diese Payload-Form unverändert akzeptiert (am Gerät
verifiziert):

```
moduleType 5, operateType "acChgCfg", params: {"chgWatts": 100…870, "chgPauseFlag": 0}
```

Live gegengemessen am gemessenen AC-Eingang (`inv.inputWatts`):

| gesetzt | gemessen | Verzögerung |
| --- | --- | --- |
| 700 W | 709 W | ~50 s |
| 100 W | 89 W | ~20 s |
| 250 W | 256 W | ~10 s |

Wertebereich River 2 Pro: **100–870 W in 50-W-Schritten**.

### `chgPauseFlag: 1` pausiert das Laden — auch am River 2 Pro

Ebenfalls undokumentiert für dieses Gerät (die Doku führt es nur bei Delta 2 /
Delta 2 Max), aber verifiziert: `chgPauseFlag: 1` zieht den AC-Eingang binnen
Sekunden auf **0 W**, `0` bringt ihn zurück (gemessen: 105 W → 0 W → 105 W,
zusätzlich am Gerätedisplay bestätigt). Damit braucht es für "nicht laden"
**keine schaltbare Steckdose**.

Laut Delta-2-Doku wird die Pause **nicht dauerhaft gespeichert** und fällt
beim Aus- und Einstecken des Netzkabels wieder weg.

**Wichtig:** `acChgCfg` verlangt beide Parameter zusammen. Wer nur die Leistung
ändert, muss den aktuellen Pausenzustand mitschicken — sonst wirft ein
Leistungswechsel eine laufende Pause ungewollt wieder an. Umgekehrt genauso.
Beides ist in `commands_river2.py` berücksichtigt und in
`tests/test_commands_river2.py` festgenagelt.

**Zwei Fallstricke bei der Messung:**
- Die Umstellung braucht **20–50 s**, bis sie sich am Eingang zeigt. Schnell
  aufeinanderfolgende Änderungen sehen deshalb aus, als würde nichts passieren.
- Der gemessene AC-Eingang ist **Ladeleistung + AC-Ausgangslast**. Hängt ein
  Verbraucher dran (im Test ein Sunlu S2, der thermostatgesteuert pulst),
  wandert der Messwert unabhängig von der Einstellung.

**Nicht lesbar:** Den eingestellten Wert gibt EcoFlow nirgends zurück (siehe
nächster Abschnitt). FlowBridge merkt sich deshalb nur, was es selbst zuletzt
gesetzt hat (`charge_power_watts_set`, nach Neustart wieder leer, und blind
gegenüber Änderungen aus der EcoFlow-App).

## Nicht lesbar: der eingestellte Ladeleistungs-Wert (geprüft 12.08.2026)

Schreiben geht (siehe oben), **Lesen nicht**:

- **41 Kandidaten-Feldnamen** wurden lesend abgefragt (u. a.
  `inv.cfgSlowChgWatts`, `inv.cfgFastChgWatts`, `mppt.cfgChgWatts`,
  `mppt.cfgDcChgCurrent`, `pd.chgPowerAC`, `bms_emsStatus.chgAmp`) — **keiner
  existiert**. Mitabgefragte Kontrollfelder (`pd.soc`, `inv.inputWatts`) kamen
  korrekt zurück, die Abfrage funktionierte also.
- 5 Minuten MQTT-Live-Mitschnitt **während aktiver Ladung** (238 Nachrichten,
  bis 722 W): unverändert dieselben 29 Felder, kein Sollwert dabei.

Als *Messwert* ist die Ladeleistung dagegen vorhanden: `inv.inputWatts`
("AC input real-time power") — abzüglich einer etwaigen AC-Ausgangslast.

**Nebenbefund — Fehler in der offiziellen Doku:** Der Abfrage-Endpoint
`/iot-open/sign/device/quota` (Einzelfelder per `params.quotas`) ist dort als
`GET` dokumentiert, antwortet auf GET aber mit `405 Method Not Allowed`.
Korrekt ist **POST**.

## Korrektur: `pd.bpPowerSoc` ist die Backup-Reserve

Dieses Feld war hier zunächst als "SoC einer Zusatzbatterie" geführt — falsch.
Laut Dev-Portal (`watthConfig`) ist es die eingestellte **Backup-Reserve in
Prozent**, also ein Sollwert, kein Messwert. Wird im UI entsprechend als
einstellbarer Wert geführt, nicht als Kachel.

Ebenfalls präzisiert (Doku-Wortlaut):

| Feld | Bedeutung laut Doku | FlowBridge-Metrik |
| --- | --- | --- |
| `inv.inputWatts` | AC input real-time power | `ac_watts_in` (AC-Ladeleistung) |
| `inv.outputWatts` | AC output real-time power | `ac_watts_out` |
| `mppt.inWatts` | DC input real-time power | `dc_watts_in` (Solar **oder** KFZ) |
| `pd.wattsOutSum` | Total output real-time power | `watts_out` |

## Backup-Reserve ist zweiteilig — und schaltet das Laden (14.08.2026)

In der EcoFlow-App besteht die Backup-Reserve aus **zwei** Bedienelementen:
einem Schalter und einem Prozentwert, und der Prozentwert lässt sich nur
einstellen, wenn der Schalter an ist. Genau das bildet `watthConfig` ab:

```
moduleType 1 (PD), operateType "watthConfig", params: {"isConfig": 0|1, "bpPowerSoc": 10…100}
```

`isConfig` ist der Schalter, `bpPowerSoc` der Prozentwert.

**`pd.watchIsConfig` meldet den Schalter zurück.** Live verifiziert durch
Umlegen in der App bei laufendem Push-Mitschnitt:

```
07:47:02  watchIsConfig: 1 → 0     (aus)
07:47:10  watchIsConfig: 0 → 1     (ein)
07:47:38  watchIsConfig: 1 → 0     (aus)
```

Das Feld stand hier bis dahin als „unklar, ungenutzt".

> **Messfalle:** Ein Kontrollwert aus `quota/all`, kurz nach dem Umschalten
> abgefragt, meldete weiterhin den alten Zustand — die Abfrage fiel in eine
> Push-Lücke, und EcoFlow beantwortet sie dann aus dem Cloud-Zwischenspeicher.
> Erst der Push zeigt den Wechsel. Wer hier misst, muss prüfen, ob der Push
> gerade läuft.

### Die Reserve hebt eine Ladepause auf

Die Backup-Reserve ist keine Anzeige, sondern eine **Ladesteuerung**: Liegt
der Ladestand unter dem eingestellten Wert, lädt das Gerät aus dem Netz.
Wird sie umgeschaltet, startet das Laden — auch dann, wenn zuvor über
`chgPauseFlag: 1` pausiert wurde. Live mitgeschnitten:

```
07:47:38  watchIsConfig: 1 → 0
07:47:41  bms_bmsStatus.inputWatts: 0 → 41     (Batterie nimmt Strom)
07:47:42  inv.inputWatts:           0 → 128    (AC-Eingang)
```

Da `chgPauseFlag` **nicht lesbar** ist (siehe oben), kann FlowBridge das nicht
mitbekommen — es zeigte weiter „pausiert". Gelöst über
`_pause_gegen_messung_pruefen()` in `src/app.py`: Nimmt die Batterie Strom
auf, **während** der AC-Eingang liefert, wird die gemerkte Pause verworfen.
Beide Bedingungen sind nötig — nur AC wäre Durchleitung, nur Batterie wäre
Solar.

### Behoben: der Schreibbefehl ändert nur noch das Gefragte

`commands_river2.py` sendete beim Setzen des Prozentwerts fest `isConfig: 1` —
wer nur den Wert verstellte, **schaltete die Reserve damit ein** und startete
so das Laden. Seit 14.08.2026 baut `_watth_config()` das Param-Set wie
`_ac_out_cfg()`: beide Felder gehen mit, der jeweils nicht gemeinte Teil
kommt aus dem zuletzt gelesenen Stand. Ist der Schalterzustand noch unbekannt
(vor dem ersten Push), gilt weiterhin `1`.

FlowBridge kennt jetzt beide Hälften als eigene Properties:

| Property | wirkt auf |
| --- | --- |
| `backup_reserve_enabled` | `isConfig` — der Schalter |
| `backup_reserve_percent` | `bpPowerSoc` — der Prozentwert |

**Umbenannt:** Die gelesene Metrik hieß bis dahin `energy_management_enabled`
— ein Name aus der Zeit, als nur die Herkunft bekannt war, nicht die
Bedeutung. Das alte `status/`-Topic wird beim Start aktiv geleert
(`_VERALTETE_STATUSFELDER`), sonst bliebe es retained stehen.

## Undokumentierte Befehle: was geht, was nicht (getestet 12.08.2026)

Die offizielle Portal-Doku listet für das River 2 Pro nur `acOutCfg`,
`dsgCfg`, `mpptCar`, `upsConfig`, `watthConfig`.
Getestet wurde, was Delta 2 / Delta 2 Max zusätzlich kennen:

| Befehl | Ergebnis am River 2 Pro |
| --- | --- |
| `acChgCfg` (`chgWatts`) | **funktioniert** — messbar am AC-Eingang |
| `acChgCfg` (`chgPauseFlag`) | **funktioniert** — Ladung auf 0 W, am Display bestätigt |
| `lcdCfg` (Helligkeit/Abschaltzeit) | **wirkungslos** — Display blieb unverändert |
| `quietMode` | unbekannt — keine messbare Rückmeldung, nicht beurteilbar |

**Merksatz:** Eine `"Success"`-Antwort beweist gar nichts. EcoFlow quittiert
auch Befehle, die das Gerät stillschweigend verwirft (siehe `lcdCfg` oben, und
`acOutCfg` mit Teil-Parametern weiter oben). Ein undokumentierter Befehl gilt
erst als bestätigt, wenn eine **messbare oder am Gerät sichtbare** Wirkung
eintritt.

## Lesend gibt es nichts über die 20 Felder hinaus

Alle **262** Feldnamen, die für Delta 2, Delta 2 Max und Delta Pro dokumentiert
sind, aber nicht fürs River 2 Pro, wurden lesend abgefragt (blockweise, mit
`pd.soc` als Kontrollfeld je Block): **kein einziges existiert**. Darunter
Zelltemperaturen, Ladezyklen, `soh`, `inv.SlowChgWatts`/`inv.FastChgWatts`.
Was das Gerät liefert, sind exakt die oben gelisteten 20 Felder — der
Schreibweg ist also deutlich großzügiger als der Leseweg.

## Über einen vollen Ladezyklus verifiziert (14.08.2026)

Bis hierher stützte sich alles auf Mitschnitte von Minuten. Der Einwand lag
auf der Hand: Der Push ist **änderungsgetrieben** — ein Wert wie `cycles`
ändert sich einmal pro Ladevorgang, `temp` nur unter Last. Fünf Minuten Ruhe
beweisen darüber nichts.

Deshalb lief das Feldinventar (`src/inventar.py`) **acht Stunden über einen
vollständigen Ladevorgang von 32 % auf 100 %**:

| | |
| --- | --- |
| Laufzeit | 8,0 h (13.08. 22:27 → 14.08. 06:29) |
| Felder | **29** |
| Neue Felder nach den ersten 29 Sekunden | **keins** |
| Dateigröße | 10,6 KB |

Der Feldsatz ist **deckungsgleich** mit dem 5-Minuten-Mitschnitt vom Vortag —
keines dazu, keines weg. Ein Ladezyklus ist genau das Ereignis, bei dem sich
`cycles` ändern müsste; er lief durch, und das Feld kam nicht.

**Damit ist die Einschränkung „nicht beobachtet ≠ nicht vorhanden" ausgeräumt.**
Batterietemperatur, Ladezyklen und `soh` sind über die offizielle Schnittstelle
nicht zu bekommen.

### Wichtige Unterscheidung: das Gerät kann es, die API gibt es nicht heraus

Ein Abgleich mit einem **alten EisBär-Payload-Satz** (13.08.2026, aus einer
früheren Anbindung über das inoffizielle App-Protokoll — ein JSON über alle
Module) zeigt: Von **168 Feldern kommen über die offizielle API noch 27 an.**

| Modul | damals | heute |
| --- | ---: | ---: |
| `pd` | 45 | 8 |
| `mppt` | 37 | 6 |
| `inv` | 28 | 6 |
| `bms_bmsStatus` | 28 | **4** |
| `bms_emsStatus` | 23 | 3 |

Im alten Satz standen `cycles`, `temp`, `maxCellTemp`, `soh`, `fullCap`,
`designCap`, `remainCap`, `vol`, `amp`. **Das Gerät kennt diese Werte also
sehr wohl** — die IoT Open Platform reicht sie nur nicht durch. Das ist eine
Entscheidung von EcoFlow, keine Eigenschaft der Hardware. Formulierungen wie
„das River 2 Pro liefert keine Batterietemperatur" sind entsprechend falsch.

### Der gezielte Abruf hilft nicht weiter

`POST /iot-open/sign/device/quota` mit `params.quotas` antwortet **nur für
Felder, die auch in `quota/all` stehen**. Nachgewiesen an einer Gegenprobe:

```
bms_bmsStatus.remainTime   [in quota/all]  ->  antwortet
bms_bmsStatus.soc          [nur im Push ]  ->  leer
```

`bms_bmsStatus.soc` kommt im Push alle paar Minuten herein, existiert also
zweifelsfrei — über den gezielten Abruf bleibt es trotzdem stumm. **Eine leere
Antwort beweist deshalb nichts** außer „steht nicht auf der `quota/all`-Liste".
Wer damit die Nicht-Existenz eines Feldes belegen will, irrt.

### Nebenbefund: das BMS meldet sich selten

Über die acht Stunden gemessen:

| Modul | Nachrichten/Stunde |
| --- | ---: |
| `inv`, `pd` | ~140–158 |
| `mppt`, `bms_emsStatus` | ~124–127 |
| **`bms_bmsStatus`** | **~11** |

`bms_bmsStatus.soc`, `.inputWatts` und `.outputWatts` kommen also nur etwa alle
fünf Minuten. Wer sich auf sie stützt, arbeitet mit einem trägen Kanal —
`pd.soc` und `inv.inputWatts` sind die schnellen Entsprechungen.

## Offene Fragen für andere Modelle

- Delta-Serie: ungetestet, vermutlich andere/zusätzliche Felder (größere
  Geräte haben z. B. mehrere Batterie-Module, andere BMS-Präfixe). Das
  Feldinventar ist der Weg dorthin, ohne selbst ein Gerät zu besitzen:
  einschalten, zwei Tage laufen lassen, `feldinventar.json` schicken.

## Vorgehen bei neuem Gerätemodell

1. `python scripts/test_quota.py` mit den Zugangsdaten des neuen Geräts laufen lassen.
2. Ausgabe mit dieser Tabelle abgleichen: welche Keys stimmen, welche fehlen/sind neu.
3. `src/device.py` (`_METRIC_CANDIDATES`) um die neuen Kandidaten-Keys ergänzen.
4. Diese Datei um eine Zeile "Modell X: Feld Y" ergänzen, falls es abweicht.
