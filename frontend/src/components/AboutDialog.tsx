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

      <h3 className="fb-help-title">{t.aboutUnderHood}</h3>
      <p className="fb-modal-text">{t.aboutTech}</p>

      <div className="fb-modal-footer">
        <p className="fb-modal-copy">© {jahr} Dirk Hofher. {t.licenseNote}</p>
        <a
          className="fb-modal-link"
          href="https://www.hofherweb.de"
          target="_blank"
          rel="noopener noreferrer"
        >
          www.hofherweb.de
        </a>
      </div>
    </Modal>
  );
}
