<div align="center">

**[English](CHANGELOG.md) · Deutsch**

</div>

# Änderungen

Jede veröffentlichte Fassung steht hier mit dem, was sich geändert hat — und wo
es sich lohnt, mit dem Grund dahinter.

Die Versionsnummer ist `JAHR.MM.TT-ZÄHLER`, der Zähler läuft innerhalb eines
Tages. Nicht zu jeder Nummer gibt es ein Abbild: Gebaut wird nur, wenn sich
etwas ändert, das im Container landet. Eine reine Doku-Änderung ergäbe ein
identisches Abbild und bei allen einen Update-Hinweis, der nichts bringt.

Die Fassung deiner Installation steht oben rechts in der Oberfläche.

---

## 2026.08.27-02

### Neu

- **Abbilder für ARM64.** Bisher wurde nur `linux/amd64` gebaut — richtig für
  die NAS, auf der das hier entstanden ist, aber es schloss jedes ARM-Gerät
  aus: Raspberry Pi, die kleinen Synology-Modelle, Apple Silicon. Beide
  Architekturen liegen jetzt unter derselben Marke; der eigene Rechner nimmt
  sich die passende, an der compose-Datei ändert sich nichts. Für 32 Bit
  (`armhf`) gibt es kein Abbild.

  Beide werden vor der Veröffentlichung wirklich gestartet und befragt — ein
  ungetestetes Abbild für ein Gerät, das der Autor selbst nicht hat, ist ein
  Versprechen, das beim Fremden platzt.

---

## 2026.08.25-03

### Neu

- **Die Änderungen stehen jetzt im Programm.** „Was ist neu?" öffnet ein
  Fenster statt eines Browser-Tabs, und die laufende Fassung ist darin
  markiert — die Antwort auf „wo stehe ich in dieser Liste eigentlich?".
  Erreichbar an zwei Stellen: in der Kopfzeile, sobald ein Update ansteht,
  und dauerhaft unter Einstellungen › Updates.
- **Unter Einstellungen › Updates steht jetzt die laufende Versionsnummer.**
  Vorher stand dort „Up-to-date", aber nicht, worauf — die Nummer war nur
  eine Ansicht weiter zu finden.

Der Text wird beim Öffnen aus dem Netz geholt und nicht mitgeliefert. Anders
ginge es nicht: Ein eingebautes Protokoll wäre auf dem Stand der installierten
Fassung eingefroren und könnte gerade die Frage nicht beantworten, die es
auslöst — was bringt das Update, das man noch nicht hat. Geholt wird aus dem
Browser und nur auf Klick, also dieselbe Verbindung, die ein Link auch
aufgebaut hätte. Ohne Netz nennt das Fenster den Grund und den Link.

---

## 2026.08.25-02

### Geändert

- **Die Kopfzeile ist eine Werkzeugleiste geworden.** Abmelden war der letzte
  Knopf mit Beschriftung und damit der einzige, der aus der Reihe fiel — jetzt
  trägt er ein Symbol wie seine Nachbarn. Alle Knöpfe sind gleich groß und
  quadratisch, Mond und Sonne sind Zeichnungen statt Emoji (die setzen manche
  Systeme farbig, dann leuchtet ein Klecks in einer Reihe grauer Striche).
- **„Up-to-date" ist ein grüner Haken.** Dieser Zustand ist die Abwesenheit
  einer Nachricht; dafür genügt ein Zeichen. Sobald es etwas zu tun gibt, gibt
  es wieder etwas zu lesen: Bei verfügbarem Update steht die Versionsnummer
  da, denn genau die wird gebraucht.
- **Eigene Tooltips statt der Browser-Blase.** Die native erscheint erst nach
  etwa einer Sekunde und lässt sich nicht gestalten. Auf Geräten ohne
  Mauszeiger entfällt sie — dort ließe sie sich nur durch Antippen auslösen,
  und das löst zugleich die Aktion aus.

### Behoben

- Die Beschriftungen von Sprach- und Design-Knopf für Screenreader waren fest
  deutsch, unabhängig von der eingestellten Sprache.

---

## 2026.08.25-01

### Behoben

- **Nach der Erneuerung des Melde-Abonnements kam jede Nachricht doppelt.**
  Aufgefallen bei der ersten planmäßigen Erneuerung nach zwölf Stunden: 799
  Nutzlasten kamen zweimal an, jeweils im selben Millisekundenwert. Die
  Ursache war die Reihenfolge beim Verbindungsabbau — der Netzwerk-Thread
  wurde angehalten, *bevor* das Abmelde-Paket abgeschickt war, das damit nie
  hinausging. Der Broker ließ die alte Sitzung stehen und legte sie beim
  Neuverbinden mit der neuen zusammen, ihr Abonnement inbegriffen. Die
  angezeigten Werte waren dadurch nicht falsch — es waren identische Kopien —,
  aber es wäre alle zwölf Stunden eine weitere hinzugekommen.

  Zusätzlich abgesichert: Die beiden Wege, auf denen ein Topic abonniert wird,
  können sich nicht mehr gegenseitig doppeln.

---

## 2026.08.24-21

### Neu

