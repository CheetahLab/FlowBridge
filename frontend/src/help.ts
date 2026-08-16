/**
 * Inhalt der Hilfe. Getrennt von i18n.ts, weil es Fließtext in Abschnitten ist
 * und die Sprachtabelle sonst unlesbar würde.
 *
 * Der Inhalt hält fest, was am echten Gerät gemessen wurde – besonders die
 * Punkte, die weder in der EcoFlow-App noch in deren Dokumentation stehen.
 */
export interface HelpSection {
  titel: string;
  punkte: string[];
}

const de: HelpSection[] = [
  {
    titel: "Was FlowBridge tut",
    punkte: [
      "FlowBridge verbindet deinen mobilen Energiespeicher mit deinem eigenen MQTT-Broker. Von dort kommen EisBär, Home Assistant, ioBroker oder jedes andere MQTT-Programm heran, ohne dass sie die EcoFlow-Zugangsdaten kennen müssen.",
      "Die Werte holt FlowBridge nicht durch Abfragen: Es hängt am EcoFlow-Broker und bekommt Änderungen zugeschickt. Deshalb stehen sie meist binnen Sekunden auf deinem Broker. Zusätzlich läuft ein langsamer Abgleich über die REST-Schnittstelle, damit nach einem Neustart nichts fehlt.",
      "Befehle laufen umgekehrt denselben Weg. Ob du in dieser Oberfläche klickst oder ein MQTT-Topic beschreibst, macht keinen Unterschied — dahinter liegt derselbe Code.",
    ],
  },
  {
    titel: "Bedienung",
    punkte: [
      "Je Speicher gibt es eine Doppelkachel: links Messwerte und Bedienung, rechts der Verlauf mit Energiebilanz.",
      "Die Reiter über den Kacheln (PD, BMS, EMS, INV, MPPT) zeigen die Rohwerte, so wie EcoFlow sie liefert. Sie sind zum Nachschauen gedacht, wenn ein Wert seltsam aussieht.",
      "Ist ein Speicher offline, wird seine Kachel abgedunkelt und die Bedienung gesperrt. Ein Schalter, der ins Leere ginge, wäre schlimmer als keiner.",
      "„Jetzt abfragen“ erzwingt einen sofortigen Abgleich über die REST-Schnittstelle. Nötig ist das selten — nur wenn du den Verdacht hast, dass eine Push-Nachricht verlorenging.",
      "Umgestellte Sollwerte brauchen 20–50 Sekunden, bis sie sich am gemessenen Eingang zeigen. Das ist das Gerät, nicht FlowBridge.",
    ],
  },
  {
    titel: "Verlauf",
    punkte: [
      "Zeitraum umschaltbar zwischen 15 Minuten, 1 Stunde und 6 Stunden. Aufgezeichnet wird alle 15 Sekunden.",
      "Klick auf einen Eintrag in der Legende blendet die Kurve aus — hilfreich, wenn eine große Leistung die kleinen Werte plattdrückt.",
      "Zwei Achsen: Prozent links (Ladezustand), Watt rechts. Die Watt-Achse skaliert automatisch auf den größten sichtbaren Wert.",
      "Der Verlauf liegt nur im Arbeitsspeicher und beginnt nach einem Neustart von vorn. Für Langzeitauswertung ist dein MQTT-Broker mit Datenbank der richtige Ort, nicht FlowBridge.",
    ],
  },
  {
    titel: "Energiebilanz",
    punkte: [
      "Sie zeigt, wie viel von dem, was hereinkommt, tatsächlich ankommt — und was auf dem Weg als Wärme verlorengeht.",
      "Die Richtung wird an der Batterie abgelesen, nicht am Eingang. Bei angestecktem Netzkabel speist das Gerät Verbraucher direkt durch; dann ist der Eingang hoch, obwohl die Batterie unbeteiligt ist.",
      "Verbraucher am Ausgang werden abgezogen, bevor der Wirkungsgrad gebildet wird. Sonst sähe ein angeschlossenes Gerät wie ein schlechter Wandler aus.",
      "Der Momentanwert schwankt zwangsläufig: Eingang, Ausgang und Batterieleistung kommen aus drei verschiedenen Modulen und treffen zeitversetzt ein. Verlässlich ist der Wirkungsgrad in der Zeitraum-Statistik darunter — dort mitteln sich die Versätze heraus.",
      "Wichtigste Erkenntnis aus der Messung: Der Grundverbrauch des Ladewandlers ist nahezu fest. Am River 2 Pro kamen bei 100 W Ladeleistung nur 58 % in der Batterie an, bei 500 W dagegen 87 %. Langsam laden kostet also spürbar mehr Strom als schnell laden.",
    ],
  },
  {
    titel: "Zugriffsschutz",
    punkte: [
      "FlowBridge ist mit einem Passwort geschützt. Solange keines gesetzt ist, liefert die Schnittstelle gar keine Daten – auch nicht an ein anderes Programm im Netz.",
      "Das Passwort lässt sich in den Einstellungen ändern. Dabei werden alle anderen angemeldeten Geräte abgemeldet: Wer sein Passwort ändert, will in aller Regel jemanden aussperren.",
      "Vergessen? Dann hilft nur, den auth-Block aus der config.yaml zu löschen und neu zu starten.",
      "FlowBridge spricht HTTP. Im eigenen Netz ist das in Ordnung, über das Internet gehört ein Reverse Proxy mit TLS davor – sonst geht das Passwort im Klartext über die Leitung.",
      "Die MQTT-Seite schützt das nicht: Wer auf deinen Broker schreiben darf, darf auch Befehle senden. Das regelst du in den Rechten deines Brokers, dort gehört es hin.",
    ],
  },
  {
    titel: "MQTT",
    punkte: [
      "Alles liegt unter dem eingestellten Basis-Topic (Standard „flowbridge“) und wird retained gesendet — ein frisch verbundener Client hat den Stand sofort.",
      "Je Speicher: ein vollständiges JSON unter state, ein JSON je Modul unter modules/, und jeder Messwert einzeln unter status/. Für das Verknüpfen im EisBär sind die Einzeltopics am bequemsten.",
      "Befehle gehen an cmnd/<Eigenschaft> — bewusst in einem eigenen Unterbaum, damit der eigene Status-Publish nicht sofort als Befehl zurückkommt.",
      "Drei getrennte Verfügbarkeits-Topics, weil es drei unabhängige Ausfallquellen gibt: FlowBridge selbst, die Verbindung zur EcoFlow-Cloud und das Gerät. Fällt die Cloud aus, sind alle Werte eingefroren — ohne eigenes Topic sähe man das nicht.",
      "Für Home Assistant werden die Geräte automatisch angemeldet (MQTT Discovery). Abschaltbar in den Einstellungen; beim Abschalten verschwinden sie sauber wieder.",
      "Die vollständige Topic-Liste steht in docs/mqtt-topics.md im Projektverzeichnis.",
    ],
  },
  {
    titel: "Topic-Export",
    punkte: [
      "In den Einstellungen liegt ein Export, der dir das Abtippen abnimmt. Alle Topics stehen darin mit Typ, Einheit und Schaltwerten — fertig zum Einlesen.",
      "„Topic-Liste (CSV)“ ist die allgemeine Fassung für jeden MQTT-Client: Topic, Richtung, Typ, Einheit, Beispielwert. Bewusst ohne EisBär-Vokabular.",
      "Für den EisBär gibt es zwei Dateien — den Payloadeditor (XML, die JSON-Profile) und den Kanaleditor (CSV, alle Kanäle) — sowie beides zusammen als ZIP mit Kurzanleitung.",
      "Die Reihenfolge zählt: zuerst das XML, dann die CSV. Die CSV verweist auf Profile, die zum Importzeitpunkt schon existieren müssen. Im ZIP steht die Reihenfolge in den Dateinamen.",
      "Der Schalter „Modul-Rohwerte einschließen“ nimmt zusätzlich die fünf Modul-Topics auf. Ohne ist der Standard — die Rohwerte sind zum Nachschauen da, im Alltag verknüpfst du die Einzelwerte. Eingeschaltet wächst das Profil-XML um rund 50 Knoten, und der Dateiname bekommt den Zusatz „-mit-modulen“.",
      "Zwei Dinge trägt der Export gleich richtig ein, die man sonst übersieht: Schaltbefehle bekommen An=on/Aus=off, und die EcoFlow-Flags An=1/Aus=0. Ohne diese Werte stünde ein Flag-Kanal dauerhaft auf „Aus“, weil 1 und 0 durch alle Erkennungsstufen fallen.",
      "Die Profile sind an das Modell gebunden, nicht an die Seriennummer: Zwei gleiche Speicher teilen sich eines.",
    ],
  },
  {
    titel: "Wenn etwas nicht läuft",
    punkte: [
      "In den Einstellungen gibt es ein Diagnose-Paket: Protokoll einschalten, den Fehler nachstellen, Paket herunterladen und verschicken. Darin stehen Version, maskierte Konfiguration, Zustand der drei Verbindungen, Feldzahl je Gerät und das Protokoll.",
      "Die letzten Zeilen laufen immer im Speicher mit, auch ohne eingeschaltetes Protokoll — sonst wäre ausgerechnet der Moment nicht drin, in dem der Fehler auftrat.",
      "Schlüssel, Passwörter und Signaturen werden unkenntlich gemacht, bevor irgendetwas geschrieben wird. Seriennummer und Kontokennung stehen als „<GERAET-1>“ und „<KONTO>“ darin; das Modell liegt als eigene Zuordnung bei, damit sich das Paket trotzdem auswerten lässt.",
      "Das Datei-Protokoll ist auf 5 × 5 MB begrenzt und rotiert. Es reicht damit rund drei bis vier Tage zurück und läuft dir nicht die Platte voll, wenn du es eingeschaltet vergisst.",
      "Daneben steht das Feldinventar. Es schreibt nicht den Datenstrom mit, sondern je Feld nur, wann es zuerst und zuletzt kam, wie oft und in welchem Wertebereich — das bleibt auch nach Wochen wenige Kilobyte. Genau daran wird sichtbar, wenn ein EcoFlow-Firmwareupdate Felder hinzufügt oder wegnimmt.",
    ],
  },
  {
    titel: "Was das Gerät nicht hergibt",
    punkte: [
      "Das River 2 Pro liefert genau 20 lesbare Felder. Batterietemperatur und Ladezyklen sind nicht darunter — sie fehlen nicht zufällig, sie existieren in der Schnittstelle nicht.",
      "Eingestellte Sollwerte kann man beim River 2 Pro nicht zurücklesen. FlowBridge merkt sich deshalb, was es zuletzt gesetzt hat, und zeigt diesen Wert an.",
      "EcoFlow meldet auch dann „Erfolg“, wenn das Gerät einen Befehl stillschweigend verwirft. Ein grünes Ergebnis ist also kein Beweis — nur eine sichtbare Wirkung ist einer.",
      "Historische Daten gibt es für Powerstations bei EcoFlow nicht. Was FlowBridge an Verlauf und Statistik zeigt, rechnet es selbst aus dem laufenden Betrieb.",
    ],
  },
  {
    titel: "Was nach draußen geht",
    punkte: [
      "FlowBridge redet mit zwei Gegenstellen: der EcoFlow-Cloud und deinem eigenen MQTT-Broker. Sonst mit niemandem — mit einer Ausnahme.",
      "Die Ausnahme ist die Update-Prüfung. Sie holt beim Start und danach alle sechs Stunden die öffentliche Versionsliste von Docker Hub. Übertragen wird nichts über dich oder deinen Speicher; sichtbar wird dort deine IP-Adresse und damit, dass FlowBridge läuft.",
      "Abschaltbar unter Einstellungen → Updates. Der Knopf „Jetzt prüfen“ fragt dann trotzdem, wenn du ihn drückst — ein Klick ist eine Entscheidung, kein stiller Abruf.",
      "Diagnosepaket und Feldinventar verlassen das Haus nur, wenn du sie selbst verschickst. Es gibt keinen Knopf, der etwas an den Entwickler sendet.",
    ],
  },
];

