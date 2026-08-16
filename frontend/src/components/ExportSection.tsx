import { useState } from "react";
import type { Strings } from "../i18n";

/**
 * Topic-Export: generische Liste und EisBär-Import-Dateien.
 *
 * Echte Links statt fetch — der Browser soll die Dateien selbst speichern,
 * mit dem Dateinamen aus dem Header.
 *
 * Die Reihenfolge der beiden EisBär-Dateien ist nicht kosmetisch: Die CSV
 * verweist auf Profile, die zum Importzeitpunkt schon existieren müssen.
 * Deshalb sind sie nummeriert — und wer das ZIP nimmt, hat die Reihenfolge
 * schon in den Dateinamen.
 *
 * Der Modul-Schalter ist standardmäßig AUS: die Rohwerte der Module sind zum
 * Nachschauen da, im Alltag arbeitet man mit den Einzelwerten. Eingeschaltet
 * wächst das Profil-XML um rund 50 Knoten.
 */
export default function ExportSection({ t }: { t: Strings }) {
  const [mitModulen, setMitModulen] = useState(false);
  const q = mitModulen ? "?modules=true" : "";

  return (
    <>
      <h2>{t.exportTitle}</h2>
      <p className="fb-muted">{t.exportHint}</p>

      <label className="fb-check">
        <input
          type="checkbox"
          checked={mitModulen}
          onChange={(e) => setMitModulen(e.target.checked)}
        />
        <span>{t.exportWithModules}</span>
      </label>
      <p className="fb-muted fb-export-modhint">{t.exportModulesHint}</p>

      {/* Nebeneinander, um die Kachel kurz zu halten. Die EisBär-Spalte ist
          deutlich höher als die allgemeine — der gewonnene Platz ist genau
          die Höhe des einzelnen Knopfes links. */}
      <div className="fb-export-cols">
        <section>
          <h3 className="fb-export-sub">{t.exportGenericTitle}</h3>
          <div className="fb-actions">
            <a className="fb-toggle" href={`/api/export/generic${q}`}>
              {t.exportGeneric}
            </a>
          </div>
        </section>

        <section>
          <h3 className="fb-export-sub">{t.exportEisbaer}</h3>
          {/* Die Einzeldateien zuerst: so steht "1. Payloadeditor" auf einer
              Linie mit "Topic-Liste" in der linken Spalte. Das ZIP fasst sie
              darunter zusammen. */}
          <ol className="fb-export-steps">
            <li>
              <a className="fb-toggle" href={`/api/export/eisbaer/profiles${q}`}>
                1. {t.exportProfiles}
              </a>
              <span className="fb-muted"> {t.exportProfilesHint}</span>
            </li>
            <li>
              <a className="fb-toggle" href={`/api/export/eisbaer/channels${q}`}>
                2. {t.exportChannels}
              </a>
              <span className="fb-muted"> {t.exportChannelsHint}</span>
            </li>
          </ol>
          <div className="fb-actions fb-export-zip">
            <a className="fb-toggle fb-toggle-primary" href={`/api/export/eisbaer/zip${q}`}>
              {t.exportZip}
            </a>
          </div>
        </section>
      </div>

      <p className="fb-muted fb-export-note">{t.exportOrderNote}</p>
    </>
  );
}
