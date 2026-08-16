import { useState } from "react";
import { setPassword } from "../api";
import type { Strings } from "../i18n";

/**
 * Passwort ändern – eigener Abschnitt in den Einstellungen.
 *
 * Bewusst getrennt vom Speichern der übrigen Einstellungen: ein Passwort
 * versehentlich mitzuändern, weil man nur die Broker-IP anpassen wollte, wäre
 * die unangenehmste Art, sich auszusperren.
 */
export default function PasswordSection({ t }: { t: Strings }) {
  const [aktuell, setAktuell] = useState("");
  const [neu, setNeu] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  async function aendern() {
    setFehler(null);
    setMeldung(null);
    if (neu !== wiederholung) {
      setFehler(t.passwordMismatch);
      return;
    }
    setLaeuft(true);
    try {
      await setPassword(neu, aktuell);
      setMeldung(t.passwordChanged);
      setAktuell("");
      setNeu("");
      setWiederholung("");
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <>
      <h2>{t.changePassword}</h2>
      <label className="fb-field">
        <span>{t.currentPassword}</span>
        <input
          type="password"
          value={aktuell}
          autoComplete="current-password"
          onChange={(e) => setAktuell(e.target.value)}
        />
      </label>
      <label className="fb-field">
        <span>{t.newPassword}</span>
        <input
          type="password"
          value={neu}
          autoComplete="new-password"
          onChange={(e) => setNeu(e.target.value)}
        />
      </label>
      <label className="fb-field">
        <span>{t.passwordRepeat}</span>
        <input
          type="password"
          value={wiederholung}
          autoComplete="new-password"
          onChange={(e) => setWiederholung(e.target.value)}
        />
      </label>
      <div className="fb-actions">
        <button
          type="button"
          className="fb-toggle"
          onClick={aendern}
          disabled={laeuft || !aktuell || !neu}
        >
          {laeuft ? "…" : t.changePassword}
        </button>
      </div>
      {meldung && <p className="fb-status-ok">{meldung}</p>}
      {fehler && <p className="fb-status-error">{fehler}</p>}
    </>
  );
}
