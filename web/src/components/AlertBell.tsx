import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useT } from '@/app/LanguageContext';
import { useAlertFeed } from '@/app/useAlertFeed';
import type { AttentionItem } from '@/types';
import { toneColors } from './ui';

/** The alert bell, top right of every console page.
 *
 *  It replaced a status block at the foot of the sidebar that said how many
 *  things needed attention and could not be clicked. The bell says the same
 *  thing, opens into the list, and each item opens the thing itself - the
 *  knife entry, the zone scene, the gate pass, the dark camera.
 *
 *  **The number is what is new since this person last opened the bell**
 *  (owner's choice, 11 Sep 2026), not what is open: opening the list clears
 *  it. Nothing still open is hidden by that - the list keeps every open
 *  item, split at the moment of the last look into "New since you last
 *  looked" and "Still open". Acknowledging stays on Home and on the pages,
 *  where it is audited; the bell only lists and opens.
 *
 *  What the bell knows lives in `app/useAlertFeed.ts`, shared with the phone
 *  (spec 015) so both apps count the same things. This file is only the
 *  console's way of drawing it: a button and a dropdown. */

/** 18×18, stroked, in the hand of the sidebar's icons. */
const BELL =
  'M9 2.9c-2.5 0-4.3 1.9-4.3 4.4v3.1l-1.4 2.2h11.4l-1.4-2.2V7.3c0-2.5-1.8-4.4-4.3-4.4z'
  + 'M7.4 14.7c.3.8.9 1.2 1.6 1.2s1.3-.4 1.6-1.2';

function Group({ label, items, onOpen }: {
  label: string;
  items: AttentionItem[];
  onOpen: (item: AttentionItem) => void;
}) {
  return (
    <div className="bell__group" role="group" aria-label={label}>
      <div className="bell__eyebrow" aria-hidden="true">{label}</div>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="bell__item"
          // The rail is the glance; the words beside it are the reading, so
          // the difference never rests on colour alone.
          style={{ borderInlineStartColor: toneColors[item.tone].fg }}
          onClick={() => onOpen(item)}
        >
          <span className="bell__item-title">{item.title}</span>
          <span className="bell__item-sub">{item.sub}</span>
          <span className="bell__item-foot">
            <span style={{ color: toneColors[item.tone].fg }}>{item.kind}</span>
            <span className="bell__item-action">
              {item.action} <span className="mirror-rtl" aria-hidden="true">→</span>
            </span>
          </span>
        </button>
      ))}
    </div>
  );
}

export function AlertBell() {
  const t = useT();
  const navigate = useNavigate();
  const { key: visit } = useLocation();

  const [open, setOpen] = useState(false);
  const {
    feed, line, capability, items, unread, marker, label, rings, newGroup, seenGroup, opened,
  } = useAlertFeed(open);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  function show() {
    opened();
    setOpen(true);
  }

  // Leaving the page closes the list: it opened over the page it was on.
  useEffect(() => setOpen(false), [visit]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  function go(item: AttentionItem) {
    setOpen(false);
    navigate(item.link, { state: { autoRun: true } });
  }

  return (
    <div ref={root} className="bell">
      <button
        ref={button}
        type="button"
        className="bell__button"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={label}
        title={line.title}
        onClick={() => (open ? setOpen(false) : show())}
      >
        <svg
          key={rings}
          className={rings > 0 ? 'bell__icon bell__icon--ring' : 'bell__icon'}
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          aria-hidden="true"
        >
          <path d={BELL} stroke="currentColor" strokeWidth="1.6"
                strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {marker && (
          <span className="bell__marker" style={{ background: marker.color }}>{marker.text}</span>
        )}
      </button>
      {/* Says a new arrival out loud; the number alone is silent. */}
      <span className="bell__live" role="status">
        {feed === 'ready' && unread.length > 0 ? label : ''}
      </span>

      {open && (
        <div className="bell__panel" role="dialog" aria-label={t('bell.title')}>
          <div className="bell__head">
            <div className="bell__title">{t('bell.title')}</div>
            <div className="bell__status" style={{ color: line.color }}>
              {line.glyph && (
                <span className="glyph" style={{ background: line.color }}>{line.glyph}</span>
              )}
              {line.title}
            </div>
            {feed === 'off' && (
              <>
                <div className="bell__lead">{t('bell.offLead')}</div>
                {/* The engine's own reason, in full: a list that is not
                    running must say why, not only on hover. */}
                {capability?.reason && <div className="bell__reason">{capability.reason}</div>}
              </>
            )}
            {feed === 'ready' && capability?.state === 'demo' && (
              <div className="bell__lead">{t('state.demoData')}</div>
            )}
          </div>

          {items.length > 0 && (
            <div className="bell__list">
              {newGroup.length > 0 && (
                <Group label={t('bell.groupNew')} items={newGroup} onOpen={go} />
              )}
              {seenGroup.length > 0 && (
                <Group label={t('bell.groupSeen')} items={seenGroup} onOpen={go} />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
