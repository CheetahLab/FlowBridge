import type { Strings } from "../i18n";

/**
 * Wird gezeigt, wenn der Datenordner nicht beschreibbar ist.
 *
 * Der haeufigste Stolperstein auf einer Synology: Der eingebundene Ordner
 * gehoert dem NAS-Benutzer, FlowBridge laeuft als Benutzer 1000. Frueher
 * startete der Container in dieser Lage endlos neu, und im Browser war
 * nichts zu sehen - man suchte an der falschen Stelle.
 *
 * Deshalb nennt diese Meldung nicht nur den Fehler, sondern gleich den
 * Befehl, der ihn behebt. Eine Fehlermeldung, die den naechsten Schritt
 * verschweigt, ist nur halb so viel wert.
 */
export default function StorageError({ t, detail }: { t: Strings; detail: string }) {
  return (
    <div className="fb-card fb-storage-error">
      <h2>{t.storageErrorTitle}</h2>
      <p>{t.storageErrorText}</p>
      <pre className="fb-storage-detail">{detail}</pre>
      <p>{t.storageErrorFix}</p>
      <pre className="fb-storage-cmd">
        sudo chown -R 1000:1000 /volume1/docker/flowbridge/data
      </pre>
      <p className="fb-muted">{t.storageErrorAfter}</p>
    </div>
  );
}
