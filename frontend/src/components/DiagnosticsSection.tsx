import { useEffect, useState } from "react";
import { clearDiagnostics, getDiagnostics, setDiagnostics } from "../api";
import type { Strings } from "../i18n";
import type { DiagnosticsState } from "../types";
import MailLink from "./MailLink";

/**
 * Diagnose-Paket: Protokoll ein-/ausschalten und herunterladen.
 *
 * Der Download ist der eigentliche Zweck – FlowBridge läuft bei Freunden, und
 * „geht nicht“ ist als Fehlerbeschreibung wenig hilfreich. Das Paket enthält
 * Version, maskierte Konfiguration, Verbindungszustand, Feldzahl je Gerät und
 * das geschwärzte Protokoll.
 */
function fmtGroesse(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function DiagnosticsSection({ t, modelle }: { t: Strings; modelle?: string[] }) {
  const [zustand, setZustand] = useState<DiagnosticsState | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  useEffect(() => {
    getDiagnostics().then(setZustand).catch(() => undefined);
  }, []);

  async function umschalten() {
    if (!zustand) return;
    setLaeuft(true);
    setFehler(null);
    try {
      setZustand(await setDiagnostics(!zustand.enabled));
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  async function leeren() {
    setLaeuft(true);
    try {
      setZustand(await clearDiagnostics());
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <>
      <h2>{t.diagnosticsTitle}</h2>
      <p className="fb-muted">{t.diagnosticsHint}</p>

      <div className="fb-actions">
        <button
          type="button"
          className={`fb-toggle ${zustand?.enabled ? "fb-toggle-primary" : ""}`}
          onClick={umschalten}
          disabled={laeuft || !zustand}
        >
          {zustand?.enabled ? t.diagnosticsOn : t.diagnosticsOff}
        </button>

        {/* Bewusst ein echter Link und kein fetch: der Browser soll die Datei
            selbst speichern, mit dem Dateinamen aus dem Header. */}
        <a className="fb-toggle" href="/api/diagnostics/download">
          {t.diagnosticsDownload}
        </a>

        {!!zustand?.size_bytes && (
          <button type="button" className="fb-toggle" onClick={leeren} disabled={laeuft}>
            {t.diagnosticsClear}
          </button>
        )}
      </div>

      {zustand && (
        <p className="fb-muted fb-diag-state">
          {zustand.enabled ? `${t.diagnosticsFile}: ${zustand.path}` : t.diagnosticsRingOnly}
          {zustand.size_bytes > 0 && ` · ${fmtGroesse(zustand.size_bytes)}`}
          {` · ${zustand.buffered_lines} ${t.diagnosticsLines}`}
        </p>
      )}

      {/* Zwei getrennte Absätze, nicht einer: "was NICHT drin ist" und "was
          drin ist" sind zwei verschiedene Aussagen. In einem Block gelesen
          bleibt von beiden nur ein Eindruck hängen – und der Sinn der Sache
          ist, dass jemand vor dem Abschicken genau weiß, was er verschickt.
          Eine Schwärzung, die man nicht nachlesen kann, beruhigt niemanden. */}
      <p className="fb-muted fb-diag-note">{t.diagnosticsPrivacy}</p>
      <p className="fb-muted fb-diag-note">{t.diagnosticsContents}</p>
      <MailLink
        t={t}
        betreff={t.mailDiagnosticsSubject}
        modelle={modelle}
        version={zustand?.version}
        vorlage={t.mailDiagnosticsBody}
      />
      {fehler && <p className="fb-status-error">{fehler}</p>}
    </>
  );
}
