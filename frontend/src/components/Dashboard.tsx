import { useEffect, useMemo, useState } from "react";
import { getState } from "../api";
import type { Strings } from "../i18n";
import type { AppConfig, DeviceStateMap } from "../types";
import ChartCard from "./ChartCard";
import DeviceCard from "./DeviceCard";

interface Props {
  t: Strings;
  config: AppConfig;
  onGoToSetup: () => void;
}

// Am Takt der Daten ausgerichtet: Der EcoFlow-Push liefert im Mittel alle
// 2,3 Sekunden (gemessen am 14.08.2026 ueber acht Stunden; groesster
// regulaerer Abstand 4,0 s). Schneller zu fragen braechte nichts Neues,
// langsamer verschenkt genau das, wofuer die Live-Anbindung gebaut wurde.
//
// Stand bis 14.08.2026 auf 10 s. Dirk fiel es im Vergleich zur EcoFlow-App
// auf: Ein Schaltbefehl war am Geraet laengst angekommen, die Oberflaeche
// zeigte es aber erst beim naechsten Poll - im Mittel fuenf, schlimmstenfalls
// zehn Sekunden spaeter. Das sah nach traeger Steuerung aus, war aber nur
// eine traege Anzeige.
//
// Kosten: eine kleine JSON-Antwort im eigenen Netz, alle drei Sekunden, bei
// einem Geraet und einem Browser.
const POLL_MS = 3_000;

/** Alter des juengsten Messwerts ueber alle Geraete - oder undefined, wenn
 *  keines eines liefert (aeltere Fassung im Container).
 *
 *  Das Minimum, nicht der Durchschnitt: Die Frage lautet "wie frisch ist das
 *  Frischeste, das FlowBridge gerade hat". Einzelne alte Werte kennzeichnet
 *  die Geraetekarte ohnehin selbst. */
function juengstesAlter(state: DeviceStateMap): number | undefined {
  let min: number | undefined;
  for (const status of Object.values(state)) {
    for (const alter of Object.values(status._alter_s ?? {})) {
      if (min === undefined || alter < min) min = alter;
    }
  }
  return min;
}

/** "vor 3 s" / "vor 4 Min" / "vor 2 Std".
 *
 *  Sekundengenau nur im ersten Abschnitt: Bei gesundem Meldeweg steht dort
 *  eine einstellige Zahl, und genau die ist die Aussage. Ab einer Minute
 *  waere Sekundengenauigkeit nur Unruhe. */
function alterText(sekunden: number, t: Strings): string {
  if (sekunden < 90) return `${Math.max(sekunden, 0)} s`;
  const min = Math.round(sekunden / 60);
  if (min < 90) return `${min} ${t.minutes}`;
  return `${Math.round(min / 60)} ${t.hours}`;
}

export default function Dashboard({ t, config, onGoToSetup }: Props) {
  const [state, setState] = useState<DeviceStateMap>({});
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);
  const messAlter = useMemo(() => juengstesAlter(state), [state]);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getState();
        if (!cancelled) {
          setState(data);
          setLastUpdate(new Date());
        }
      } catch {
        // Poll-Fehler bewusst still ignorieren – naechster Tick versucht es erneut.
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (config.ecoflow.devices.length === 0) {
    return (
      <div className="fb-card">
        <p>{t.noDevices}</p>
        <button type="button" className="fb-toggle fb-toggle-primary" onClick={onGoToSetup}>
          {t.goToSetup}
        </button>
      </div>
    );
  }

  return (
    <div>
      {/* Das Alter der MESSWERTE, nicht die Uhrzeit dieses Browsers.
          Vorher stand hier `new Date()` aus dem Moment des Abrufs - eine Zahl,
          die sich alle drei Sekunden erneuerte, auch wenn EcoFlow seit zehn
          Minuten nichts mehr gemeldet hatte. Am 23.08.2026 stand so
          "Zuletzt aktualisiert 19:04:25" ueber Werten von 18:59.
          Der Abrufzeitpunkt bleibt als Rueckfallebene, falls das Backend
          noch keine Altersangaben liefert. */}
      {messAlter !== undefined ? (
        <p className="fb-muted">{t.measuredAgo.replace("{d}", alterText(messAlter, t))}</p>
      ) : (
        lastUpdate && (
          <p className="fb-muted">
            {t.lastUpdate}: {lastUpdate.toLocaleTimeString()}
          </p>
        )
      )}
      {/* Pro Gerät eine Doppelkachel: links Messwerte + Bedienung, rechts der
          Verlauf. Auf schmalen Fenstern stapeln sie sich. */}
      {config.ecoflow.devices.map((device) => (
        <div className="fb-device-pair" key={device.sn}>
          <DeviceCard
            t={t}
            name={device.name}
            status={state[device.sn]}
            chargeSteps={device.charge_watts_steps ?? []}
            controllable={device.controllable !== false}
            model={device.model}
            supportLevel={device.support_level}
            readonlyFields={device.readonly_fields ?? []}
          />
          <ChartCard t={t} sn={device.sn} name={device.name} status={state[device.sn]} />
        </div>
      ))}
    </div>
  );
}
