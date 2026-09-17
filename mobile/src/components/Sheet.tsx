import { useEffect, useId, useRef, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { useT } from '@/app/LanguageContext';

/** A panel that rises from the bottom of the screen: the phone's answer to a
 *  dropdown, a picker, or a short menu (spec 015, P13-FR-050).
 *
 *  It closes the three ways a phone user expects - tapping the dimmed page
 *  above it, the Done button, and Back/Escape - and also when the route
 *  changes underneath it, because a sheet belongs to the screen it opened on.
 *
 *  Focus moves into the sheet when it opens and back to whatever opened it
 *  when it closes, so a keyboard or screen-reader user is never left on a
 *  control that is now covered. */
export function Sheet({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const t = useT();
  const { key: visit } = useLocation();
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  const titleId = useId();

  // A route change closes it. Skip the first run: opening is not a change.
  const firstVisit = useRef(visit);
  useEffect(() => {
    if (visit !== firstVisit.current) onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visit]);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      if (opener.current instanceof HTMLElement) opener.current.focus();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  return (
    <div className="sheet-layer">
      <button
        type="button"
        className="sheet-scrim"
        aria-label={t('phone.sheet.done')}
        tabIndex={-1}
        onClick={onClose}
      />
      <div
        ref={panel}
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <div className="sheet__grab" aria-hidden="true" />
        <div className="sheet__head">
          <div className="sheet__title" id={titleId}>{title}</div>
          <button type="button" className="linkbtn" onClick={onClose}>
            {t('phone.sheet.done')}
          </button>
        </div>
        <div className="sheet__body">{children}</div>
      </div>
    </div>
  );
}

/** One choice in a sheet: a full-width row with a tick on the current one. */
export function SheetOption({
  selected,
  onSelect,
  children,
}: {
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={selected ? 'sheet__option sheet__option--on' : 'sheet__option'}
      onClick={onSelect}
    >
      <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{children}</span>
      {selected && (
        <span className="sheet__tick" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 18 18" fill="none">
            <path d="M3.5 9.5 L7.5 13.5 L14.5 5" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      )}
    </button>
  );
}
