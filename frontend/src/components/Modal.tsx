import { useEffect, type ReactNode } from "react";

/**
 * Schlichter Overlay-Dialog für "Über" und "Hilfe".
 *
 * Bewusst ohne <dialog>-Element: dessen Browser-Standardstile (Rand, Backdrop,
 * Zentrierung) müssten für das CI ohnehin komplett überschrieben werden.
 *
 * Escape schließt, Klick auf den Hintergrund ebenfalls - Klicks INNERHALB des
 * Dialogs dürfen dabei nicht durchschlagen, sonst schlösse jeder Textklick
 * das Fenster.
 */
export default function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fb-modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="fb-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="fb-modal-close" onClick={onClose} aria-label="Schließen">
          ×
        </button>
        {children}
      </div>
    </div>
  );
}
