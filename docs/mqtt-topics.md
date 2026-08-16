# MQTT-Topics

Alles unterhalb von `base_topic` (Default `flowbridge`, in den Einstellungen
änderbar). Alle ausgehenden Topics sind **retained** – ein frisch verbundener
Client (EisBär, Home Assistant, MQTT Explorer) hat den Stand sofort.

## Verfügbarkeit

Drei **unabhängige** Ausfallquellen, deshalb drei Topics:

| Topic | Werte | Bedeutung |
| --- | --- | --- |
| `flowbridge/bridge/available` | `online` / `offline` | FlowBridge selbst. Per Last-Will – meldet auch einen Absturz. |
| `flowbridge/bridge/ecoflow` | `online` / `offline` | Verbindung zur EcoFlow-Cloud. Ist sie weg, sind alle Werte eingefroren. |
| `flowbridge/<SN>/available` | `online` / `offline` | Das Gerät selbst (siehe `/status`-Event + Staleness). |

Der mittlere ist der leicht zu übersehende Fall: FlowBridge läuft, der lokale
Broker ist erreichbar – aber die Cloud antwortet nicht mehr. Ohne dieses Topic
sähen die letzten Werte unverändert aktuell aus.

## Zustand

| Topic | Inhalt |
| --- | --- |
| `flowbridge/<SN>/state` | JSON mit allen normalisierten Werten (inkl. `_modules`) |
| `flowbridge/<SN>/modules/pd` | JSON, Rohwerte des PD-Moduls (moduleType 1) |
| `flowbridge/<SN>/modules/bms` | JSON, `bmsStatus` (moduleType 2) |
| `flowbridge/<SN>/modules/ems` | JSON, `emsStatus` (moduleType 2) |
| `flowbridge/<SN>/modules/inv` | JSON, Wechselrichter (moduleType 3) |
| `flowbridge/<SN>/modules/mppt` | JSON, Laderegler (moduleType 5) |
| `flowbridge/<SN>/status/<feld>` | **Einzelwert** je Messwert – für EisBär am bequemsten |

Die Modul-Topics enthalten die Feldnamen **so wie EcoFlow sie liefert**
(un-präfigiert, z. B. `cfgAcEnabled`). Die `status/`-Topics enthalten die
normalisierten FlowBridge-Namen.

Einzelwerte werden **nur bei Änderung** gesendet. Da sie retained sind, geht
dabei nichts verloren – es liegen nur nicht alle paar Sekunden identische
Werte neu auf dem Broker.

### Verfügbare Einzelwerte

Je nach Modell; fehlende Felder erscheinen gar nicht (das River 2 Pro liefert
z. B. weder Temperatur noch Ladezyklen).

`soc_percent`, `battery_soc_percent`, `ac_watts_in`, `dc_watts_in`,
`battery_watts_in`, `battery_watts_out`, `watts_out`, `ac_watts_out`,
`car_watts`, `usb1_watts`, `typec1_watts`, `typec_charge_watts`,
`ac_output_voltage`, `ac_output_freq_hz`, `ac_output_enabled`,
`xboost_enabled`, `car_output_enabled`, `charge_limit_percent`,
`discharge_limit_percent`, `backup_reserve_percent`,
`energy_management_enabled`, `charge_remain_min`, `discharge_remain_min`,
`battery_temp_c`, `cycles`, `charge_power_watts_set`,
`ac_charging_enabled_set`, `last_update`

Wahrheitswerte kommen als `true`/`false`, EcoFlow-Flags als `1`/`0`.

### Restzeiten

EcoFlow liefert beide Richtungen in **einem** Feld (`pd.remainTime`) – mal ist
es die Zeit bis voll, mal die verbleibende Laufzeit. FlowBridge teilt das auf
zwei Topics mit fester Bedeutung auf, damit ein Kanal nicht im Betrieb
umspringt:

| Topic | gesetzt, wenn | Bedeutung |
| --- | --- | --- |
| `status/charge_remain_min` | geladen wird | Minuten bis zum Ladeende |
| `status/discharge_remain_min` | sonst | verbleibende Laufzeit in Minuten |

Es ist also immer **genau eines von beiden** vorhanden. Die Richtung wird am
gemessenen Leistungsfluss (`ac_watts_in` / `dc_watts_in`) festgemacht, nicht
am Vorzeichen: laut Doku bedeutet `> 0` „bis voll geladen", das River 2 Pro
liefert im Entladen aber positive Werte.

