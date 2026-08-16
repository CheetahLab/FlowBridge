/**
 * Wort-Bild-Marke: Protocol Rail in einer Kachel, daneben der Name.
 *
 * ZWEI ENTSCHEIDUNGEN, die die Vorgängerfassung hinter sich lässt:
 *
 * 1. **„FlowBridge“ ist ein Wort.** Vorher stand das Zeichen zwischen „Flow“
 *    und „Bridge“ und las sich als Trennzeichen — aus einem Namen wurden zwei
 *    Worte, und die Rail war als eigenständige Marke verschenkt. Jetzt trägt
 *    die Farbe die Zweiteilung, das Zeichen steht für sich.
 *
 * 2. **Der Schriftzug ist HTML, nicht SVG.** Die alte Fassung setzte den Text
 *    als `<text>` in eine feste Zeichenfläche — und schnitt die Unterlänge des
 *    „g“ ab, weil die Fläche 14 Einheiten zu niedrig war. Jede Schriftgröße
 *    hätte diese Rechnung neu gebraucht. Als HTML macht der Browser die
 *    Metrik, es kann nichts abgeschnitten werden, und die Schrift passt
 *    automatisch zur übrigen Oberfläche.
 *
 * Die Größe steuert allein `font-size` auf `.fb-logo` — die Kachel ist in `em`
 * bemessen und wächst mit.
 *
 * Die Kachelform ist zugleich das, was Docker, Home Assistant und jede
 * App-Übersicht von einem Logo erwarten; das Zeichen allein ergibt damit das
 * Container-Symbol.
 */
export default function Logo() {
  return (
    <span className="fb-logo">
      <svg
        className="fb-logo-mark"
        viewBox="0 0 100 100"
        xmlns="http://www.w3.org/2000/svg"
        role="img"
        aria-label="FlowBridge"
      >
        <rect
          x="1"
          y="1"
          width="98"
          height="98"
          rx="22"
          fill="var(--fb-rail-fill)"
          stroke="var(--fb-line)"
          strokeWidth="2"
        />
        {/* Protocol Rail, Geometrie 1:1 aus der Wortmarke übernommen
            (assets/brand/flowbridge-wordmark-protocol-rail-dark.svg) und nur
            in die Kachel eingepasst (zentriert, Faktor 1,27). Die ungleichen
            Punktabstände sind so gewollt — sie geben dem Zeichen den Rhythmus
            von Daten, die durchlaufen. */}
        <g transform="translate(4.2 50) scale(1.2727)">
          <path
            d="M17 0H51"
            stroke="var(--fb-ice-blue)"
            strokeWidth="5"
            strokeLinecap="round"
          />
          <circle cx="20" cy="0" r="6" fill="var(--fb-electric-blue)" />
          <circle cx="34" cy="0" r="6" fill="var(--fb-ice-blue)" />
          <circle cx="52" cy="0" r="6" fill="var(--fb-signal-orange)" />
        </g>
      </svg>
      <span className="fb-logo-wort">
        Flow<span className="fb-logo-akzent">Bridge</span>
      </span>
    </span>
  );
}
