import { useEffect, useState } from "react";
import { getHealth } from "../api";
import type { Strings } from "../i18n";
import type { Health } from "../types";

const POLL_MS = 5_000;

type Level = "ok" | "warn" | "off" | "unknown";

function Lamp({ label, level, detail }: { label: string; level: Level; detail: string }) {
  return (
    <div className={`fb-lamp fb-lamp-${level}`} title={`${label}: ${detail}`}>
      <span className="fb-lamp-dot" />
      <span className="fb-lamp-label">{label}</span>
      <span className="fb-lamp-detail">{detail}</span>
    </div>
  );
}

export default function HealthBar({ t, version }: { t: Strings; version?: string | null }) {
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getHealth();
        if (!cancelled) setHealth(data);
      } catch {
        // Backend nicht erreichbar - naechster Tick versucht es erneut.
      }
    }
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  if (!health) return null;

  function brokerState(b: { configured: boolean; connected: boolean }): [Level, string] {
    if (!b.configured) return ["off", t.healthNotConfigured];
    return b.connected ? ["ok", t.healthConnected] : ["warn", t.healthDisconnected];
  }

  const [ecoLevel, ecoDetail] = brokerState(health.ecoflow_broker);
  const [localLevel, localDetail] = brokerState(health.local_broker);

  // Sammel-Lampe über alle Speicher. GRÜN nur, wenn wirklich alle melden -
  // sonst wirkt "1/3 verbunden" neben einem grünen Punkt wie "alles gut".
  // Rot schlägt Blau: ein nachweislich offline gegangener Speicher ist die
  // wichtigere Information als ein noch unbekannter.
  const { configured, online, offline, unknown } = health.devices;
  const many = configured > 1;
  let deviceLevel: Level;
  let deviceDetail: string;
  if (configured === 0) {
    deviceLevel = "off";
    deviceDetail = t.healthNotConfigured;
  } else if (offline > 0) {
    deviceLevel = "warn";
    deviceDetail = many ? `${offline}/${configured} ${t.offline}` : t.offline;
  } else if (unknown > 0) {
    deviceLevel = "unknown";
    deviceDetail = many ? `${online}/${configured} ${t.healthConnected}` : t.healthUnknown;
  } else {
    deviceLevel = "ok";
    deviceDetail = many ? `${online}/${configured} ${t.healthConnected}` : t.healthConnected;
  }

  return (
    <div className="fb-health">
      <Lamp label={t.healthEcoflow} level={ecoLevel} detail={ecoDetail} />
      <Lamp label={t.healthLocal} level={localLevel} detail={localDetail} />
      <Lamp label={t.healthDevice} level={deviceLevel} detail={deviceDetail} />
      {/* Version rechtsbündig in derselben Zeile - der Platz ist ohnehin frei,
          und sie gehört zum Betriebszustand wie die Lampen. */}
      {version && <span className="fb-health-version">{version}</span>}
    </div>
  );
}
