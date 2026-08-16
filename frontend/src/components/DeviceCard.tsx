import { useEffect, useState } from "react";
import { refreshDevice, sendCommand } from "../api";
import type { Strings } from "../i18n";
import type { DeviceStatus } from "../types";

interface Props {
  t: Strings;
  name: string;
  status: DeviceStatus | undefined;
  chargeSteps: number[];
  controllable: boolean;
  model?: string;
  supportLevel?: string;
  /** Felder, die das Geraet meldet, aber nicht annimmt (siehe models.nur_lesbar). */
  readonlyFields: string[];
}

// OBERGRENZE, nicht Anzeigedauer: Der Hinweis verschwindet normalerweise
// schon vorher - naemlich sobald das Geraet den neuen Wert meldet (siehe den
// useEffect weiter unten). Typisch sind 2-3 Sekunden.
//
// Bis 14.08.2026 lief er stur diese 10 Sekunden ab, auch wenn die Aenderung
// laengst zurueckgekommen war. Dirk fiel es im Vergleich zur EcoFlow-App auf:
// dort reagiert es sichtbar schnell, in FlowBridge "dauerte" es. Der
// Kommentar an dieser Stelle nannte die 2-3 Sekunden schon damals - der Code
// hat sie nur nie genutzt.
//
// Als Obergrenze bleibt der Wert sinnvoll: Laeuft er ab, ohne dass sich etwas
// geruehrt hat, ist das ein echtes Indiz fuer ein Problem. Und fuer die zwei
// Werte, die EcoFlow gar nicht zurueckliefert (Ladeleistung, Ladepause), ist
// er die einzige Moeglichkeit, den Hinweis je wieder loszuwerden.
const SYNC_HINT_MS = 10_000;

const OVERVIEW = "__overview__";

/** Auf die nächste gültige Stufe rasten; ungültige Eingabe -> null. */
function snapCharge(value: number, steps: number[]): number | null {
  if (Number.isNaN(value) || steps.length === 0) return null;
  return steps.reduce((a, b) => (Math.abs(b - value) < Math.abs(a - value) ? b : a));
}

/** Enter in einem Zahlenfeld heisst "fertig" - genau wie das Wegklicken.
 *
 * Absichtlich ueber `blur()` statt ueber einen eigenen Absende-Pfad: Es gibt
 * damit weiterhin nur EINE Stelle, an der ein Wert das Feld verlaesst
 * (`onBlur`), und Enter loest sie nur aus. Zwei parallele Wege waeren zwei
 * Gelegenheiten, sich zu unterscheiden.
 *
 * Bis 14.08.2026 gab es Enter gar nicht: Der Wert blieb stehen, der Cursor
 * blinkte weiter, und nichts passierte - erst ein Klick daneben schickte ihn
 * los. Wer eine Zahl tippt und Enter drueckt, hat aber genau eine Erwartung.
 */
function enterUebernimmt(e: React.KeyboardEvent<HTMLInputElement>): void {
  if (e.key !== "Enter") return;
  e.preventDefault();
  e.currentTarget.blur();
}

/* Dauer der Funkstille, grob gerundet.
 *
 * Grob ist hier richtig: Der Unterschied zwischen "3 Min" und "22 Std" ist der
 * zwischen einer normalen EcoFlow-Push-Luecke und einem abgeschalteten Geraet.
 * Auf Sekunden genau waere die Zahl nur unruhig - sie aktualisiert im
 * Poll-Takt und stuende dann nie still. */
function stilleText(sekunden: number, t: Strings): string {
  const min = Math.floor(sekunden / 60);
  if (min < 60) return `${Math.max(min, 1)} ${t.minutes}`;
  const std = Math.floor(min / 60);
  if (std < 48) return `${std} ${t.hours}`;
  return `${Math.floor(std / 24)} ${t.days}`;
}

