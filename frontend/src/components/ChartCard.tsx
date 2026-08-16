import { useEffect, useMemo, useState } from "react";
import { getHistory } from "../api";
import type { Strings } from "../i18n";
import type { DeviceStatus, HistoryPoint } from "../types";
import EnergyPanel from "./EnergyPanel";

/**
 * Verlaufskurven pro Gerät.
 *
 * Bewusst als handgezeichnetes SVG statt mit einer Chart-Bibliothek: der
 * Container soll schlank bleiben, und mehr als mehrere Linien mit gemeinsamer
 * Zeitachse braucht es hier nicht. Zwei Y-Achsen, weil Prozent (SoC) und Watt
 * sonst nicht zusammen darstellbar wären.
 */

const POLL_MS = 15_000;
const BREITE = 560;
const HOEHE = 200;
const PAD = { links: 34, rechts: 40, oben: 12, unten: 22 };

interface Serie {
  feld: keyof HistoryPoint;
  label: string;
  farbe: string;
  achse: "prozent" | "watt";
}

export default function ChartCard({
  t,
  sn,
  name,
  status,
}: {
  t: Strings;
  sn: string;
  name: string;
  status?: DeviceStatus;
}) {
  const [punkte, setPunkte] = useState<HistoryPoint[]>([]);
  const [minuten, setMinuten] = useState(60);
  const [aus, setAus] = useState<Set<string>>(new Set());

  useEffect(() => {
    let abgebrochen = false;
    async function laden() {
      try {
        const d = await getHistory(sn, minuten);
        if (!abgebrochen) setPunkte(d.points);
      } catch {
        // stiller Fehlschlag - nächster Tick versucht es erneut
      }
    }
    laden();
    const id = setInterval(laden, POLL_MS);
    return () => {
      abgebrochen = true;
      clearInterval(id);
    };
  }, [sn, minuten]);

  const serien: Serie[] = useMemo(
    () => [
      { feld: "soc_percent", label: t.soc, farbe: "var(--fb-status-online)", achse: "prozent" },
      { feld: "ac_watts_in", label: t.acWattsIn, farbe: "var(--fb-electric-blue)", achse: "watt" },
      { feld: "battery_watts_in", label: t.batteryWattsIn, farbe: "var(--fb-ice-blue)", achse: "watt" },
      { feld: "watts_out", label: t.wattsOut, farbe: "var(--fb-signal-orange)", achse: "watt" },
      { feld: "ac_watts_out", label: t.acWattsOut, farbe: "#C77DFF", achse: "watt" },
      { feld: "dc_watts_in", label: t.dcWattsIn, farbe: "#FFD166", achse: "watt" },
    ],
    [t]
  );

  const sichtbar = serien.filter((s) => !aus.has(s.feld as string));

  const maxWatt = useMemo(() => {
    let m = 0;
    for (const p of punkte) {
      for (const s of sichtbar) {
        if (s.achse !== "watt") continue;
        const v = p[s.feld];
        if (typeof v === "number" && v > m) m = v;
      }
    }
    // auf glatte Schritte aufrunden, damit die Achse nicht bei jedem Tick springt
    return m <= 0 ? 100 : Math.ceil(m / 100) * 100;
  }, [punkte, sichtbar]);

  // Ohne Verlauf gibt es keine Kurve - die Energiebilanz braucht aber nur die
  // Live-Werte und muss trotzdem erscheinen. Sie hing anfangs hinter diesem
  // Ausstieg und war deshalb nach jedem Neustart minutenlang unsichtbar.
  if (punkte.length < 2) {
    return (
      <div className="fb-card fb-chart-card">
        <h3 className="fb-card-title">{t.chartTitle}</h3>
        <p className="fb-muted">{t.chartCollecting}</p>
        <EnergyPanel t={t} status={status} punkte={punkte} />
      </div>
    );
  }

  const t0 = punkte[0].t;
  const t1 = punkte[punkte.length - 1].t;
  const spanne = Math.max(1, t1 - t0);
  const x = (p: HistoryPoint) =>
    PAD.links + ((p.t - t0) / spanne) * (BREITE - PAD.links - PAD.rechts);
  const y = (wert: number, achse: Serie["achse"]) => {
    const anteil = achse === "prozent" ? wert / 100 : wert / maxWatt;
    return HOEHE - PAD.unten - anteil * (HOEHE - PAD.oben - PAD.unten);
  };

  function pfad(s: Serie): string {
    let d = "";
    let luecke = true;
    for (const p of punkte) {
      const v = p[s.feld];
      if (typeof v !== "number") {
        luecke = true; // fehlende Werte nicht überbrücken, sonst lügt die Kurve
        continue;
      }
      d += `${luecke ? "M" : "L"}${x(p).toFixed(1)},${y(v, s.achse).toFixed(1)}`;
      luecke = false;
    }
    return d;
  }

  const uhrzeit = (sek: number) =>
    new Date(sek * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

  return (
    <div className="fb-card fb-chart-card">
      <div className="fb-chart-head">
        <h3 className="fb-card-title">{t.chartTitle}</h3>
        <div className="fb-chart-range">
          {[15, 60, 360].map((m) => (
            <button
              key={m}
              type="button"
              className={`fb-tab ${minuten === m ? "fb-tab-active" : ""}`}
              onClick={() => setMinuten(m)}
            >
              {m < 60 ? `${m} ${t.minutes}` : `${m / 60} h`}
            </button>
          ))}
        </div>
      </div>

      <svg className="fb-chart" viewBox={`0 0 ${BREITE} ${HOEHE}`} role="img" aria-label={name}>
        {/* waagerechte Hilfslinien + beide Achsenbeschriftungen */}
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const yy = HOEHE - PAD.unten - f * (HOEHE - PAD.oben - PAD.unten);
          return (
            <g key={f}>
              <line
                x1={PAD.links}
                x2={BREITE - PAD.rechts}
                y1={yy}
                y2={yy}
                stroke="var(--fb-line)"
                strokeWidth="1"
              />
              <text x={PAD.links - 5} y={yy + 3} className="fb-chart-tick" textAnchor="end">
                {Math.round(f * 100)}%
              </text>
              <text x={BREITE - PAD.rechts + 5} y={yy + 3} className="fb-chart-tick">
                {Math.round(f * maxWatt)}W
              </text>
            </g>
          );
        })}
        <text x={PAD.links} y={HOEHE - 6} className="fb-chart-tick">
          {uhrzeit(t0)}
        </text>
        <text x={BREITE - PAD.rechts} y={HOEHE - 6} className="fb-chart-tick" textAnchor="end">
          {uhrzeit(t1)}
        </text>

        {sichtbar.map((s) => (
          <path key={s.feld as string} d={pfad(s)} fill="none" stroke={s.farbe} strokeWidth="1.8" />
        ))}
      </svg>

      <div className="fb-chart-legend">
        {serien.map((s) => {
          const anzeigen = !aus.has(s.feld as string);
          const letzter = [...punkte].reverse().find((p) => typeof p[s.feld] === "number");
          const wert = letzter ? (letzter[s.feld] as number) : undefined;
          return (
            <button
              key={s.feld as string}
              type="button"
              className={`fb-legend-item ${anzeigen ? "" : "fb-legend-off"}`}
              onClick={() =>
                setAus((alt) => {
                  const neu = new Set(alt);
                  const k = s.feld as string;
                  neu.has(k) ? neu.delete(k) : neu.add(k);
                  return neu;
                })
              }
            >
              <span className="fb-legend-dot" style={{ background: s.farbe }} />
              {s.label}
              {wert !== undefined && (
                <span className="fb-legend-value">
                  {wert}
                  {s.achse === "prozent" ? "%" : "W"}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <EnergyPanel t={t} status={status} punkte={punkte} />
    </div>
  );
}
