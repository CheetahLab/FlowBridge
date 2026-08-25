import { useEffect, useState, type ReactNode } from "react";
import type { Strings } from "../i18n";
import Modal from "./Modal";

/**
 * "Was ist neu" - das Änderungsprotokoll im Dialog.
 *
 * Der Text wird beim ÖFFNEN geholt, nicht mitgeliefert. Das ist der Kern:
 * Ein eingebautes Protokoll wäre auf dem Stand der installierten Fassung
 * eingefroren und könnte damit die eine Frage nicht beantworten, die es
 * auslöst - "was bringt das Update, das ich noch nicht habe?".
 *
 * Geholt wird aus dem Browser heraus, ausgelöst durch einen Klick. Über den
 * Server liefe es nicht: Dann spräche FlowBridge selbst mit einem dritten
 * Haus, und die Zusage "redet nur mit EcoFlow und deinem Broker" bekäme eine
 * stille Ausnahme. So ist es dieselbe Verbindung, die ein Klick auf einen
 * Link auch aufgebaut hätte - nur mit der Darstellung hier statt drüben.
 *
 * Ohne Netz bleibt der Dialog nicht leer, sondern nennt den Grund und den
 * Link. Ein Dialog, der schweigend nichts zeigt, sieht aus wie ein Fehler
 * im Programm.
 */
export default function ChangelogDialog({
  t,
  version,
  onClose,
}: {
  t: Strings;
  version: string | null;
  onClose: () => void;
}) {
  const [text, setText] = useState<string | null>(null);
  const [fehler, setFehler] = useState(false);

  useEffect(() => {
    let abgebrochen = false;
    // Der Rohtext, nicht die GitHub-Seite: Die brächte deren ganzes Gerüst
    // mit, und daraus den Artikel zu schneiden wäre eine Wette auf fremdes
    // Markup.
    fetch(t.changelogRawUrl)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((s) => {
        if (!abgebrochen) setText(s);
      })
      .catch(() => {
        if (!abgebrochen) setFehler(true);
      });
    return () => {
      abgebrochen = true;
    };
  }, [t.changelogRawUrl]);

  return (
    <Modal title={t.whatsNewTitle} onClose={onClose}>
      <h2 className="fb-changelog-titel">{t.whatsNewTitle}</h2>

      {fehler ? (
        <p className="fb-modal-text">
          {t.changelogOffline}{" "}
          <a href={t.changelogUrl} target="_blank" rel="noreferrer noopener">
            {t.changelogOpenOnline}
          </a>
        </p>
      ) : text === null ? (
        <p className="fb-muted">{t.loading}</p>
      ) : (
        <div className="fb-changelog">{rendere(text, version, t)}</div>
      )}
    </Modal>
  );
}

/**
 * Markdown-Teilmenge nach React-Elementen.
 *
 * Kein Fremdpaket und kein `innerHTML`: Der Text kommt aus dem Netz, und
 * fremden Text als HTML einzusetzen ist der klassische Weg, sich Skripte
 * einzufangen. React setzt hier ausschliesslich Textknoten - selbst wenn in
 * der Datei einmal `<script>` stuende, waere es sichtbarer Text.
 *
 * Abgedeckt ist genau das, was in CHANGELOG.md tatsaechlich vorkommt. Das
 * ist keine Faulheit, sondern der Vorteil einer Datei, die wir selbst
 * schreiben: Ein vollstaendiger Markdown-Uebersetzer waere hier ein Paket
 * von der Groesse des halben Frontends.
 *
 * Exportiert, damit sich die Uebersetzung ohne laufende Oberflaeche gegen die
 * echte CHANGELOG-Datei pruefen laesst.
 */
