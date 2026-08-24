import { aboutFeatures } from "../help";
import type { Language, Strings } from "../i18n";
import Logo from "./Logo";
import Modal from "./Modal";

/**
 * "Über FlowBridge" - Marke, Version, Kurzbeschreibung, Rechtliches.
 *
 * Die Versionsnummer kommt aus /api/version und stammt aus der Datei VERSION,
 * die der pre-commit-Hook schreibt. Steht dort der Platzhalter, ist FlowBridge
 * ohne aktivierten Hook gebaut worden - dann lieber nichts behaupten.
 */
export default function AboutDialog({
  t,
  lang,
  version,
  onClose,
}: {
  t: Strings;
  lang: Language;
  version: string | null;
  onClose: () => void;
}) {
  const jahr = new Date().getFullYear();
  const bekannt = version && !version.startsWith("0000.");

  return (
    <Modal title={t.about} onClose={onClose}>
      <div className="fb-modal-brand">
        <Logo />
        <p className="fb-modal-subtitle">{t.tagline}</p>
      </div>

      <p className="fb-modal-version">
        {bekannt ? `${t.version} ${version}` : t.versionUnknown}
      </p>

      <p className="fb-modal-text">{t.aboutText}</p>

      <h3 className="fb-help-title">{t.aboutCan}</h3>
      <ul className="fb-about-list">
        {aboutFeatures[lang].map((zeile) => (
          <li key={zeile}>{zeile}</li>
        ))}
      </ul>

      {/* Der Absatz, der die Frage beantwortet, die sich jeder stellt, bevor
          er ein weiteres Werkzeug installiert: Was sehe ich damit, was ich
          vorher nicht gesehen habe? Steht bewusst VOR der Technik - die
          interessiert erst, wenn die Antwort ueberzeugt hat.
          Die Zahlen sind ausdruecklich als Messung an EINEM Geraet
          ausgewiesen; im Dashboard rechnet FlowBridge sie fuer das Geraet des
          Nutzers aus, statt sie zu behaupten. */}
      <h3 className="fb-help-title">{t.aboutSeeTitle}</h3>
      <p className="fb-modal-text">{t.aboutSeeText}</p>

      <h3 className="fb-help-title">{t.aboutUnderHood}</h3>
      <p className="fb-modal-text">{t.aboutTech}</p>

      <div className="fb-modal-footer">
        <p className="fb-modal-copy">© {jahr} Dirk Hofher. {t.licenseNote}</p>
        <a
          className="fb-modal-link"
          href="https://www.cheetahlab.de"
          target="_blank"
          rel="noopener noreferrer"
        >
          www.cheetahlab.de
        </a>
      </div>
    </Modal>
  );
}
