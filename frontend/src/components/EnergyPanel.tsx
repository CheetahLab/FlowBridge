import type { Strings } from "../i18n";
import type { DeviceStatus, HistoryPoint } from "../types";

/**
 * Energiebilanz + Zeitraum-Statistik unter dem Verlaufs-Chart.
 *
 * Hintergrund (gemessen am River 2 Pro, 13.08.2026): der Ladewandler hat einen
 * weitgehend FESTEN Grundverbrauch. Bei 100 W Ladeleistung kamen nur 58 % in
 * der Batterie an, bei 500 W dagegen 87 %. Das sieht man weder in der
 * EcoFlow-App noch am Display – deshalb steht es hier.
 *
 * Alle Werte sind gemessen, keiner ist modelliert: Eingang, Ausgang und
 * Batterieleistung liefert das Gerät selbst, der Rest ist Subtraktion.
 */

/** Unter dieser Leistung ist der Wirkungsgrad nur noch Rauschen. */
const MIN_FLUSS_W = 10;
/** Ab hier lohnt der Hinweis, mit mehr Leistung zu laden. */
const SCHWELLE_HINWEIS = 70;

/** Bruchteile einer Wattstunde runden auf 0 - dann lieber die ganze Zeile
 *  weglassen, statt "0 Wh" hinzuschreiben. */
const NENNENSWERT_WH = 0.5;

function fmtEnergie(wh: number): string {
  if (wh < 1000) return `${Math.round(wh)} Wh`;
  return `${(wh / 1000).toFixed(2).replace(".", ",")} kWh`;
}

/** Trapezintegration über die Stützstellen -> Wh. */
function energie(punkte: HistoryPoint[], feld: keyof HistoryPoint): number {
  let wh = 0;
  for (let i = 1; i < punkte.length; i++) {
    const a = punkte[i - 1][feld];
    const b = punkte[i][feld];
    if (typeof a !== "number" || typeof b !== "number") continue;
    const dt = punkte[i].t - punkte[i - 1].t;
    // Lücken nicht überbrücken: nach einem Aussetzer wäre die Fläche erfunden.
    if (dt <= 0 || dt > 120) continue;
    wh += ((a + b) / 2) * (dt / 3600);
  }
  return wh;
}

function reihe(punkte: HistoryPoint[], feld: keyof HistoryPoint): number[] {
  return punkte.map((p) => p[feld]).filter((v): v is number => typeof v === "number");
}

