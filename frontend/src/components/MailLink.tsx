import type { Strings } from "../i18n";

/**
 * Einsende-Link für Diagnosepaket und Feldinventar.
 *
 * FlowBridge läuft bei anderen Leuten, und „geht nicht" ist als
 * Fehlerbeschreibung wertlos. Die Dateien dafür gibt es längst – nur wusste
 * niemand, wohin damit. Genau das war die Lücke.
 *
 * DREI DINGE, DIE HIER LEICHT SCHIEFGEHEN:
 *
 * 1. Ein `mailto:` kann KEINE Datei anhängen. Das ist keine Nachlässigkeit,
 *    sondern eine Eigenschaft des Schemas – eine Webseite, die ungefragt
 *    Dateien an eine Mail hängen dürfte, wäre ein Sicherheitsproblem. Wer nur
 *    klickt, schickt also eine leere Mail. Deshalb steht die Reihenfolge
 *    ausdrücklich dabei, und der Textkörper erinnert noch einmal daran.
 *
 * 2. Ohne eingerichtetes Mailprogramm passiert beim Klick NICHTS. Webmail-
 *    Nutzer stünden vor einem toten Link. Deshalb die Adresse zusätzlich als
 *    lesbarer, markierbarer Text.
 *
 * 3. Ohne Versionsnummer ist eine Einsendung nur die halbe Information –
 *    dieselbe Erkenntnis wie bei der Kopfzeile der Protokolldatei. Sie steht
 *    deshalb im Betreff, nicht im Text: Im Betreff sieht man sie in der
 *    Übersicht, ohne die Mail zu öffnen.
 */
/** Die EINE Kontaktadresse des Projekts - auch in NOTICE.md für
 *  Lizenzanfragen. Bewusst eine Projektadresse statt einer persönlichen:
 *  filterbar, und sie lässt sich zurückziehen, ohne die Hauptadresse
 *  anzufassen. Kleinschreibung durchgängig - der lokale Teil ist zwar nach
 *  RFC theoretisch unterscheidend, praktisch behandelt ihn jeder Anbieter
 *  gleich, und zwei Schreibweisen derselben Adresse im selben Abbild sähen
 *  nach Versehen aus. */
export const KONTAKT_MAIL = "flowbridge@hofherweb.de";

export default function MailLink({
  t,
  betreff,
  version,
  modelle,
  vorlage,
}: {
  t: Strings;
  /** Kurzform der Sache, z.B. "Diagnose" – landet vor der Version. */
  betreff: string;
  version?: string;
  /** Gerätemodelle dieser Installation – gehören in den Betreff, nicht nur
   *  die Version: Ohne sie ist beim Öffnen unklar, um welches Gerät es geht,
   *  und genau das ist die erste Frage. Bei mehreren durch Komma getrennt. */
  modelle?: string[];
  /** Textkörper aus i18n - EIN String mit Zeilenumbrüchen, nicht ein Feld
   *  von Zeilen: So steht der Text vollständig in der Sprachdatei, und beim
   *  Übersetzen sieht man ihn im Zusammenhang statt in Bruchstücken. */
  vorlage: string;
}) {
  const geraete = (modelle ?? []).filter(Boolean).join(", ");
  const subject = [`FlowBridge ${betreff} ${version ?? ""}`.trim(), geraete]
    .filter(Boolean)
    .join(" / ");
  const body = [...vorlage, "", `— FlowBridge ${version ?? ""}`.trim()].join("\n");
  const href =
    `mailto:${KONTAKT_MAIL}` +
    `?subject=${encodeURIComponent(subject)}` +
    `&body=${encodeURIComponent(body)}`;

  return (
    <div className="fb-mail">
      <a className="fb-toggle" href={href}>
        {t.sendMail}
      </a>
      <p className="fb-muted fb-diag-note">{t.sendMailOrder}</p>
      <p className="fb-muted fb-diag-note">
        {t.sendMailAddress} <span className="fb-mail-address">{KONTAKT_MAIL}</span>
      </p>
    </div>
  );
}