/* ToggleRow und LimitRow stehen bewusst HIER, auf Modulebene, und nicht im
   Rumpf von DeviceCard.

   Eine Komponente, die innerhalb einer anderen definiert wird, ist bei jedem
   Rendern ein NEUER Typ. React kann sie dann nicht wiedererkennen, haengt den
   Teilbaum ab und baut ihn neu auf - ein Eingabefeld verliert dabei Fokus und
   Inhalt. Beim Dashboard mit seinem Sekundentakt hiess das: Was man tippte,
   war praktisch sofort wieder weg, und der alte Wert stand wieder da. Genau
   das hat Dirk am 13.08.2026 gemeldet - und es erklaert auch, warum die
   AC-Ladeleistung funktionierte: die wird direkt im JSX gerendert, nicht ueber
   eine innen definierte Komponente. */

function ToggleRow({
  t,
  label,
  property,
  enabled,
  syncing,
  disabled,
  onToggle,
}: {
  t: Strings;
  label: string;
  property: string;
  enabled: number | undefined;
  syncing: string | null;
  disabled: boolean;
  onToggle: (property: string, currentlyOn: boolean) => void;
}) {
  if (enabled === undefined) return null;
  return (
    <div className="fb-toggle-row">
      <span>
        {label}
        {syncing === property && <span className="fb-sync-hint"> · {t.syncing}</span>}
      </span>
      <button
        type="button"
        className={`fb-switch ${enabled ? "fb-switch-on" : ""}`}
        disabled={disabled}
        onClick={() => onToggle(property, !!enabled)}
      >
        {enabled ? t.on : t.off}
      </button>
    </div>
  );
}

function LimitRow({
  t,
  label,
  property,
  value,
  draft,
  onDraft,
  syncing,
  disabled,
  onCommit,
}: {
  t: Strings;
  label: string;
  property: string;
  value: number | undefined;
  /** Getippter, noch nicht bestaetigter Wert. */
  draft: number | undefined;
  onDraft: (property: string, value: number | undefined) => void;
  syncing: string | null;
  disabled: boolean;
  onCommit: (property: string, value: number) => void;
}) {
  if (value === undefined) return null;
  // Kontrolliert statt defaultValue: Der Entwurf gilt, bis das Geraet den
  // neuen Wert bestaetigt. Mit defaultValue sprang die Anzeige beim naechsten
  // Poll auf den alten Wert zurueck - das Geraet braucht aber seine Zeit, bis
  // die Umstellung bei ihm angekommen ist.
  const angezeigt = draft ?? value;
  return (
    <div className="fb-toggle-row">
      <span>
        {label}
        {syncing === property && <span className="fb-sync-hint"> · {t.syncing}</span>}
      </span>
      {/* Eingabefeld + Einheit als eine Gruppe, damit alle Limit-Zeilen
          rechtsbuendig auf derselben Kante stehen wie die Schalter. */}
      <span className="fb-limit-group">
        <input
          type="number"
          min={0}
          max={100}
          value={angezeigt}
          className="fb-limit-input"
          disabled={disabled}
          onChange={(e) => {
            const roh = e.target.value;
            // Leeres Feld zulassen - sonst laesst sich die Zahl nicht
            // loeschen, um eine neue zu tippen.
            onDraft(property, roh === "" ? undefined : parseInt(roh, 10));
          }}
          onBlur={(e) => {
            const v = parseInt(e.target.value, 10);
            if (Number.isNaN(v)) {
              onDraft(property, undefined); // ungueltig -> zurueck zum Geraetewert
              return;
            }
            if (v !== value) onCommit(property, v);
          }}
          onKeyDown={enterUebernimmt}
        />
        <span className="fb-limit-unit">%</span>
      </span>
    </div>
  );
}

