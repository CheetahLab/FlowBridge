#!/bin/sh
# FlowBridge – Einstiegspunkt.
#
# Loest das Problem, an dem auf einer Synology sonst jeder haengenbleibt:
# Der gemountete Datenordner gehoert dem NAS-Benutzer, FlowBridge laeuft als
# Benutzer 1000 – und darf dort nicht schreiben. Der Container startete dann
# in einer Dauerschleife neu, ohne dass im Browser irgendetwas davon zu sehen
# war.
#
# Verbreitete Abbilder (Mosquitto, Vaultwarden) haben das Problem nicht, weil
# sie schlicht durchgehend als root laufen – und damit auf einem Bind-Mount
# auch auf der NAS alles duerfen. Das ist bequem, aber es verschenkt die
# einzige echte Absicherung, die ein Container mitbringt.
#
# Hier der uebliche Mittelweg (so machen es auch die linuxserver.io-Abbilder):
# kurz als root die Rechte am Datenordner setzen, die Rechte dann ABGEBEN und
# FlowBridge selbst als gewoehnlicher Benutzer ausfuehren. Ab dem exec laeuft
# kein Zeilencode mehr mit root-Rechten.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

konfig="${FLOWBRIDGE_CONFIG:-/config/config.yaml}"
datenordner=$(dirname "$konfig")

# Hat jemand im compose ausdruecklich "user:" gesetzt, laeuft dieses Skript
# gar nicht als root. Dann nichts anfassen – der Wunsch ist eindeutig.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

mkdir -p "$datenordner" 2>/dev/null || true

# Nur anfassen, wenn es noetig ist. Ein chown bei jedem Start waere zwar
# harmlos, aber es aendert Zeitstempel und verschleiert im Zweifel, wer
# zuletzt wirklich etwas geaendert hat.
besitzer=$(stat -c '%u:%g' "$datenordner" 2>/dev/null || echo "?")
if [ "$besitzer" != "$PUID:$PGID" ]; then
    if chown -R "$PUID:$PGID" "$datenordner" 2>/dev/null; then
        echo "FlowBridge: Datenordner $datenordner auf $PUID:$PGID gesetzt."
    else
        # Kein Abbruch: FlowBridge meldet gleich selbst im Klartext, dass es
        # nicht schreiben kann. Hier zu sterben brachte nur die Schleife
        # zurueck, die dieses Skript gerade abschaffen soll.
        echo "FlowBridge: WARNUNG – Rechte an $datenordner lassen sich nicht setzen." >&2
        echo "FlowBridge: Ist der Ordner schreibgeschuetzt eingebunden (:ro)?" >&2
    fi
fi

# --clear-groups: sonst behielte der Prozess die Gruppen von root.
exec setpriv --reuid "$PUID" --regid "$PGID" --clear-groups "$@"
