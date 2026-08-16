# --- Stage 1: Frontend-Build ---
FROM node:22-slim AS frontend-build
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python-Runtime ---
FROM python:3.14.6-slim

# image.source muss auf ein OEFFENTLICH erreichbares Repository zeigen.
# Zwei Gruende:
#
#   1. FlowBridge steht unter AGPL. Wer das Abbild hat, muss an den Quelltext
#      kommen - und dieses Etikett ist die uebliche Stelle, an der man nachsieht
#      (`docker inspect`). Ein Verweis auf ein Repository, das eine Anmeldung
#      verlangt, waere so gut wie keiner.
#   2. Registries haengen ein Paket anhand dieses Labels an das Repository
#      statt an das Konto. Bei GHCR taucht es sonst nur unter dem Profil auf
#      und die Zugriffseinstellungen des Repositorys greifen nicht.
LABEL org.opencontainers.image.source="https://github.com/CheetahLab/FlowBridge" \
      org.opencontainers.image.title="FlowBridge" \
      org.opencontainers.image.description="MQTT-Bruecke fuer mobile Energiespeicher von ECOFLOW" \
      org.opencontainers.image.vendor="Dirk Hofher" \
      org.opencontainers.image.licenses="AGPL-3.0-only"

WORKDIR /app

COPY requirements.txt .
# apt-get upgrade IST hier gewollt, obwohl es vielerorts als schlechter Stil
# gilt.
#
# Der uebliche Einwand: Zwei Builds aus derselben Quelle ergeben zu
# verschiedenen Zeitpunkten verschiedene Abbilder. Stimmt - und ist hier der
# geringere Preis. FlowBridge geht an Fremde; ein Abbild, das bekannte Luecken
# mitschleppt, nur weil das Basis-Abbild aelter ist als das Debian-Archiv,
# waere schlechter als eines, das sich nicht byteweise nachbauen laesst.
#
# Gemessen am 16.08.2026: Das Archiv fuehrte util-linux 2.41.5-0+deb13u1,
# python:3.14.6-slim brachte 2.41-5 mit - neun Pakete veraltet, zwei davon mit
# CVE (CVE-2026-13595, CVE-2026-27456). Ohne diese Zeile bliebe das so, bis
# jemand das Basis-Abbild anhebt und es ueberhaupt bemerkt.
#
# Der zweite Grund wiegt schwerer: perl-base traegt derzeit vier ungefixte
# Funde (2 kritisch, 2 hoch, Debian-Bug #1142037). Sobald Debian sie patcht,
# holt ein gewoehnlicher Neubau den Fix von selbst - sonst haengt es daran,
# dass ich es mitbekomme.
#
# Nachvollziehbar bleibt es trotzdem: Jede Fassung liegt unter einer
# unveraenderlichen Versionsmarke mit festem Digest.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY --from=frontend-build /build/dist/ frontend/dist/
# Versionsnummer: src/version.py liest sie aus /app/VERSION. Ohne diese Zeile
# meldete der Container "unbekannt" - im Container gibt es kein git, aus dem
# man sie nachtraeglich ableiten koennte.
COPY VERSION .
# Die Lizenz verlangt, dass ihr Text jeder Kopie beiliegt - und das Abbild
# IST eine Kopie. Bei der AGPL gilt das noch strenger als vorher bei MIT:
# Wer eine veraenderte Fassung betreibt, muss den Nutzern den Quelltext
# anbieten koennen, und der Vermerk ist der Anfang dieser Kette.
# NOTICE.md traegt den Urhebervermerk und die Ausnahme fuer Name und Logo,
# THIRD-PARTY-NOTICES.md die Vermerke der mitgelieferten Fremdbibliotheken.
COPY LICENSE NOTICE.md THIRD-PARTY-NOTICES.md ./

RUN adduser --uid 1000 --disabled-password --gecos "" appuser

# Bewusst KEIN "USER appuser" mehr: Der Einstiegspunkt braucht kurz
# root-Rechte, um dem gemounteten Datenordner die passenden Rechte zu geben -
# sonst scheitert FlowBridge auf einer Synology daran, dass der Ordner dem
# NAS-Benutzer gehoert. Danach gibt er die Rechte ab und startet uvicorn als
# Benutzer 1000; ab dort laeuft kein Anwendungscode mehr als root.
# setpriv liegt im Basis-Abbild bereits vor (util-linux), es braucht also
# weder gosu noch ein zusaetzliches Paket.
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Im Abbild festgelegt, damit Einstiegspunkt und Anwendung DENSELBEN Ordner
# meinen. Ohne diese Zeile richtet der Einstiegspunkt /config her, waehrend
# die Anwendung auf ihren Entwicklungs-Standard im Repo-Root zielt - und
# beschwert sich dann ueber ein /app, das ihr gar nicht gehoert. In den
# compose-Dateien steht der Wert weiterhin, das schadet nicht.
ENV FLOWBRIDGE_CONFIG=/config/config.yaml

WORKDIR /app/src
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
