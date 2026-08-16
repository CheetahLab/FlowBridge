import { useEffect, useState } from "react";
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

export default function Dashboard({ t, config, onGoToSetup }: Props) {
  const [state, setState] = useState<DeviceStateMap>({});
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

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
      {lastUpdate && (
        <p className="fb-muted">
          {t.lastUpdate}: {lastUpdate.toLocaleTimeString()}
        </p>
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
