import { useState } from "react";
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
 * Einstellungsseite in Tabs.
 *
 * Vorher hingen Passwort und Diagnose unten in der Einrichtungs-Kachel und
 * sahen aus, als gehörten sie dazu — der Weg zurück zum Dashboard verlor sich
 * zwischen „Verbindung testen“ und „Speichern“. Der Rücksprung steht deshalb
 * oben in der Kopfzeile, von jeder Kachel gleich weit weg.
 *
 * Danach wuchs die Seite weiter: sechs Kacheln in zwei Spalten, gut zwei
 * Bildschirmhöhen. Dirk nannte es am 24.08.2026 eine „Scrollorgie“, und das
 * traf es — man scrollte an Diagnose und Feldinventar vorbei, um an das
 * Passwort zu kommen.
 *
 * Vier Tabs statt einer Rolle. Die Einteilung folgt der Frage, WARUM man
 * herkommt:
 *
 *   Einrichtung   — womit FlowBridge redet (EcoFlow, Geräte, Broker)
 *   Darstellung   — wie es aussieht und wer hereindarf
 *   Updates       — ob es aktuell ist
 *   Export/Daten  — was man herausträgt (Topics, Diagnose, Feldinventar)
 *
 * Kein Tab-Zustand in der URL: Die Seite hat keine Routen, und ein
 * Neuladen soll bei der Einrichtung landen — dort will man hin, wenn etwas
 * nicht geht.
 */

type Tab = "setup" | "darstellung" | "updates" | "daten";
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
  const [tab, setTab] = useState<Tab>("setup");

  const tabs: { id: Tab; label: string }[] = [
    { id: "setup", label: t.setupTitle },
    { id: "darstellung", label: t.tabAppearance },
    { id: "updates", label: t.updateTitle },
    { id: "daten", label: t.tabData },
  ];

  return (
    <div className="fb-settings">
      <div className="fb-settings-head">
        <h2 className="fb-settings-title">{t.settings}</h2>
        <button type="button" className="fb-toggle fb-toggle-primary" onClick={onBack}>
          ← {t.backToDashboard}
        </button>
      </div>

      <div className="fb-tabs fb-settings-tabs" role="tablist">
        {tabs.map((eintrag) => (
          <button
            key={eintrag.id}
            type="button"
            role="tab"
            aria-selected={tab === eintrag.id}
            className={`fb-tab ${tab === eintrag.id ? "fb-tab-active" : ""}`}
            onClick={() => setTab(eintrag.id)}
          >
            {eintrag.label}
          </button>
        ))}
      </div>

      {tab === "setup" && (
        <SetupForm
          t={t}
          config={config}
          language={language}
          theme={theme}
          onSaved={onSaved}
          alsAbschnitt
        />
      )}

      {/* Zwei kurze Kacheln nebeneinander statt untereinander - zusammen
          fuellen sie knapp eine Bildschirmhoehe. */}
      {tab === "darstellung" && (
        <div className="fb-settings-grid fb-settings-grid-gleich">
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
        </div>
      )}

      {tab === "updates" && (
        <div className="fb-card fb-card-wide">
          <UpdateSection t={t} info={versionInfo} onGeprueft={onUpdateGeprueft} />
        </div>
      )}

      {/* Die drei langen Kacheln. Export links, die beiden Mitschriften
          rechts - sie gehoeren zusammen: beide schreiben mit, beide werden
          per Mail verschickt, beide haben einen Hinweis zum Datenschutz. */}
      {tab === "daten" && (
        <div className="fb-settings-grid fb-settings-grid-gleich">
          <div className="fb-card fb-card-wide">
            <ExportSection t={t} />
          </div>
          <div className="fb-settings-col">
            <div className="fb-card fb-card-wide">
              <DiagnosticsSection t={t} modelle={geraeteModelle} />
            </div>
            <div className="fb-card fb-card-wide">
              <AnalysisSection t={t} modelle={geraeteModelle} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