const en: HelpSection[] = [
  {
    titel: "What FlowBridge does",
    punkte: [
      "FlowBridge connects your portable power station to your own MQTT broker. From there EisBär, Home Assistant, ioBroker or any other MQTT client can reach it without ever seeing your EcoFlow credentials.",
      "Values are not polled: FlowBridge subscribes to the EcoFlow broker and receives changes as they happen, so they usually reach your broker within seconds. A slow REST sync runs alongside it so nothing is missing after a restart.",
      "Commands travel the same path in reverse. Clicking in this interface and writing to an MQTT topic are the same thing — they share the same code underneath.",
    ],
  },
  {
    titel: "Using it",
    punkte: [
      "Each device gets a pair of cards: readings and controls on the left, history and energy balance on the right.",
      "The tabs above the tiles (PD, BMS, EMS, INV, MPPT) show the raw values exactly as EcoFlow reports them — there to look things up when a value seems odd.",
      "If a device is offline its card is dimmed and the controls are locked. A switch that does nothing would be worse than no switch.",
      "“Refresh now” forces an immediate REST sync. You rarely need it — only if you suspect a push message went missing.",
      "Changed set points take 20–50 seconds to show up in the measured input. That is the device, not FlowBridge.",
    ],
  },
  {
    titel: "History",
    punkte: [
      "Switch between 15 minutes, 1 hour and 6 hours. Samples are taken every 15 seconds.",
      "Click a legend entry to hide that curve — useful when a large power value flattens the small ones.",
      "Two axes: percent on the left (state of charge), watts on the right. The watt axis scales to the largest visible value.",
      "The history lives in memory only and starts over after a restart. For long-term analysis your MQTT broker with a database is the right place, not FlowBridge.",
    ],
  },
  {
    titel: "Energy balance",
    punkte: [
      "It shows how much of what goes in actually arrives — and what is lost as heat along the way.",
      "Direction is read from the battery, not from the input. With mains connected the unit feeds loads straight through, so the input is high while the battery is uninvolved.",
      "Loads on the output are subtracted before efficiency is calculated. Otherwise a connected appliance would look like a bad converter.",
      "The instantaneous figure necessarily fluctuates: input, output and battery power come from three different modules and arrive at different times. The efficiency in the period statistics below is the reliable one — there the offsets average out.",
      "The key finding from measurement: the charger's base draw is nearly fixed. On the River 2 Pro only 58 % reached the battery at 100 W charge power, but 87 % at 500 W. Charging slowly costs noticeably more electricity than charging fast.",
    ],
  },
  {
    titel: "Access protection",
    punkte: [
      "FlowBridge is protected by a password. Until one is set, the interface returns no data at all – not even to another program on your network.",
      "You can change the password in the settings. Doing so logs out every other signed-in device: changing a password usually means you want to lock someone out.",
      "Forgotten it? The only way back is to delete the auth block from config.yaml and restart.",
      "FlowBridge speaks HTTP. That is fine on your own network, but over the internet it belongs behind a reverse proxy with TLS – otherwise the password travels in the clear.",
      "This does not protect the MQTT side: anyone allowed to write to your broker can send commands. That belongs in your broker's access rules, which is the right place for it.",
    ],
  },
  {
    titel: "MQTT",
    punkte: [
      "Everything sits under the configured base topic (default “flowbridge”) and is published retained — a freshly connected client has the current state immediately.",
      "Per device: one complete JSON under state, one JSON per module under modules/, and every reading individually under status/. The individual topics are the most convenient ones to bind to.",
      "Commands go to cmnd/<property> — deliberately in a separate subtree so that publishing state does not immediately come back as a command.",
      "Three separate availability topics, because there are three independent ways things can fail: FlowBridge itself, the connection to the EcoFlow cloud, and the device. If the cloud drops, all values freeze — without its own topic you would not see that.",
      "Devices are announced to Home Assistant automatically (MQTT Discovery). It can be switched off in the settings, and they disappear cleanly when you do.",
      "The full topic reference is in docs/mqtt-topics.md in the project directory.",
    ],
  },
  {
    titel: "Topic export",
    punkte: [
      "The settings hold an export that saves you the typing. Every topic is listed with its type, unit and switch values – ready to import.",
      "“Topic list (CSV)” is the general version for any MQTT client: topic, direction, type, unit, sample value. Deliberately free of EisBär vocabulary.",
      "For EisBär there are two files – the payload editor (XML, the JSON profiles) and the channel editor (CSV, all channels) – plus both together as a ZIP with a short guide.",
      "The order matters: XML first, then CSV. The CSV refers to profiles that must already exist at import time. Inside the ZIP the order is part of the file names.",
      "The “Include raw module values” switch adds the five module topics. Off is the default – the raw values are there to look things up, day to day you bind the individual values. Enabling it adds about 50 nodes to the profile XML and appends “-mit-modulen” to the file name.",
      "Two things the export gets right that are easy to miss: command channels carry On=on/Off=off, and the EcoFlow flags carry On=1/Off=0. Without those a flag channel would read “off” forever, because 1 and 0 fall through every detection stage.",
      "Profiles are tied to the model, not the serial number: two identical power stations share one.",
    ],
  },
  {
    titel: "When something is not working",
    punkte: [
      "The settings contain a diagnostics package: turn on logging, reproduce the problem, download the package and send it. It contains the version, a masked configuration, the state of all three connections, the field count per device, and the log.",
      "The most recent lines are always kept in memory, even with logging switched off – otherwise the very moment the fault occurred would be missing.",
      "Keys, passwords and signatures are redacted before anything is written. Serial number and account identifier appear as “<GERAET-1>” and “<KONTO>”; the model is listed separately so the package can still be analysed.",
      "The log file is capped at 5 × 5 MB with rotation. It therefore reaches back about three to four days and will not fill your disk if you leave it on.",
      "Next to it sits the field inventory. It does not record the data stream, only per field when it first and last arrived, how often, and in what value range — that stays a few kilobytes even after weeks. This is exactly what makes it visible when an EcoFlow firmware update adds or removes fields.",
    ],
  },
  {
    titel: "What the device does not provide",
    punkte: [
      "The River 2 Pro exposes exactly 20 readable fields. Battery temperature and cycle count are not among them — they are not missing by chance, they do not exist in the interface.",
      "Set points cannot be read back on the River 2 Pro. FlowBridge therefore remembers what it last set and shows that value.",
      "EcoFlow reports “success” even when the device silently discards a command. A green result is not proof — only a visible effect is.",
      "EcoFlow provides no historical data for power stations. The history and statistics shown here are calculated by FlowBridge from live operation.",
    ],
  },
  {
    titel: "What leaves the house",
    punkte: [
      "FlowBridge talks to two counterparts: the EcoFlow cloud and your own MQTT broker. Nobody else — with one exception.",
      "The exception is the update check. At startup and every six hours it fetches the public version list from Docker Hub. Nothing about you or your power station is sent; what becomes visible there is your IP address, and that FlowBridge is running.",
      "It can be switched off under Settings → Updates. The “Check now” button still asks when you press it — a click is a decision, not a silent request.",
      "The diagnostics package and the field inventory only leave your house if you send them yourself. There is no button that transmits anything to the developer.",
    ],
  },
];

