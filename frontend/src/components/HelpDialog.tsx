import { helpSections } from "../help";
import type { Language, Strings } from "../i18n";
import Logo from "./Logo";
import Modal from "./Modal";

/** Hilfe: Marke oben, darunter die Abschnitte aus help.ts. */
export default function HelpDialog({
  t,
  lang,
  onClose,
}: {
  t: Strings;
  lang: Language;
  onClose: () => void;
}) {
  return (
    <Modal title={t.help} onClose={onClose}>
      <div className="fb-modal-brand">
        <Logo />
        <p className="fb-modal-subtitle">{t.tagline}</p>
      </div>

      {helpSections[lang].map((abschnitt) => (
        <section className="fb-help-section" key={abschnitt.titel}>
          <h3 className="fb-help-title">{abschnitt.titel}</h3>
          <ul className="fb-help-list">
            {abschnitt.punkte.map((punkt, i) => (
              <li key={i}>{punkt}</li>
            ))}
          </ul>
        </section>
      ))}
    </Modal>
  );
}