export default function EnergyPanel({
  t,
  status,
  punkte,
}: {
  t: Strings;
  status?: DeviceStatus;
  punkte: HistoryPoint[];
}) {
  const ein = (status?.ac_watts_in ?? 0) + (status?.dc_watts_in ?? 0);
  const raus = status?.watts_out ?? 0;
  const inBatterie = status?.battery_watts_in ?? 0;
  const ausBatterie = status?.battery_watts_out ?? 0;

  // Richtung an der Batterie ablesen, nicht am Eingang: bei angestecktem
  // Netzkabel laufen Verbraucher im Durchleitbetrieb direkt aus dem Netz -
  // hohe Eingangsleistung, aber die Batterie ist unbeteiligt. Am Eingang
  // festgemacht hätte die Bilanz dann "lädt" behauptet, obwohl nichts
  // in die Batterie geht.
  // ODER, weil die beiden Quellen zeitversetzt eintreffen: ac_watts_in kommt
  // aus dem INV-Modul, battery_watts_in aus dem BMS. Beim Anlaufen meldet der
  // Eingang schon Leistung, waehrend das BMS noch 0 sagt - allein an der
  // Batterie festgemacht stand dort dann "Ruhe" bei 118 W Zufluss.
  // Der Netto-Zufluss schliesst den Durchleitbetrieb weiterhin aus, denn dort
  // heben sich Ein- und Ausgang gegenseitig auf.
  const netto = ein - raus;
  // Beide Richtungen an DERSELBEN Schwelle. `inBatterie > 0` genügte vorher,
  // und damit kippten zwei Watt Messrauschen die ganze Anzeige in den
  // Lademodus - bei pausierter Ladung und null Eingang. Am 16.08.2026 von
  // Dirk im Bild eingefangen: 0 W Eingang, 2 W Batterie, 3 W Ausgang, und
  // die Bilanz meldete "lädt" mit -3 W Eingang.
  // Der Anlauf-Fall (Eingang liefert schon, BMS meldet noch 0) bleibt über
  // `netto` abgedeckt - dafür steht das ODER da.
  const laedt = inBatterie > MIN_FLUSS_W || netto > MIN_FLUSS_W;
  const entlaedt = !laedt && ausBatterie > MIN_FLUSS_W;
  const durchleitung = !laedt && !entlaedt && ein > MIN_FLUSS_W && raus > MIN_FLUSS_W;

  // Beim Laden zählt nur, was NACH Abzug der Verbraucher übrig bleibt - sonst
  // sähe ein angeschlossenes Gerät wie ein schlechter Wirkungsgrad aus.
  // Nie negativ: Beim Laden wird der Ausgang abgezogen, damit ein
  // angeschlossenes Gerät nicht wie ein schlechter Wirkungsgrad aussieht -
  // ist der Ausgang aber größer als der Eingang, käme eine negative
  // Eingangsleistung heraus. Die gibt es nicht. Zweites Netz hinter der
  // Schwelle oben, denn `messbar` unterdrückt nur die Bewertung, nicht die
  // angezeigte Zahl.
  const quelle = Math.max(0, laedt ? ein - raus : entlaedt ? ausBatterie : ein);
  const ziel = laedt ? inBatterie : raus;
  const messbar = (laedt || entlaedt || durchleitung) && quelle > MIN_FLUSS_W && ziel > 0;
  const verlust = messbar ? Math.max(0, quelle - ziel) : 0;

  // Beschriftungen haengen NUR an der Richtung, nicht daran, ob gerade etwas
  // fliesst. Ein taktender Verbraucher am Ausgang wechselt sonst im
  // Sekundentakt zwischen "leitet durch" und "Ruhe" - und liesse die ganze
  // Anzeige auf- und zuklappen, samt springendem Seitenlayout. So bleibt die
  // Zeile stehen und nur die Zahlen aendern sich.
  const quelleLabel = entlaedt ? t.flowBattery : t.flowInput;
  const zielLabel = laedt ? t.flowBattery : t.flowOutput;
  // Im Durchleitbetrieb meldet EcoFlow fuer Ein- und Ausgang DIESELBE Zahl.
  // Daraus einen Wirkungsgrad zu bilden ergaebe stets 100 % - eine Genauigkeit,
  // die die Daten nicht hergeben (verlustfrei ist kein Wechselrichter).
  // Deshalb dort nur den Fluss zeigen, keine Bewertung.
  const wirkungsgrad = messbar && !durchleitung ? (ziel / quelle) * 100 : undefined;

  const socReihe = reihe(punkte, "soc_percent");
  const ladeReihe = reihe(punkte, "ac_watts_in");
  const maxLade = ladeReihe.length ? Math.max(...ladeReihe) : 0;
  const whEin = energie(punkte, "ac_watts_in") + energie(punkte, "dc_watts_in");
  const whBatterie = energie(punkte, "battery_watts_in");
  const whAus = energie(punkte, "watts_out");

  // Der Momentanwert oben zappelt zwangslaeufig: ac_watts_in (INV),
  // watts_out (PD) und battery_watts_in (BMS) treffen zeitversetzt ein, und
  // eine Subtraktion aus drei nicht gleichzeitigen Messungen schwankt.
  // Ueber den Zeitraum integriert mitteln sich diese Versaetze heraus - das
  // ist die Zahl, auf die man sich verlassen kann.
  const whNetto = whEin - whAus;
  const wirkungsgradZeitraum =
    whNetto >= 5 && whBatterie >= NENNENSWERT_WH ? (whBatterie / whNetto) * 100 : undefined;

  return (
    <div className="fb-energy">
      <div className="fb-energy-head">
        <h4 className="fb-energy-title">{t.energyTitle}</h4>
        <span className={`fb-energy-mode ${laedt ? "fb-energy-mode-in" : ""}`}>
          {laedt
            ? t.flowCharging
            : durchleitung
              ? t.flowPassthrough
              : entlaedt
                ? t.flowDischarging
                : t.flowIdle}
        </span>
      </div>

      {/* Immer gerendert - siehe Kommentar bei quelleLabel. */}
      <div className="fb-energy-flow">
        <div className="fb-energy-node">
          <div className="fb-energy-node-value">{Math.round(quelle)} W</div>
          <div className="fb-energy-node-label">{quelleLabel}</div>
        </div>
        <div className="fb-energy-arrow" aria-hidden="true">
          {/* Unter 1 W stuende hier "−0 W" - das sieht nach Fehler aus. */}
          <span className="fb-energy-loss">
            {Math.round(verlust) >= 1 ? `−${Math.round(verlust)} W` : " "}
          </span>
          <span className="fb-energy-arrow-line" />
        </div>
        <div className="fb-energy-node">
          <div className="fb-energy-node-value">{Math.round(ziel)} W</div>
          <div className="fb-energy-node-label">{zielLabel}</div>
        </div>
        <div className="fb-energy-eff">
          <div
            className={`fb-energy-eff-value ${
              wirkungsgrad !== undefined && wirkungsgrad < SCHWELLE_HINWEIS
                ? "fb-energy-eff-bad"
                : ""
            }`}
          >
            {wirkungsgrad !== undefined ? `${Math.round(wirkungsgrad)} %` : "–"}
          </div>
          <div className="fb-energy-node-label">{t.efficiency}</div>
        </div>
      </div>

      {laedt && wirkungsgrad !== undefined && wirkungsgrad < SCHWELLE_HINWEIS && (
        <p className="fb-energy-hint">{t.efficiencyHint}</p>
      )}

      <div className="fb-stats">
        <div className="fb-stats-title">{t.statsTitle}</div>
        <dl className="fb-stats-grid">
          {socReihe.length > 1 && (
            <>
              <dt>{t.soc}</dt>
              <dd>
                {socReihe[0]} → {socReihe[socReihe.length - 1]} %
              </dd>
            </>
          )}
          {whEin >= NENNENSWERT_WH && (
            <>
              <dt>{t.statFromInput}</dt>
              <dd>{fmtEnergie(whEin)}</dd>
            </>
          )}
          {whBatterie >= NENNENSWERT_WH && (
            <>
              <dt>{t.statToBattery}</dt>
              <dd>{fmtEnergie(whBatterie)}</dd>
            </>
          )}
          {whAus >= NENNENSWERT_WH && (
            <>
              <dt>{t.statAtOutput}</dt>
              <dd>{fmtEnergie(whAus)}</dd>
            </>
          )}
          {wirkungsgradZeitraum !== undefined && (
            <>
              <dt>{t.efficiency}</dt>
              <dd>{Math.round(wirkungsgradZeitraum)} %</dd>
            </>
          )}
          {maxLade > 0 && (
            <>
              <dt>{t.statChargePower}</dt>
              <dd>
                Ø {Math.round(ladeReihe.reduce((a, b) => a + b, 0) / ladeReihe.length)} W ·{" "}
                {t.statMax} {Math.round(maxLade)} W
              </dd>
            </>
          )}
        </dl>
      </div>
    </div>
  );
}