export function rendere(md: string, version: string | null, t: Strings): ReactNode[] {
  const zeilen = md.split("\n");
  const raus: ReactNode[] = [];
  let liste: ReactNode[] = [];
  // Der Rohtext des laufenden Listenpunkts, noch unuebersetzt.
  //
  // Das ist der Kern der Sache: Ein Punkt laeuft oft ueber mehrere Zeilen,
  // und Auszeichnungen halten sich nicht an Zeilenenden - ein `**` beginnt
  // in der einen Zeile und schliesst in der naechsten. Wer zeilenweise
  // uebersetzt, laesst genau diese Stellen roh stehen. Also erst sammeln,
  // dann uebersetzen, wenn der Punkt zu Ende ist.
  let punkt: string[] = [];
  let absatz: string[] = [];
  let imKopf = true;

  const punktSchliessen = () => {
    if (punkt.length) {
      liste.push(<li key={`l${liste.length}`}>{inline(punkt.join(" "))}</li>);
      punkt = [];
    }
  };
  const listeSchliessen = () => {
    punktSchliessen();
    if (liste.length) {
      raus.push(<ul key={`u${raus.length}`}>{liste}</ul>);
      liste = [];
    }
  };
  const absatzSchliessen = () => {
    if (absatz.length) {
      raus.push(<p key={`p${raus.length}`}>{inline(absatz.join(" "))}</p>);
      absatz = [];
    }
  };

  for (const roh of zeilen) {
    const zeile = roh.trimEnd();

    // Der Sprachumschalter und die Ueberschrift am Dateianfang gehoeren zur
    // Datei, nicht zum Inhalt - der Dialog hat beides schon.
    if (imKopf) {
      if (/^## /.test(zeile)) imKopf = false;
      else continue;
    }

    if (/^---\s*$/.test(zeile)) {
      listeSchliessen();
      absatzSchliessen();
      raus.push(<hr key={`h${raus.length}`} />);
      continue;
    }

    if (/^## /.test(zeile)) {
      listeSchliessen();
      absatzSchliessen();
      const fassung = zeile.slice(3).trim();
      // Die laufende Fassung markieren. Ohne sie liest man eine Liste von
      // Nummern und muss selbst abgleichen, wo man steht - und genau das ist
      // die Frage, mit der man den Dialog geoeffnet hat.
      const meine = version !== null && fassung === version;
      raus.push(
        <h3 key={`v${raus.length}`} className="fb-changelog-version">
          {fassung}
          {meine && <span className="fb-changelog-hier">{t.changelogYours}</span>}
        </h3>,
      );
      continue;
    }

    if (/^### /.test(zeile)) {
      listeSchliessen();
      absatzSchliessen();
      raus.push(
        <h4 key={`s${raus.length}`} className="fb-changelog-art">
          {zeile.slice(4).trim()}
        </h4>,
      );
      continue;
    }

    if (/^[-*] /.test(zeile)) {
      absatzSchliessen();
      punktSchliessen();
      punkt.push(zeile.slice(2).trim());
      continue;
    }

    // Eingerueckte Folgezeile: gehoert zum laufenden Listenpunkt.
    if (/^\s+\S/.test(roh) && punkt.length) {
      punkt.push(zeile.trim());
      continue;
    }

    if (!zeile) {
      // Eine Leerzeile beendet den Punkt, aber nicht die Liste: Zwischen
      // den Absaetzen EINES Punktes steht ebenfalls eine.
      punktSchliessen();
      absatzSchliessen();
      continue;
    }

    listeSchliessen();
    absatz.push(zeile.trim());
  }
  listeSchliessen();
  absatzSchliessen();
  return raus;
}

/** Fett, Kursiv und Code innerhalb einer Zeile. Alles andere bleibt Text. */
function inline(s: string): ReactNode[] {
  const teile: ReactNode[] = [];
  const muster = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let zuletzt = 0;
  let treffer: RegExpExecArray | null;

  while ((treffer = muster.exec(s)) !== null) {
    if (treffer.index > zuletzt) teile.push(s.slice(zuletzt, treffer.index));
    const stueck = treffer[0];
    if (stueck.startsWith("**")) {
      // Rekursiv, denn in einer fetten Stelle steht durchaus Code -
      // "**`quota/all` galt faelschlich ...**" kommt so in der Datei vor.
      teile.push(<strong key={teile.length}>{inline(stueck.slice(2, -2))}</strong>);
    } else if (stueck.startsWith("`")) {
      // Code NICHT rekursiv: Was zwischen den Haken steht, ist woertlich.
      teile.push(<code key={teile.length}>{stueck.slice(1, -1)}</code>);
    } else {
      teile.push(<em key={teile.length}>{inline(stueck.slice(1, -1))}</em>);
    }
    zuletzt = treffer.index + stueck.length;
  }
  if (zuletzt < s.length) teile.push(s.slice(zuletzt));
  return teile;
}
