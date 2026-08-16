import { useEffect, useState } from "react";
import { getAnalysis, resetAnalysis, setAnalysis } from "../api";
import type { Strings } from "../i18n";
import type { AnalysisState } from "../types";
import MailLink from "./MailLink";

/**
 * Feldinventar: dauerhaft mitschreiben, WAS EcoFlow über die Zeit liefert.
 *
 * Nicht zu verwechseln mit der Diagnose darüber. Die sucht einen konkreten
 * Fehler, schreibt Fließtext und rotiert nach wenigen Megabyte weg. Das
 * Inventar zählt nur je Feld mit — wann zuerst, wann zuletzt, wie oft, in
 * welchem Bereich — und bleibt deshalb über Monate wenige Kilobyte groß.
 *
 * Sichtbar wird damit, was sonst still passiert: EcoFlow spielt Firmware
 * aus, und der Datenstrom wird breiter oder schmaler.
 */
function fmtGroesse(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fmtDatum(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

export default function AnalysisSection({ t, modelle }: { t: Strings; modelle?: string[] }) {
  const [zustand, setZustand] = useState<AnalysisState | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  useEffect(() => {
    getAnalysis().then(setZustand).catch(() => undefined);
  }, []);

  async function umschalten() {
    if (!zustand) return;
    setLaeuft(true);
    setFehler(null);
    try {
      setZustand(await setAnalysis(!zustand.enabled));
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  async function zuruecksetzen() {
    setLaeuft(true);
    try {
      setZustand(await resetAnalysis());
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  const seit = fmtDatum(zustand?.started ?? null);

  return (
    <>
      <h2>{t.analysisTitle}</h2>
      <p className="fb-muted">{t.analysisHint}</p>

      <div className="fb-actions">
        <button
          type="button"
          className={`fb-toggle ${zustand?.enabled ? "fb-toggle-primary" : ""}`}
          onClick={umschalten}
          disabled={laeuft || !zustand}
        >
          {zustand?.enabled ? t.analysisOn : t.analysisOff}
        </button>

        {/* Echter Link, kein fetch: Der Browser soll die Datei selbst
            speichern, mit dem Dateinamen aus dem Header. */}
        <a className="fb-toggle" href="/api/analysis/download">
          {t.analysisDownload}
        </a>

        {!!zustand?.fields && (
          <button type="button" className="fb-toggle" onClick={zuruecksetzen} disabled={laeuft}>
            {t.analysisReset}
          </button>
        )}
      </div>

      {zustand && (
        <p className="fb-muted fb-diag-state">
          {zustand.fields > 0
            ? `${zustand.fields} ${t.analysisFields} · ${zustand.events} ${t.analysisEvents}` +
              (seit ? ` · ${t.analysisSince} ${seit}` : "") +
              (zustand.size_bytes ? ` · ${fmtGroesse(zustand.size_bytes)}` : "")
            : t.analysisEmpty}
        </p>
      )}

      <p className="fb-muted fb-diag-note">{t.analysisNote}</p>
      {/* Diese Datei ist die, die Mitwirkende HERSCHICKEN sollen - dann muss
          auch hier stehen, was drin ist. Und vor allem der Unterschied
          zwischen Knopf und Datei aus dem Ordner: Nur der Knopf ersetzt die
          Seriennummer. */}
      <p className="fb-muted fb-diag-note">{t.analysisPrivacy}</p>
      <MailLink
        t={t}
        betreff={t.mailAnalysisSubject}
        modelle={modelle}
        version={zustand?.version}
        vorlage={t.mailAnalysisBody}
      />
      {fehler && <p className="fb-status-error">{fehler}</p>}
    </>
  );
}