Der EcoFlow-Platzhalter **5999** (99 h 59 min = „keine Schätzung") wird
herausgefiltert – das Topic bleibt dann leer, statt eine erfundene Restzeit
von 100 Stunden zu melden. `bms_emsStatus.dsgRemainTime` steht auf echter
Hardware fast durchgehend auf diesem Platzhalter; die brauchbaren Werte
kommen aus `pd.remainTime`.

## Befehle

Topic-Segment ist **`cmnd`** (wie bei Tasmota):

```
flowbridge/<SN>/cmnd/<property>
```

| Property | Werte | Wirkung |
| --- | --- | --- |
| `ac_output_enabled` | `on` / `off` | AC-Ausgang |
| `xboost_enabled` | `on` / `off` | X-Boost |
| `car_output_enabled` | `on` / `off` | 12V-KFZ-Ausgang |
| `ac_charging_enabled` | `on` / `off` | AC-Laden bzw. **Ladepause** |
| `charge_power_watts` | Zahl | AC-Ladeleistung (Stufen modellabhängig) |
| `charge_limit_percent` | 0–100 | Ladelimit |
| `discharge_limit_percent` | 0–100 | Entladelimit |
| `backup_reserve_percent` | 0–100 | Backup-Reserve |

Beispiel:

```bash
mosquitto_pub -h 192.168.1.10 -t "flowbridge/<SN>/cmnd/charge_power_watts" -m "300"
```

Hinweise:

- `cmnd/` und `status/` liegen bewusst in **getrennten** Unterbäumen. Lägen
  sie zusammen, würde der eigene Status-Publish sofort wieder als Befehl
  zurückkommen.
- Befehls-Topics werden **nicht** retained gesendet (und sollten es auch von
  außen nicht werden) – ein retained Befehl würde bei jedem Neustart erneut
  ausgeführt.
- Ungültige Werte werden abgelehnt und **nur geloggt**: Auf dem MQTT-Weg gibt
  es keinen Rückkanal für Fehlermeldungen.
- Steuerbefehle gibt es nur für Modelle, deren Befehle FlowBridge kennt
  (siehe `src/models.py`).

## Home-Assistant-Discovery

Standardmäßig aktiv, abschaltbar über `homeassistant.discovery` in der
`config.yaml`. Beim Abschalten werden die Config-Topics wieder geleert, die
Entitäten verschwinden also sauber aus HA.

```
homeassistant/<component>/flowbridge_<SN>/<feld>/config
```

Angelegt werden Sensoren für alle Messwerte, Schalter für AC-Ausgang,
X-Boost, KFZ-Ausgang und AC-Laden sowie Zahlenfelder für Lade-/Entladelimit,
Backup-Reserve und Ladeleistung. Alle Entitäten teilen sich einen
`device`-Block, erscheinen in HA also unter **einem** Gerät.

Für Modelle ohne bekannte Befehle entstehen **nur Sensoren** – ein Schalter,
der nichts bewirkt, wäre schlimmer als keiner.

## Topic-Export

Die Einstellungen bieten mehrere Dateien zum Herunterladen, jeweils **mit oder
ohne die Modul-Rohwerte** (Schalter in der Kachel):

| Datei | wofür |
| --- | --- |
| `flowbridge-topics.csv` | schlichte Liste zum Nachschlagen, für jeden MQTT-Client |
| `flowbridge-eisbaer.zip` | **beide** EisBär-Dateien plus Kurzanleitung |
| `flowbridge-payloadeditor.xml` | EisBär-Payloadeditor: die JSON-Profile |
| `flowbridge-kanaleditor.csv` | EisBär-Kanaleditor: alle Kanäle |

**Beim EisBär zuerst das XML importieren, dann die CSV.** Die CSV verweist über
Spalte 11 auf ProfileIds, die zum Importzeitpunkt existieren müssen. Im ZIP
tragen die Dateien die Reihenfolge im Namen (`1-` und `2-`).

**Mit oder ohne Module?** Ohne ist der Standard: die fünf Modul-Topics liefern
EcoFlow-Rohwerte, die man zum Nachschauen braucht, aber selten verknüpft — im
Alltag arbeitet man mit den Einzelwerten unter `status/`. Eingeschaltet wächst
das Profil-XML um rund 50 Knoten. Der Dateiname bekommt dann den Zusatz
`-mit-modulen`, damit nicht zwei gleichnamige Dateien im Download-Ordner
landen.

Zwei Dinge trägt der Export gleich richtig ein, die man sonst übersieht:

- **Befehlskanäle bekommen An=`on` / Aus=`off`.** Ohne gesetzten TrueString
  sendet EisBär wörtlich `True`/`False`. FlowBridge nimmt das inzwischen an
  (`true`, `1`, `an`, `yes` ebenfalls), aber der Export verlässt sich nicht
  darauf: Was ein Kanal senden soll, gehört in den Kanal und nicht in die
  Nachsicht der Gegenstelle. Würde das Einlesen je enger gefasst, täten sonst
  alle exportierten Schalter stillschweigend nichts – auf dem MQTT-Weg gibt es
  keinen Rückkanal für Fehlermeldungen.
- **EcoFlow-Flags bekommen An=`1` / Aus=`0`.** Diese beiden Werte fallen durch
  alle Erkennungsstufen von EisBär durch; ohne die Angabe stünde der Kanal
  dauerhaft auf „Aus".

Profile sind **shape-basiert**: Zwei River 2 Pro teilen sich ein Profil, die
Struktur hängt am Modell und nicht an der Seriennummer.

### Die generische Liste

Bewusst ohne EisBär-Vokabular. Sie nennt die Richtung ehrlich `schreiben` für
`cmnd/`-Topics – FlowBridge veröffentlicht dort nichts, wer Werte erwartet,
wartet vergeblich. Typen heißen `boolean` / `ganzzahl` / `dezimalzahl` /
`text` / `json` statt `INT64_STRING`, es gibt eine Spalte **Einheit**, und
An/Aus stehen nur bei Wahrheitswerten.
