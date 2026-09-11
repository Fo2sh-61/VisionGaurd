import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useCapability, type Capability } from '@/app/CapabilityContext';
import { useLanguage, type Translate } from '@/app/LanguageContext';
import { useSite } from '@/app/SiteContext';
import { useAsync } from '@/app/useAsync';
import { toAttentionItem } from '@/app/useAttention';
import { getAttention } from '@/services/api';
import { formatCount } from '@/services/format';
import type { AttentionItem as WireAttentionItem } from '@/services/wire';
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
 *  Console only. The phone keeps Home's list until its own redesign lands. */

/** How often the bell asks whether anything is waiting. Home's list polls at
 *  the same pace, so the two are never far apart. */
const CHECK_MS = 15_000;

/** How many seen items one browser remembers per account. Far more than are
 *  ever open at once; the cap only stops the list growing for ever. */
const SEEN_MAX = 500;

const NONE: WireAttentionItem[] = [];

/** 18×18, stroked, in the hand of the sidebar's icons. */
const BELL =
  'M9 2.9c-2.5 0-4.3 1.9-4.3 4.4v3.1l-1.4 2.2h11.4l-1.4-2.2V7.3c0-2.5-1.8-4.4-4.3-4.4z'
  + 'M7.4 14.7c.3.8.9 1.2 1.6 1.2s1.3-.4 1.6-1.2';

/** What the bell can honestly say, in the order that decides it.
 *
 *  "Nothing needs attention" needs three things at once: the engine answered,
 *  its feed is running, and the feed is empty. An empty list from a feed that
 *  is not running is not an all-clear, and neither is the last list from an
 *  engine that has stopped answering - so in every other state the bell says
 *  what it cannot know, and shows no list it cannot vouch for. */
type Feed = 'down' | 'failed' | 'checking' | 'off' | 'ready';

function feedState(engineDown: boolean, capability: Capability | null,
                   error: string | null, loading: boolean): Feed {
  if (engineDown) return 'down';
  if (error) return 'failed';
  if (loading || !capability) return 'checking';
  if (capability.state === 'unavailable') return 'off';
  return 'ready';
}

interface StatusLine {
  color: string;
  glyph: string | null;
  title: string;
}

function statusLine(t: Translate, feed: Feed, open: AttentionItem[], count: string): StatusLine {
  switch (feed) {
    case 'down':
      return { color: 'var(--rd)', glyph: '!', title: t('topbar.engineUnreachable') };
    case 'failed':
      return { color: 'var(--am)', glyph: '!', title: t('bell.failed') };
    case 'checking':
      return { color: 'var(--tx3)', glyph: null, title: t('bell.checking') };
    case 'off':
      return { color: 'var(--am)', glyph: '!', title: t('bell.off') };
    default:
      if (open.length === 0) return { color: 'var(--ac)', glyph: '✓', title: t('bell.calm') };
      return {
        color: open.some((i) => i.tone === 'bad') ? 'var(--rd)' : 'var(--am)',
        glyph: '!',
        title: open.length === 1 ? t('bell.waitingOne') : t('bell.waiting', { count }),
      };
  }
}

function seenKey(accountId: string): string {
  return `vg.alerts.seen.${accountId}`;
}

function readSeen(key: string): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(key) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter((id): id is string => typeof id === 'string') : [];
  } catch {
    return [];
  }
}

function writeSeen(key: string, ids: string[]): void {
  try {
    localStorage.setItem(key, JSON.stringify(ids));
  } catch {
    /* blocked or full: the number forgets on the next visit, nothing worse */
  }
}

/** Which items this person has already seen in the bell, on this browser.
 *  Every tab shares it: opening the bell in one clears the number in all. */
function useSeen(accountId: string) {
  const key = seenKey(accountId);
  const [seen, setSeen] = useState<string[]>(() => readSeen(key));
  // What this tab knows even when storage is blocked and reads come back empty.
  const latest = useRef(seen);
  latest.current = seen;

  useEffect(() => {
    setSeen(readSeen(key));
    const onStorage = (event: StorageEvent) => {
      if (event.key === key) setSeen(readSeen(key));
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [key]);

  const markSeen = useCallback((ids: string[]) => {
    const known = new Set([...readSeen(key), ...latest.current]);
    const fresh = ids.filter((id) => !known.has(id));
    if (fresh.length === 0) return;
    const next = [...known, ...fresh].slice(-SEEN_MAX);
    writeSeen(key, next);
    latest.current = next;
    setSeen(next);
  }, [key]);

  return { seen, markSeen };
}

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
  const { language, t } = useLanguage();
  const account = useAccount();
  const navigate = useNavigate();
  const { key: visit } = useLocation();
  const { error: engineError } = useSite();
  const capability = useCapability('attention');
  const request = useAsync(
    // Acknowledged items stay in the history, but somebody has dealt with them.
    () => getAttention().then((items) => items.filter((i) => !i.acknowledged)),
    [], NONE, CHECK_MS,
  );
  const feed = feedState(engineError !== null, capability, request.error, request.loading);

  // Worded at render rather than when the answer lands, so switching language
  // rewords the list at once.
  const items = useMemo(
    () => (feed === 'ready' ? request.data.map((i) => toAttentionItem(i, t, language)) : []),
    [feed, request.data, t, language],
  );
  const line = statusLine(t, feed, items, formatCount(items.length, language));

  const { seen, markSeen } = useSeen(account.id);
  const unread = items.filter((i) => !seen.includes(i.id));
  const unreadKey = unread.map((i) => i.id).join('\n');

  const [open, setOpen] = useState(false);
  // The top group: what was new when the list opened, plus anything that
  // arrived while it was open.
  const [fresh, setFresh] = useState<string[]>([]);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  function show() {
    setFresh(unread.map((i) => i.id));
    markSeen(items.map((i) => i.id));
    setOpen(true);
  }

  // Anything that lands while the list is open is seen as it lands.
  useEffect(() => {
    if (!open || unread.length === 0) return;
    const ids = unread.map((i) => i.id);
    setFresh((current) => [...current, ...ids.filter((id) => !current.includes(id))]);
    markSeen(ids);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, unreadKey]);

  // One swing of the bell when something new arrives - never on the first
  // answer, which is not an arrival, and never on a count going down.
  const [rings, setRings] = useState(0);
  const lastUnread = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (feed !== 'ready') return;
    const now = new Set(unread.map((i) => i.id));
    const before = lastUnread.current;
    lastUnread.current = now;
    if (before && [...now].some((id) => !before.has(id))) setRings((n) => n + 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [feed, unreadKey]);

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

  // A number while the bell knows; "!" while it cannot, because a quiet bell
  // would read as an all-clear; nothing while the first answer is on its way.
  const marker = feed === 'ready'
    ? unread.length > 0
      ? {
        text: unread.length > 9
          ? `${formatCount(9, language)}+` : formatCount(unread.length, language),
        color: unread.some((i) => i.tone === 'bad') ? 'var(--rd)' : 'var(--am)',
      }
      : null
    : feed === 'checking' ? null : { text: '!', color: line.color };
  const label = feed === 'ready' && unread.length > 0
    ? t('bell.titleNew', { count: formatCount(unread.length, language) })
    : t('bell.title');

  const newGroup = items.filter((i) => fresh.includes(i.id));
  const seenGroup = items.filter((i) => !fresh.includes(i.id));

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