- **Lizenzwechsel auf die Apache-Lizenz 2.0.** Benutzen, betreiben, anpassen,
  weitergeben und einbauen — frei, auch gewerblich und in geschlossenen
  Produkten. Zu erfüllen sind die drei Auflagen aus Abschnitt 4. Gerade im
  Smarthome-Bereich soll die Einbindung an der Lizenz nicht scheitern.
- **Abschnitt „Was du sonst nicht siehst" in beiden READMEs.** Der Wandler
  einer Powerstation kostet mehr, als die Herstellerapp erkennen lässt —
  nachgemessen an einer RIVER 2 Pro, mit den Messpunkten, der daraus
  angepassten Geraden und einer ausdrücklichen Grenze dessen, was die Zahlen
  hergeben.
- **Screenshots der laufenden Oberfläche** in hell und dunkel, deutsch und
  englisch.

### Geändert

- **Die Oberfläche wurde durchgesehen und aufgeräumt.** Kacheln brechen
  sauber um, die Gerätekarte hat eine Abschnittsüberschrift „Steuerung" und
  eine gestraffte Reihenfolge, Grenzwerte und Reserve stehen paarweise
  nebeneinander, die Einstellungen liegen in vier Reitern statt in einer
  langen Spalte, und die Reglerskala ist beschriftet.
- **Der Verlauf skaliert nicht mehr mit der Fensterbreite.** Auf einem
  breiten Bildschirm wurden Schrift und Linien mitvergrößert; jetzt bleibt
  die Zeichnung in ihrer Größe und nutzt den Platz.
- **Die Inhaltsbreite folgt der Ansicht** — das Dashboard darf breiter
  stehen als die Einstellungen, ohne dass die Kopfzeile verrutscht.
- **Ein Messwert gilt fünf Minuten als aktuell**, vorher zwei. Zwei Minuten
  waren für Felder, die das Gerät ohnehin selten meldet, zu streng.
- **Die Einrichtung erklärt sich besser:** der Prüfknopf sitzt bei den
  EcoFlow-Zugängen statt bei MQTT, das erkannte Modell wird benannt, und ein
  Wegweiser führt zum EcoFlow-Entwicklerportal, wo die Schlüssel herkommen.
- **Über 100 % Wirkungsgrad wird nicht mehr angezeigt.** Wo Eingang und
  Ausgang nicht im selben Moment gemessen wurden, steht jetzt „–" statt einer
  Zahl, die zufällig entsteht.

---

## 2026.08.24-05

Die Fassung, die den Kern des Projekts geradezog.

### Neu

- **Jeder Messwert führt sein Alter mit.** Über den Kacheln steht, wie alt
  die jüngste Messung ist; einzelne veraltete Werte werden gekennzeichnet.
  Der Grund ist unbequem, aber wichtig: Ein unveränderter Wert ist ohne
  Altersangabe mehrdeutig — er kann „stabil" heißen oder „seit zwölf Minuten
  tot". Für eine Regelung, die darauf reagiert, ist das der Unterschied
  zwischen richtig und gefährlich.
- **Der Verlauf zeichnet Lücken statt Linien.** Werte, die älter sind als die
  Schwelle, werden nicht mehr fortgeschrieben. Eine durchgezogene Linie über
  eine tote Strecke sieht aus wie Wissen.
- **Das Melde-Abonnement wird planmäßig erneuert.** EcoFlow richtet die
  Melderate des Geräts ein, wenn sich ein Client anmeldet — und diese
  Einrichtung läuft ab. Gemessen: nach rund 37 Stunden fiel der Abstand
  zwischen zwei Meldungen vom Median 3 Sekunden auf 899. FlowBridge meldet
  sich deshalb alle zwölf Stunden neu an, und zusätzlich sofort, wenn die
  Meldungen tatsächlich einbrechen.

### Behoben

- **`quota/all` galt fälschlich als zweiter Messweg.** Es ist die Kopie des
  letzten Push. Bleibt der Push aus, liefert die Abfrage unbegrenzt lange
  dieselben alten Zahlen — erfolgreich, mit HTTP 200, mit jedem Aufruf frisch
  gestempelt. Ein gezielter Feldabruf wurde als Alternative gemessen und
  verworfen: in 40 Runden null Unterschied.

---

## 2026.08.17-04

Nur Quelltext und Anleitungen, kein neues Abbild.

- Synology-Anleitung zweisprachig, als HTML und PDF im Repository.
- Zwei Installationswege beschrieben.

---

## 2026.08.16

Erste öffentliche Fassung.

### Neu

- Live-Werte über MQTT-Push statt Abfragen im Takt.
- Steuerung von AC-Ausgang, 12-V-Ausgang, X-Boost, Ladelimit, Entladelimit,
  Ladeleistung und Ladepause — über die Oberfläche oder über MQTT.
- Home-Assistant-Discovery, Topic-Export für EisBär SCADA, Feldinventar und
  ein Diagnosepaket mit geschwärzten Schlüsseln.
- Oberfläche und Anleitungen auf Deutsch und Englisch.
- Fehler- und Gerätevorlagen für Issues.

### Behoben

- **Ein AC-Befehl verstellte stillschweigend X-Boost, Ausgangsspannung und
  Frequenz mit.** Wer die Ladeleistung änderte, änderte ungewollt drei
  weitere Einstellungen.
- Der Bau des Abbilds aktualisiert die Debian-Pakete des Basis-Abbilds, statt
  bekannte Lücken mitzuschleppen.
