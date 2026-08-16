import { useEffect, useState } from "react";
import { checkUpdateNow, getAuthState, getConfig, getVersion, logout } from "./api";
import AboutDialog from "./components/AboutDialog";
import Dashboard from "./components/Dashboard";
import HealthBar from "./components/HealthBar";
import HelpDialog from "./components/HelpDialog";
import LoginForm from "./components/LoginForm";
import Logo from "./components/Logo";
import SettingsView from "./components/SettingsView";
import SetupForm from "./components/SetupForm";
import StorageError from "./components/StorageError";
import { strings, type Language, type Theme } from "./i18n";
import type { AppConfig, AuthState, VersionInfo } from "./types";

type View = "loading" | "setup" | "dashboard" | "settings";
type Dialog = "about" | "help" | null;

// Die Version aendert sich nur beim Neustart - stuendlich nachsehen genuegt.
// Sobald die Update-Quelle steht, ist das zugleich der Prueftakt.
const VERSION_POLL_MS = 60 * 60 * 1000;

/** Wert im Browser merken - und mitteilen, ob dort schon einer STAND.
 *
 * Das dritte Rueckgabefeld ist der ganze Punkt: Der Effekt unten schreibt
 * sofort nach dem Mounten in den localStorage. Wer erst danach (wenn die
 * Konfiguration geladen ist) nachsaehe, ob der Browser schon eine Vorliebe
 * hat, faende immer eine - naemlich die gerade selbst geschriebene. Die
 * serverseitige Vorgabe kaeme nie zum Zug.
 */
function usePersistentState<T extends string>(key: string, initial: T) {
  const [warGespeichert] = useState(() => localStorage.getItem(key) !== null);
  const [value, setValue] = useState<T>(
    () => (localStorage.getItem(key) as T) ?? initial
  );
  useEffect(() => {
    localStorage.setItem(key, value);
  }, [key, value]);
  return [value, setValue, warGespeichert] as const;
}

