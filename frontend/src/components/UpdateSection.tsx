import { useState } from "react";
import { checkUpdateNow, saveUpdateSetting } from "../api";
import type { Strings } from "../i18n";
import type { VersionInfo } from "../types";

/**
 * Update-Prüfung: Zustand, Schalter, Knopf — und die Offenlegung dazu.
 *
 * Die Offenlegung ist hier kein Beiwerk. FlowBridge redet sonst nur mit
 * EcoFlow und dem eigenen Broker; die Update-Prüfung ist die EINZIGE
 * Verbindung zu einem Dritten. Ungefragt und unerwähnt wäre das genau die
 * Sorte stiller Heimtelefonie, über die man sich bei anderen ärgert —
 * deshalb steht daneben, was abgerufen wird, und daneben der Schalter.
 *
 * Der Knopf prüft auch bei abgeschalteter Hintergrundprüfung. Kein
 * Widerspruch: Ein Klick ist eine ausdrückliche Handlung. Wer den
 * Hintergrundabruf nicht will, soll trotzdem nachsehen können.
 */
export default function UpdateSection({
  t,
  info,
  onGeprueft,
}: {
  t: Strings;
  info: VersionInfo | null;
  onGeprueft: (neu: VersionInfo["update"]) => void;
}) {
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [an, setAn] = useState(true);

  const status = info?.update.status ?? "unknown";
  const neueste = info?.update.latest;

  async function jetztPruefen() {
    setLaeuft(true);
    setFehler(null);
    try {
      onGeprueft(await checkUpdateNow());
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  async function umschalten() {
    const neu = !an;
    setAn(neu);
    try {
      await saveUpdateSetting(neu);
    } catch (err) {
      setAn(!neu); // zurückdrehen, sonst zeigt der Schalter etwas Falsches an
      setFehler(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <h2>{t.updateTitle}</h2>
      <p className="fb-muted">{t.updateSectionHint}</p>

      <div className="fb-toggle-row">
        <span>{t.updateBackground}</span>
        <button
          type="button"
          className={`fb-switch ${an ? "fb-switch-on" : ""}`}
          onClick={umschalten}
        >
          {an ? t.on : t.off}
        </button>
      </div>

      <p className="fb-muted fb-diag-state">
        {status === "update"
          ? `${t.updateAvailable}: ${neueste ?? ""}`
          : status === "current"
            ? t.upToDate
            : t.updateUnknown}
        {info?.update.detail ? ` · ${info.update.detail}` : ""}
      </p>

      <div className="fb-actions">
        <button type="button" className="fb-toggle" onClick={jetztPruefen} disabled={laeuft}>
          {laeuft ? t.updateChecking : t.updateCheckNow}
        </button>
      </div>

      <p className="fb-muted fb-diag-note">{t.updatePrivacy}</p>
      {fehler && <p className="fb-status-error">{fehler}</p>}
    </>
  );
}