export const helpSections: Record<"de" | "en", HelpSection[]> = { de, en };

/**
 * Kurzfassung für den Über-Dialog: was FlowBridge kann.
 *
 * Bewusst knapp und ohne Superlative — jede Zeile benennt eine Fähigkeit, die
 * es tatsächlich gibt. Was nur nach Doku gebaut und nie an Hardware geprüft
 * ist (Delta 2), steht hier NICHT als Fähigkeit; das sagt der Diagnosebericht
 * an der Stelle, an der es zählt.
 */
export const aboutFeatures: Record<"de" | "en", string[]> = {
  de: [
    "Werte im Sekundentakt — FlowBridge hängt am EcoFlow-Broker, statt in Abständen nachzufragen",
    "Steuern über Weboberfläche und MQTT, beides durch denselben Code",
    "Vollständiger Topic-Baum: alles als JSON, je Modul, und jeder Messwert einzeln",
    "Home Assistant meldet sich selbst an (MQTT Discovery), abschaltbar",
    "Topic-Export für EisBär (Kanal- und Payloadeditor) sowie eine allgemeine Liste",
    "Verlauf mit Energiebilanz: Verlust und Wirkungsgrad, die sonst niemand anzeigt",
    "Drei getrennte Verfügbarkeits-Meldungen — Dienst, Cloud und Gerät fallen unabhängig aus",
    "Mehrere Speicher gleichzeitig, jeder mit eigener Kachel",
    "Zugriffsschutz mit Passwort; Schlüssel verlassen den Server nie",
    "Diagnose-Paket zum Verschicken, mit geschwärztem Protokoll",
    "Feldinventar: schreibt über Wochen mit, welche Felder EcoFlow wirklich liefert — so fällt auf, wenn ein Firmware-Update den Datenstrom ändert",
    "Dunkel und hell, Deutsch und Englisch",
  ],
  en: [
    "Readings within seconds — FlowBridge subscribes to the EcoFlow broker instead of polling",
    "Control from the web interface and over MQTT, both through the same code",
    "Complete topic tree: everything as JSON, per module, and every reading on its own",
    "Home Assistant registers itself (MQTT Discovery), can be switched off",
    "Topic export for EisBär (channel and payload editor) plus a general list",
    "History with an energy balance: the loss and efficiency nobody else shows",
    "Three separate availability signals — service, cloud and device fail independently",
    "Several power stations at once, each with its own card",
    "Password protection; your keys never leave the server",
    "A diagnostics package to send on, with the log redacted",
    "Field inventory: records over weeks which fields EcoFlow actually delivers — so a firmware update changing the data stream gets noticed",
    "Dark and light, German and English",
  ],
};
