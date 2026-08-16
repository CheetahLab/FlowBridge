import { useState } from "react";
import { saveUi } from "../api";
import type { Language, Strings, Theme } from "../i18n";

/**
 * Darstellungs-Vorgabe dieser Installation.
 *
 * Die Schalter im Kopf der Seite gelten nur fuer den Browser, in dem sie
 * gedrueckt werden (localStorage). Das ist richtig so - zwei Leute duerfen
 * dieselbe FlowBridge verschieden ansehen. Nur fehlte bisher der Startpunkt:
 * Ein neuer Browser, das Handy, ein geleerter Verlauf - ueberall stand wieder
 * Dunkel/Deutsch, egal was man vorher eingestellt hatte.
 *
 * Hier steht deshalb, womit ein Browser ANFAENGT, der FlowBridge zum ersten
 * Mal sieht. Wer danach oben umschaltet, ueberstimmt das fuer sich.
 */
export default function AppearanceSection({
  t,
  theme,
  language,
  onApply,
}: {
  t: Strings;
  /** Aktuelle Vorgabe aus der Konfiguration - nicht das, was der Kopf zeigt. */
  theme: Theme;
  language: Language;
  /** Uebernimmt die neue Vorgabe zugleich in diesem Browser. */
  onApply: (theme: Theme, language: Language) => void;
}) {
  const [entwurfTheme, setEntwurfTheme] = useState<Theme>(theme);
  const [entwurfSprache, setEntwurfSprache] = useState<Language>(language);
  const [speichert, setSpeichert] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  async function speichern() {
    setSpeichert(true);
    setFehler(null);
    setMeldung(null);
    try {
      await saveUi(entwurfTheme, entwurfSprache);
      // Sofort anwenden. Eine gespeicherte Vorgabe, die man erst nach dem
      // naechsten Neuladen sieht, fuehlt sich an, als haette sie nicht
      // funktioniert.
      onApply(entwurfTheme, entwurfSprache);
      setMeldung(t.appearanceSaved);
    } catch (err) {
      setFehler(err instanceof Error ? err.message : String(err));
    } finally {
      setSpeichert(false);
    }
  }

  const unveraendert = entwurfTheme === theme && entwurfSprache === language;

  return (
    <>
      <h2 className="fb-card-title">{t.appearanceTitle}</h2>
      <p className="fb-muted fb-field-hint">{t.appearanceHint}</p>

      <label className="fb-field">
        <span>{t.appearanceTheme}</span>
        <select
          value={entwurfTheme}
          onChange={(e) => setEntwurfTheme(e.target.value as Theme)}
        >
          <option value="dark">{t.themeDark}</option>
          <option value="light">{t.themeLight}</option>
        </select>
      </label>

      <label className="fb-field">
        <span>{t.appearanceLanguage}</span>
        <select
          value={entwurfSprache}
          onChange={(e) => setEntwurfSprache(e.target.value as Language)}
        >
          <option value="de">Deutsch</option>
          <option value="en">English</option>
        </select>
      </label>

      <div className="fb-actions">
        <button
          type="button"
          className="fb-toggle fb-toggle-primary"
          onClick={speichern}
          disabled={speichert || unveraendert}
        >
          {speichert ? t.saving : t.save}
        </button>
      </div>

      {meldung && <p className="fb-muted fb-diag-state">{meldung}</p>}
      {fehler && <p className="fb-status-error">{fehler}</p>}
    </>
  );
}
