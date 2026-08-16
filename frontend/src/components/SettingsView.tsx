import type { Language, Strings, Theme } from "../i18n";
import type { AppConfig, VersionInfo } from "../types";
import AnalysisSection from "./AnalysisSection";
import AppearanceSection from "./AppearanceSection";
import DiagnosticsSection from "./DiagnosticsSection";
import UpdateSection from "./UpdateSection";
import ExportSection from "./ExportSection";
import PasswordSection from "./PasswordSection";
import SetupForm from "./SetupForm";

/**
 * Einstellungsseite: getrennte Kacheln statt einer langen.
 *
 * Vorher hingen Passwort und Diagnose unten in der Einrichtungs-Kachel und
 * sahen aus, als gehörten sie dazu — und der Weg zurück zum Dashboard verlor
 * sich zwischen „Verbindung testen“ und „Speichern“.
 *
 * Der Rücksprung steht deshalb jetzt oben in der Kopfzeile: dort sucht man
 * ihn, und er ist von jeder Kachel aus gleich weit weg.
 */
export default function SettingsView({
  t,
  config,
  language,
  theme,
  onSaved,
  onBack,
  onApplyUi,
  versionInfo,
  onUpdateGeprueft,
}: {
  t: Strings;
  config: AppConfig;
  language: string;
  theme: string;
  onSaved: () => void;
  onBack: () => void;
  onApplyUi: (theme: Theme, language: Language) => void;
  versionInfo: VersionInfo | null;
  onUpdateGeprueft: (neu: VersionInfo["update"]) => void;
}) {
  // Modelle für den Betreff der Einsende-Mail. Aus der Config, nicht aus dem
  // Live-Zustand: Ein Gerät, das gerade nicht meldet, gehört trotzdem dazu -
  // vielleicht ist genau das der Grund für die Mail.
  const geraeteModelle = config.ecoflow.devices.map((d) => d.model ?? "").filter(Boolean);

  return (
    <div className="fb-settings">
      <div className="fb-settings-head">
        <h2 className="fb-settings-title">{t.settings}</h2>
        <button type="button" className="fb-toggle fb-toggle-primary" onClick={onBack}>
          ← {t.backToDashboard}
        </button>
      </div>

      {/* Links die Einrichtung (die längste Kachel), rechts die beiden
          kurzen gestapelt. Auf schmalen Fenstern wird daraus wieder eine
          Spalte — nebeneinander wären die Formularfelder dann zu schmal. */}
      <div className="fb-settings-grid">
        <SetupForm t={t} config={config} language={language} theme={theme} onSaved={onSaved} />

        <div className="fb-settings-col">
          {/* Ganz oben, direkt neben der Einrichtung: Das Aussehen ist das
              Erste, was jemand fuer sich zurechtruecken will - und es ist
              die einzige Kachel hier, die nichts kaputtmachen kann. */}
          <div className="fb-card fb-card-wide">
            <AppearanceSection
              t={t}
              theme={config.ui.theme}
              language={config.ui.language}
              onApply={onApplyUi}
            />
          </div>
          <div className="fb-card fb-card-wide">
            <PasswordSection t={t} />
          </div>
          {/* Direkt unter dem Passwort: Beides sind Entscheidungen ueber die
              Aussenwelt - wer hereindarf, und wohin FlowBridge hinausredet. */}
          <div className="fb-card fb-card-wide">
            <UpdateSection t={t} info={versionInfo} onGeprueft={onUpdateGeprueft} />
          </div>
          <div className="fb-card fb-card-wide">
            <ExportSection t={t} />
          </div>
          <div className="fb-card fb-card-wide">
            <DiagnosticsSection t={t} modelle={geraeteModelle} />
          </div>
          <div className="fb-card fb-card-wide">
            <AnalysisSection t={t} modelle={geraeteModelle} />
          </div>
        </div>
      </div>
    </div>
  );
}