/** Rohwerte eines Moduls, so wie EcoFlow sie liefert - reiner Kontrollzweck. */
function ModuleTable({
  fields,
  emptyText,
}: {
  fields: Record<string, unknown> | undefined;
  emptyText: string;
}) {
  const entries = Object.entries(fields ?? {}).sort(([a], [b]) => a.localeCompare(b));
  if (entries.length === 0) return <p className="fb-muted">{emptyText}</p>;
  return (
    <table className="fb-module-table">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td className="fb-module-key">{key}</td>
            <td className="fb-module-value">{String(value)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/** Minuten -> "7 h 22 min". Roh sind Restzeiten unlesbar: 662 sagt niemandem
 *  etwas, 11 h 2 min sofort. Unter einer Stunde bleiben nur die Minuten. */
function formatDauer(minuten: number | undefined): string | undefined {
  if (minuten === undefined || minuten === null) return undefined;
  const h = Math.floor(minuten / 60);
  const m = minuten % 60;
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

function Metric({ label, value, unit }: { label: string; value: unknown; unit?: string }) {
  if (value === undefined || value === null) return null;
  return (
    <div className="fb-metric">
      <div className="fb-metric-value">
        {String(value)}
        {unit && <span className="fb-metric-unit"> {unit}</span>}
      </div>
      <div className="fb-metric-label">{label}</div>
    </div>
  );
}

export default function DeviceCard({
  t,
  name,
  status,
  chargeSteps,
  controllable,
  model,
  supportLevel,
  readonlyFields,
}: Props) {
  const [pending, setPending] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);
  // Wert der betroffenen Eigenschaft im Moment des Befehls - daran
  // erkennt der Effekt weiter unten, dass das Geraet bestaetigt hat.
  const [syncVorher, setSyncVorher] = useState<unknown>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<string>(OVERVIEW);
  // Reglerposition lokal halten, damit das Ziehen flüssig ist; gesendet wird
  // erst beim Loslassen (sonst ein Befehl pro Pixel).
  const [chargeDraft, setChargeDraft] = useState<number | null>(null);
  // Dasselbe fuer die Prozent-Limits, nur je Eigenschaft. Ohne diesen Entwurf
  // spraenge das Feld beim naechsten Poll auf den Geraetewert zurueck - und
  // das Geraet meldet den neuen erst nach einer Weile.
  const [limitDrafts, setLimitDrafts] = useState<Record<string, number | undefined>>({});
  const [refreshing, setRefreshing] = useState(false);
  // Quittung der letzten REST-Abfrage. Verschwindet von selbst - eine
  // Meldung, die stehen bleibt, waere beim naechsten Blick nicht mehr von
  // einer frischen zu unterscheiden.
  const [refreshDone, setRefreshDone] = useState<string | null>(null);

  // MUSS vor jedem vorzeitigen return stehen: React verlangt in jedem Render
  // dieselbe Hook-Reihenfolge. Weiter unten platziert, wurde der Hook bei
  // "noch keine Messwerte" uebersprungen - und sobald die ersten Werte kamen,
  // brach der gesamte Baum ab (leere Seite statt Dashboard).
  //
  // Inhaltlich: der lokale Entwurf gilt nur, bis der Wert bestaetigt
  // zurueckkommt. Sonst bliebe die Anzeige fuer immer an dem haengen, was hier
  // zuletzt jemand angefasst hat - eine Umstellung ueber MQTT (EisBaer, Home
  // Assistant) oder die EcoFlow-App waere unsichtbar, und der naechste Klick
  // wuerde sie mit dem alten Wert ueberschreiben.
  useEffect(() => {
    if (chargeDraft === null) return;
    const gemeldet = status?.charge_power_watts ?? status?.charge_power_watts_set;
    if (gemeldet === chargeDraft) setChargeDraft(null);
  }, [status?.charge_power_watts, status?.charge_power_watts_set, chargeDraft]);

  // Dieselbe Regel fuer die Limits: Der Entwurf faellt weg, sobald das Geraet
  // ihn bestaetigt. Danach zaehlt wieder der gemeldete Wert - eine Umstellung
  // ueber die EcoFlow-App oder MQTT bliebe sonst unsichtbar.
  // Der Hinweis "wird uebernommen" verschwindet, sobald das Geraet den neuen
  // Wert meldet - nicht erst nach Ablauf von SYNC_HINT_MS. Fuer Ladeleistung
  // und Ladepause gibt es kein lesbares Feld; dort bleibt es beim Timer.
  const gemeldeterSyncWert =
    syncing ? (status as Record<string, unknown> | undefined)?.[syncing] : undefined;
  useEffect(() => {
    if (!syncing) return;
    if (gemeldeterSyncWert !== undefined && gemeldeterSyncWert !== syncVorher) {
      setSyncing(null);
    }
  }, [syncing, syncVorher, gemeldeterSyncWert]);

  useEffect(() => {
    if (!refreshDone) return;
    const id = setTimeout(() => setRefreshDone(null), 6_000);
    return () => clearTimeout(id);
  }, [refreshDone]);

  const gemeldeteLimits = [
    status?.charge_limit_percent,
    status?.discharge_limit_percent,
    status?.backup_reserve_percent,
  ].join("|");
  useEffect(() => {
    setLimitDrafts((vorher) => {
      const gemeldet: Record<string, number | undefined> = {
        charge_limit_percent: status?.charge_limit_percent,
        discharge_limit_percent: status?.discharge_limit_percent,
        backup_reserve_percent: status?.backup_reserve_percent,
      };
      let geaendert = false;
      const nachher = { ...vorher };
      for (const [eigenschaft, entwurf] of Object.entries(vorher)) {
        if (entwurf !== undefined && gemeldet[eigenschaft] === entwurf) {
          delete nachher[eigenschaft];
          geaendert = true;
        }
      }
      // Nur bei echter Aenderung ein neues Objekt zurueckgeben, sonst
      // rendert die Karte im Sekundentakt ohne Grund neu.
      return geaendert ? nachher : vorher;
    });
  }, [gemeldeteLimits]);

  const modules = status?._modules ?? {};
  // Feste Reihenfolge nach Modul-Nummer statt Dict-Zufall; unbekannte hinten.
  const ORDER = ["PD", "BMS", "EMS", "INV", "MPPT"];
  const moduleNames = Object.keys(modules).sort(
    (a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99)
  );

  // Ein Gerät ohne jegliche Messwerte: entweder noch am Verbinden oder gar
  // nicht erreichbar. Den bekannten Grund anzeigen statt endlos "lade ..."
  // (fällt vor allem bei mehreren Geräten auf, z.B. falsche Seriennummer).
  const hasData = status && status.soc_percent !== undefined;
  if (!hasData) {
    return (
      <div className={`fb-card ${status?.error ? "fb-card-offline" : ""}`}>
        <h3 className="fb-card-title">
          <span
            className={`fb-lamp-dot ${status?.error ? "fb-lamp-warn-dot" : "fb-lamp-unknown-dot"}`}
          />
          {name || status?.sn}
          {status?.error && <span className="fb-offline-badge">{t.unreachable}</span>}
        </h3>
        {status?.error ? (
          <>
            <p className="fb-status-error">{t.unreachableHint}</p>
            <p className="fb-muted">{status.error}</p>
          </>
        ) : (
          <p className="fb-muted">{t.loading}</p>
        )}
      </div>
    );
  }

  function markSyncing(property: string) {
    setSyncVorher((status as Record<string, unknown> | undefined)?.[property]);
    setSyncing(property);
    setTimeout(() => {
      setSyncing((current) => (current === property ? null : current));
    }, SYNC_HINT_MS);
  }

  async function toggle(property: string, currentlyOn: boolean) {
    setPending(property);
    setError(null);
    try {
      await sendCommand(status!.sn, property, currentlyOn ? "off" : "on");
      markSyncing(property);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPending(null);
    }
  }

  async function refreshNow() {
    setRefreshing(true);
    setError(null);
    try {
      const antwort = await refreshDevice(status!.sn);
      // Ohne Quittung sah der Knopf aus, als taete er nichts: Die Abfrage
      // dauert Millisekunden, und weil der Push die Werte ohnehin schon
      // aktuell haelt, aendert sich danach in aller Regel KEINE Zahl. Der
      // Feldzaehler ist der einzige ehrliche Beleg, dass etwas passiert ist.
      setRefreshDone(
        `${antwort.fields} ${t.refreshDone} · ${new Date().toLocaleTimeString()}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRefreshing(false);
    }
  }

  function setLimitDraft(property: string, value: number | undefined) {
    setLimitDrafts((vorher) => ({ ...vorher, [property]: value }));
  }

  async function setLimit(property: string, value: number) {
    setPending(property);
    setError(null);
    try {
      await sendCommand(status!.sn, property, String(value));
      markSyncing(property);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      // Fehlgeschlagener Befehl: Entwurf verwerfen, sonst zeigt das Feld
      // dauerhaft einen Wert an, den das Geraet nie bekommen hat.
      if (property === "charge_power_watts") setChargeDraft(null);
      else setLimitDraft(property, undefined);
    } finally {
      setPending(null);
    }
  }

  // Strikt `=== false`: fehlt das Feld (noch keine Aussage möglich), gilt das
  // Gerät NICHT als offline - sonst false-positive beim ersten Laden.
  const offline = status.online === false;

  // Reihenfolge: laufender Entwurf > vom Gerät gemeldeter Wert > zuletzt
  // selbst gesetzter. Der gemeldete schlägt den gemerkten, weil er auch
  // Änderungen aus der EcoFlow-App mitbekommt.
  const backupNurLesbar = readonlyFields.includes("backup_reserve_enabled");

  const chargeValue =
    chargeDraft ?? status.charge_power_watts ?? status.charge_power_watts_set ?? null;
  const chargeKnown =
    status.charge_power_watts !== undefined || status.charge_power_watts_set !== undefined;
  // chgPauseFlag: 1 = pausiert. Fehlt es, gilt der gemerkte Zustand.
  const chargingPaused =
    status.charge_paused !== undefined
      ? status.charge_paused === 1
      : status.ac_charging_enabled_set === false;

  // Gleiche Ampel-Semantik wie in der Kopfleiste: grün/rot/blau.
  const lampLevel = status.online === true ? "ok" : offline ? "warn" : "unknown";
  const lampTitle =
    status.online === true ? t.healthConnected : offline ? t.offline : t.healthUnknown;

  // Wie lange schon still? Nur zeigen, wenn das Gerät NICHT meldet - im
  // Normalbetrieb stünde da eine Sekundenzahl, die niemanden interessiert.
  // "Offline" allein sagt nicht, ob das seit fünf Minuten oder seit gestern
  // gilt; genau dieser Unterschied entscheidet, ob man nachschauen geht.
  const stille =
    status.online !== true && status.silence_seconds !== undefined
      ? t.noSignalFor.replace("{d}", stilleText(status.silence_seconds, t))
      : null;

  return (
    <div className={`fb-card fb-card-wide ${offline ? "fb-card-offline" : ""}`}>
      <div className="fb-card-header">
        <h3 className="fb-card-title">
          <span className={`fb-lamp-dot fb-lamp-${lampLevel}-dot`} title={lampTitle} />
          {name || status.sn}
          {offline && <span className="fb-offline-badge">{t.offline}</span>}
          {stille && <span className="fb-silence-badge">{stille}</span>}
        </h3>
        <button
          type="button"
          className="fb-toggle fb-refresh"
          onClick={refreshNow}
          disabled={refreshing}
          title={t.refreshHint}
        >
          {refreshing ? t.refreshing : t.refresh}
        </button>
      </div>
      {refreshDone && <p className="fb-muted fb-refresh-done">{refreshDone}</p>}
      {offline && <p className="fb-status-error">{t.offlineHint}</p>}

      {/* Übersicht bleibt der Haupt-Tab; die Modul-Tabs zeigen die Rohwerte
          genau so, wie sie EcoFlow je Modul liefert (Kontrollzweck). */}
      <div className="fb-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === OVERVIEW}
          className={`fb-tab ${tab === OVERVIEW ? "fb-tab-active" : ""}`}
          onClick={() => setTab(OVERVIEW)}
        >
          {t.overview}
        </button>
        {moduleNames.map((moduleName) => (
          <button
            key={moduleName}
            type="button"
            role="tab"
            aria-selected={tab === moduleName}
            className={`fb-tab ${tab === moduleName ? "fb-tab-active" : ""}`}
            onClick={() => setTab(moduleName)}
          >
            {moduleName}
          </button>
        ))}
      </div>

      {tab !== OVERVIEW ? (
        <ModuleTable fields={modules[tab]} emptyText={t.noModuleData} />
      ) : (
      <>
      <div className="fb-metrics">
        <Metric label={t.soc} value={status.soc_percent} unit="%" />
        <Metric label={t.acWattsIn} value={status.ac_watts_in} unit="W" />
        <Metric label={t.dcWattsIn} value={status.dc_watts_in} unit="W" />
        <Metric label={t.batteryWattsIn} value={status.battery_watts_in} unit="W" />
        <Metric label={t.wattsOut} value={status.watts_out} unit="W" />
        <Metric label={t.acWattsOut} value={status.ac_watts_out} unit="W" />
        {/* Nur EINE der beiden Zeiten ist je sinnvoll - das Geraet laedt oder
            es entlaedt. Beide dauerhaft nebeneinander zu zeigen hiesse, dass
            staendig eine davon leer ist. Das Backend liefert deshalb genau die
            passende; hier wird nur noch entschieden, welche Beschriftung
            darueber steht. */}
        <Metric
          label={status.charge_remain_min !== undefined ? t.chargeRemain : t.dischargeRemain}
          value={formatDauer(
            status.charge_remain_min !== undefined
              ? status.charge_remain_min
              : status.discharge_remain_min,
          )}
        />
        <Metric label={t.acVoltage} value={status.ac_output_voltage} unit="V" />
        <Metric label={t.acFreq} value={status.ac_output_freq_hz} unit="Hz" />
        <Metric label={t.carWatts} value={status.car_watts} unit="W" />
        <Metric label={t.usb1Watts} value={status.usb1_watts} unit="W" />
        <Metric label={t.typec1Watts} value={status.typec1_watts} unit="W" />
      </div>

      {/* Bedienung nur bei verifiziertem Modell: EcoFlow quittiert Befehle
          auch dann mit "Success", wenn das Gerät sie stillschweigend verwirft -
          Schalter, die nichts tun, wären schlimmer als keine. */}
      {!controllable ? (
        <p className="fb-muted fb-charge-note">
          {t.monitorOnlyCard}
          {model && ` (${model})`}
        </p>
      ) : (
      <>
      {supportLevel === "documented" && (
        <p className="fb-muted fb-charge-note">{t.documentedOnly}</p>
      )}
      <ToggleRow
        t={t}
        label={t.acOutput}
        property="ac_output_enabled"
        enabled={status.ac_output_enabled}
        syncing={syncing}
        disabled={offline || pending === "ac_output_enabled"}
        onToggle={toggle}
      />
      <ToggleRow
        t={t}
        label={t.xboost}
        property="xboost_enabled"
        enabled={status.xboost_enabled}
        syncing={syncing}
        disabled={offline || pending === "xboost_enabled"}
        onToggle={toggle}
      />
      <ToggleRow
        t={t}
        label={t.carOutput}
        property="car_output_enabled"
        enabled={status.car_output_enabled}
        syncing={syncing}
        disabled={offline || pending === "car_output_enabled"}
        onToggle={toggle}
      />
      <LimitRow
        t={t}
        label={t.chargeLimit}
        property="charge_limit_percent"
        value={status.charge_limit_percent}
        draft={limitDrafts.charge_limit_percent}
        onDraft={setLimitDraft}
        syncing={syncing}
        disabled={offline || pending === "charge_limit_percent"}
        onCommit={setLimit}
      />
      <LimitRow
        t={t}
        label={t.dischargeLimit}
        property="discharge_limit_percent"
        value={status.discharge_limit_percent}
        draft={limitDrafts.discharge_limit_percent}
        onDraft={setLimitDraft}
        syncing={syncing}
        disabled={offline || pending === "discharge_limit_percent"}
        onCommit={setLimit}
      />
      {/* AC-Ladeleistung: 100-870 W in 50er-Schritten. Der eingestellte Wert
          ist über die API NICHT auslesbar - angezeigt wird deshalb nur, was
          FlowBridge zuletzt selbst gesetzt hat (nach Neustart wieder leer). */}
      {/* AC-Laden pausieren: undokumentiert, aber am Gerät verifiziert
          (chgPauseFlag). Ersetzt das Aus- und Einschalten einer Steckdose. */}
      <div className="fb-toggle-row">
        <span>
          {t.acCharging}
          {syncing === "ac_charging_enabled" && (
            <span className="fb-sync-hint"> · {t.syncing}</span>
          )}
        </span>
        <button
          type="button"
          className={`fb-switch ${chargingPaused ? "" : "fb-switch-on"}`}
          disabled={offline || pending === "ac_charging_enabled"}
          onClick={() => toggle("ac_charging_enabled", !chargingPaused)}
        >
          {chargingPaused ? t.paused : t.charging}
        </button>
      </div>
      <p className="fb-muted fb-charge-note">{t.acChargingHint}</p>

      <div className="fb-charge-row">
        <div className="fb-toggle-row fb-charge-head">
          <span>
            {t.chargePower}
            {syncing === "charge_power_watts" && (
              <span className="fb-sync-hint"> · {t.syncing}</span>
            )}
          </span>
          <span className="fb-limit-group">
            <input
              type="number"
              min={chargeSteps[0]}
              max={chargeSteps[chargeSteps.length - 1]}
              step={50}
              className="fb-limit-input"
              value={chargeValue ?? ""}
              disabled={offline || pending === "charge_power_watts"}
              onChange={(e) => setChargeDraft(parseInt(e.target.value, 10))}
              onBlur={(e) => {
                const v = snapCharge(parseInt(e.target.value, 10), chargeSteps);
                if (v !== null) {
                  setChargeDraft(v);
                  setLimit("charge_power_watts", v);
                }
              }}
              onKeyDown={enterUebernimmt}
            />
            <span className="fb-limit-unit">W</span>
          </span>
        </div>
        {/* Der Regler laeuft ueber den INDEX der Stufenliste, nicht ueber Watt.
            Nur so rastet er sauber auf jeder erlaubten Stufe ein - inklusive
            der letzten (870 W), die nicht ins 50er-Raster ab 100 passt. */}
        <input
          type="range"
          min={0}
          max={Math.max(0, chargeSteps.length - 1)}
          step={1}
          className="fb-slider"
          value={Math.max(0, chargeSteps.indexOf(chargeValue ?? chargeSteps[0]))}
          disabled={offline || pending === "charge_power_watts"}
          onChange={(e) => setChargeDraft(chargeSteps[parseInt(e.target.value, 10)])}
          onMouseUp={(e) =>
            setLimit("charge_power_watts", chargeSteps[parseInt(e.currentTarget.value, 10)])
          }
          onTouchEnd={(e) =>
            setLimit("charge_power_watts", chargeSteps[parseInt(e.currentTarget.value, 10)])
          }
          onKeyUp={(e) =>
            setLimit("charge_power_watts", chargeSteps[parseInt(e.currentTarget.value, 10)])
          }
        />
        {/* Selbst gezeichnete Skala statt <datalist>.
            Die Strichmarken eines <datalist> zu zeichnen ist dem Browser
            ueberlassen, und die Browser sind sich uneins: In Firefox blitzten
            sie nur beim Loslassen kurz auf, Chromium zeigt sie gar nicht, die
            Beschriftungen (label) rendert ohnehin keiner. Bei einem Regler,
            dessen ganzer Sinn die festen Stufen sind, darf ihre Sichtbarkeit
            nicht vom Browser abhaengen.
            Die Marken stehen gleichmaessig, weil der Regler ueber den INDEX
            laeuft - der Abstand 820->870 ist auf der Skala derselbe wie
            100->150. */}
        <div className="fb-slider-scale" aria-hidden="true">
          {chargeSteps.map((w, i) => (
            <span className="fb-slider-tick" key={w}>
              {w % 200 === 100 || i === chargeSteps.length - 1 ? (
                <span className="fb-slider-tick-label">{w}</span>
              ) : null}
            </span>
          ))}
        </div>
        <p className="fb-muted fb-charge-note">
          {!chargeKnown && chargeDraft === null ? t.chargePowerUnknown : t.chargePowerHint}
        </p>
      </div>

      {/* Backup-Reserve ist ein Sollwert (watthConfig), kein Messwert -
          gehoert deshalb zu den Einstellungen, nicht zu den Kacheln.

          Zweiteilig wie in der EcoFlow-App: Schalter plus Prozentwert.

          Beim River 2 Pro steht beides in `readonlyFields`: Am 14.08.2026
          gemessen, dass das Geraet watthConfig ueber die offene API nicht
          annimmt - EcoFlow quittiert ohne Fehler, am Geraet passiert
          nichts, und auch in der EcoFlow-App bewegt sich kein Schalter.
          Gelesen wird es dagegen einwandfrei: Umschalten IN der App kommt
          hier sofort an. Also anzeigen, nicht anbieten. Ein Knopf, der
          nachweislich nichts tut, laesst den Fehler beim Benutzer suchen. */}
      {backupNurLesbar ? (
        <>
          <div className="fb-toggle-row">
            <span>{t.backupReserve}</span>
            <span className="fb-readonly-value">
              {status.backup_reserve_enabled ? t.on : t.off}
            </span>
          </div>
          {status.backup_reserve_percent !== undefined && (
            <div className="fb-toggle-row">
              <span>{t.backupReserveLevel}</span>
              <span className="fb-readonly-value">{status.backup_reserve_percent} %</span>
            </div>
          )}
          <p className="fb-muted fb-charge-note">{t.backupReserveReadonly}</p>
        </>
      ) : (
        <>
          <ToggleRow
            t={t}
            label={t.backupReserve}
            property="backup_reserve_enabled"
            enabled={status.backup_reserve_enabled}
            syncing={syncing}
            disabled={offline || pending === "backup_reserve_enabled"}
            onToggle={toggle}
          />
          <LimitRow
            t={t}
            label={t.backupReserveLevel}
            property="backup_reserve_percent"
            value={status.backup_reserve_percent}
            draft={limitDrafts.backup_reserve_percent}
            onDraft={setLimitDraft}
            syncing={syncing}
            disabled={
              offline ||
              pending === "backup_reserve_percent" ||
              status.backup_reserve_enabled === 0
            }
            onCommit={setLimit}
          />
          {status.backup_reserve_enabled === 0 && (
            <p className="fb-muted fb-charge-note">{t.backupReserveOff}</p>
          )}
        </>
      )}
      </>
      )}
      </>
      )}

      {error && <p className="fb-status-error">{error}</p>}
    </div>
  );
}