export default function App() {
  // Dark/DE ist der Notnagel, falls weder Browser noch Server etwas sagen -
  // Dunkel ist der Grundton der Marke. Die Reihenfolge ist:
  // Browser-Vorliebe > Vorgabe aus der config.yaml > dieser Wert.
  const [theme, setTheme, themeAusBrowser] = usePersistentState<Theme>("fb-theme", "dark");
  const [lang, setLang, spracheAusBrowser] = usePersistentState<Language>("fb-lang", "de");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [view, setView] = useState<View>("loading");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [versionInfo, setVersionInfo] = useState<VersionInfo | null>(null);
  const [authState, setAuthState] = useState<AuthState | null>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // Vorgabe aus der config.yaml uebernehmen - aber nur fuer einen Browser,
  // der noch nie selbst umgeschaltet hat. Sonst wuerde die Einstellung eines
  // zweiten Nutzers dem ersten bei jedem Laden seine wegnehmen.
  useEffect(() => {
    if (!config) return;
    if (!themeAusBrowser) setTheme(config.ui.theme);
    if (!spracheAusBrowser) setLang(config.ui.language);
    // Absichtlich nur an `config` haengend: Es geht um den EINEN Moment, in
    // dem die Konfiguration eintrifft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function reloadConfig() {
    const cfg = await getConfig();
    setConfig(cfg);
    setView(cfg.ecoflow.access_key && cfg.ecoflow.secret_key ? "dashboard" : "setup");
    return cfg;
  }

  // Erst den Anmeldezustand klaeren - vorher hat es keinen Sinn, Daten zu
  // holen, die ohnehin mit 401 beantwortet wuerden.
  async function reloadAuth() {
    const a = await getAuthState();
    setAuthState(a);
    if (a.authenticated) await reloadConfig().catch(() => setView("setup"));
    return a;
  }

  useEffect(() => {
    reloadAuth().catch(() => setAuthState({ configured: true, authenticated: false, min_length: 8 }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Meldet sich die Sitzung irgendwo als abgelaufen, zurueck zur Anmeldung -
  // egal, welche Anfrage es bemerkt hat (siehe api.ts).
  useEffect(() => {
    function abgemeldet(e: Event) {
      const setupRequired = (e as CustomEvent).detail?.setupRequired ?? false;
      setAuthState({ configured: !setupRequired, authenticated: false, min_length: 8 });
    }
    window.addEventListener("fb-unauthorized", abgemeldet);
    return () => window.removeEventListener("fb-unauthorized", abgemeldet);
  }, []);

  useEffect(() => {
    if (!authState?.authenticated) return;
    let abgebrochen = false;
    async function laden() {
      try {
        const v = await getVersion();
        if (!abgebrochen) setVersionInfo(v);
      } catch {
        // Ohne Version laeuft alles weiter - sie wird dann nur nicht angezeigt.
      }
    }
    laden();
    const id = setInterval(laden, VERSION_POLL_MS);
    return () => {
      abgebrochen = true;
      clearInterval(id);
    };
  }, [authState?.authenticated]);

  const t = strings[lang];
  const angemeldet = authState?.authenticated === true;
  const updateStatus = versionInfo?.update.status ?? "unknown";

  // Prüfung direkt aus der Kopfzeile. Die Rückmeldung ist hier der heikle
  // Teil: Wer "Up-to-date" ist und prüft, bekommt wieder "Up-to-date" - ohne
  // Quittung sähe das aus, als hätte der Klick nichts getan. Deshalb erst
  // "Prüfe …", danach ein kurzes Aufleuchten.
  const [pruefeLaeuft, setPruefeLaeuft] = useState(false);
  const [geprueft, setGeprueft] = useState(false);

  async function updatePruefen() {
    setPruefeLaeuft(true);
    setGeprueft(false);
    try {
      const neu = await checkUpdateNow();
      setVersionInfo((alt) => (alt ? { ...alt, update: neu } : alt));
    } catch {
      // Der Zustand selbst trägt den Fehlgrund (detail) - eine zweite
      // Fehlerzeile in der Kopfzeile wäre hier nur im Weg.
    } finally {
      setPruefeLaeuft(false);
      setGeprueft(true);
    }
  }

  // Quittung wieder abräumen, sonst bliebe die Klasse für immer stehen und
  // das nächste Aufleuchten fiele aus.
  useEffect(() => {
    if (!geprueft) return;
    // Länger als die Animation (1100 ms) - wird die Klasse vorher entfernt,
    // bricht das Aufleuchten mittendrin ab.
    const id = setTimeout(() => setGeprueft(false), 1300);
    return () => clearTimeout(id);
  }, [geprueft]);

  return (
    <>
      <header className="fb-header">
        <Logo />
        <div className="fb-header-controls">
          {/* Update-Zustand ganz vorn: bei verfuegbarem Update orange, damit es
              auffaellt. "unknown" bleibt bewusst unaufdringlich - es ist keine
              Warnung, sondern die Aussage, dass noch nicht geprueft wurde. */}
          {angemeldet && view !== "setup" && (
            <button
              type="button"
              className={
                `fb-update fb-update-${updateStatus}` + (geprueft ? " fb-update-geprueft" : "")
              }
              onClick={updatePruefen}
              disabled={pruefeLaeuft}
              title={versionInfo?.update.detail ?? t.updateClickHint}
            >
              {/* Bei verfügbarem Update die NUMMER dazu, nicht nur den Zustand.
                  "Update verfügbar" allein lässt offen, ob man einen Sprung
                  oder dreizehn vor sich hat – und die Nummer ist genau die,
                  die gleich in die Compose-Datei muss. */}
              {pruefeLaeuft
                ? t.updateChecking
                : updateStatus === "update"
                  ? `${t.updateAvailable}: ${versionInfo?.update.latest ?? ""}`.trim()
                  : updateStatus === "current"
                    ? t.upToDate
                    : t.updateUnknown}
            </button>
          )}
          {angemeldet && view !== "setup" && (
            <button className="fb-toggle" onClick={() => setView(view === "settings" ? "dashboard" : "settings")}>
              {t.settings}
            </button>
          )}
          <button
            className="fb-toggle fb-toggle-icon"
            onClick={() => setDialog("about")}
            aria-label={t.about}
            title={t.about}
          >
            ℹ
          </button>
          <button
            className="fb-toggle fb-toggle-icon"
            onClick={() => setDialog("help")}
            aria-label={t.help}
            title={t.help}
          >
            ?
          </button>
          <button
            className="fb-toggle"
            onClick={() => setLang(lang === "de" ? "en" : "de")}
            aria-label="Sprache wechseln"
          >
            {lang === "de" ? "DE" : "EN"}
          </button>
          {angemeldet && (
            <button
              className="fb-toggle"
              onClick={async () => {
                await logout().catch(() => undefined);
                setAuthState({ configured: true, authenticated: false, min_length: 8 });
                setConfig(null);
                setView("loading");
              }}
              title={t.logout}
            >
              {t.logout}
            </button>
          )}
          <button
            className="fb-toggle"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label="Theme wechseln"
          >
            {theme === "dark" ? "🌙" : "☀️"}
          </button>
        </div>
      </header>
      {angemeldet && view !== "setup" && (
        <HealthBar t={t} version={versionInfo?.version ?? null} />
      )}
      <main className="fb-main">
        {authState === null && <p className="fb-muted">{t.loading}</p>}

        {/* Kann FlowBridge nicht speichern, waere eine Anmeldemaske eine
            Luege: Das gesetzte Passwort liesse sich gar nicht ablegen. Also
            der Grund statt des Formulars - und zwar ohne Anmeldung, denn
            ueber die kommt hier ja gerade niemand hinaus. */}
        {authState?.storage_error && (
          <StorageError t={t} detail={authState.storage_error} />
        )}

        {authState !== null && !angemeldet && !authState.storage_error && (
          <LoginForm
            t={t}
            configured={authState.configured}
            minLength={authState.min_length}
            onDone={() => reloadAuth().catch(() => undefined)}
          />
        )}

        {angemeldet && view === "loading" && <p className="fb-muted">{t.loading}</p>}

        {/* Ersteinrichtung: nur das Formular, ohne Passwort-/Diagnose-Kachel
            und ohne Rueckweg - es gibt noch kein Dashboard. */}
        {angemeldet && view === "setup" && config && (
          <SetupForm
            t={t}
            config={config}
            language={lang}
            theme={theme}
            onSaved={() => reloadConfig()}
          />
        )}

        {angemeldet && view === "settings" && config && (
          <SettingsView
            t={t}
            config={config}
            language={lang}
            theme={theme}
            onSaved={() => reloadConfig()}
            onBack={() => setView("dashboard")}
            onApplyUi={(neuesTheme, neueSprache) => {
              setTheme(neuesTheme);
              setLang(neueSprache);
              reloadConfig();
            }}
            versionInfo={versionInfo}
            // Ergebnis des Knopfs direkt übernehmen, statt auf den nächsten
            // Abruf zu warten: Sonst steht in der Kopfzeile noch der alte
            // Zustand, während die Kachel darunter schon den neuen zeigt.
            onUpdateGeprueft={(neu) =>
              setVersionInfo((alt) => (alt ? { ...alt, update: neu } : alt))
            }
          />
        )}

        {angemeldet && view === "dashboard" && config && (
          <Dashboard t={t} config={config} onGoToSetup={() => setView("settings")} />
        )}
      </main>

      {dialog === "about" && (
        <AboutDialog
          t={t}
          lang={lang}
          version={versionInfo?.version ?? null}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "help" && <HelpDialog t={t} lang={lang} onClose={() => setDialog(null)} />}
    </>
  );
}
