import { useState } from "react";
import { login, setPassword } from "../api";
import type { Strings } from "../i18n";
import Logo from "./Logo";

/**
 * Anmeldung – und beim allerersten Start das Vergeben des Passworts.
 *
 * Beide Fälle in einer Komponente, weil sie sich nur in einem Feld und dem
 * aufgerufenen Endpunkt unterscheiden. Der Ersteinrichtungs-Fall verlangt eine
 * Wiederholung: ein vertipptes Passwort, das niemand kennt, sperrt sonst den
 * eigenen Speicher aus.
 */
export default function LoginForm({
  t,
  configured,
  minLength,
  onDone,
}: {
  t: Strings;
  configured: boolean;
  minLength: number;
  onDone: () => void;
}) {
  const [passwort, setPasswort] = useState("");
  const [wiederholung, setWiederholung] = useState("");
  const [fehler, setFehler] = useState<string | null>(null);
  const [laeuft, setLaeuft] = useState(false);

  async function absenden(e: React.FormEvent) {
    e.preventDefault();
    setFehler(null);

    if (!configured) {
      if (passwort.length < minLength) {
        setFehler(t.passwordTooShort.replace("{n}", String(minLength)));
        return;
      }
      if (passwort !== wiederholung) {
        setFehler(t.passwordMismatch);
        return;
      }
    }

    setLaeuft(true);
    try {
      if (configured) await login(passwort);
      else await setPassword(passwort);
      onDone();
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setLaeuft(false);
    }
  }

  return (
    <div className="fb-login">
      <form className="fb-card fb-login-card" onSubmit={absenden}>
        <div className="fb-modal-brand">
          <Logo />
          <p className="fb-modal-subtitle">{t.tagline}</p>
        </div>

        <h2>{configured ? t.loginTitle : t.firstRunTitle}</h2>
        <p className="fb-muted">{configured ? t.loginHint : t.firstRunHint}</p>

        <label className="fb-field">
          <span>{t.password}</span>
          <input
            type="password"
            value={passwort}
            autoFocus
            autoComplete={configured ? "current-password" : "new-password"}
            onChange={(e) => setPasswort(e.target.value)}
          />
        </label>

        {!configured && (
          <label className="fb-field">
            <span>{t.passwordRepeat}</span>
            <input
              type="password"
              value={wiederholung}
              autoComplete="new-password"
              onChange={(e) => setWiederholung(e.target.value)}
            />
          </label>
        )}

        {fehler && <p className="fb-status-error">{fehler}</p>}

        <div className="fb-actions">
          <button
            className="fb-toggle fb-toggle-primary"
            type="submit"
            disabled={laeuft || !passwort}
          >
            {laeuft ? "…" : configured ? t.loginButton : t.firstRunButton}
          </button>
        </div>

        {!configured && <p className="fb-muted fb-login-note">{t.firstRunNote}</p>}
      </form>
    </div>
  );
}
