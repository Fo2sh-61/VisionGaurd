import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

/** What the alert bell knows, for whichever app is drawing it.
 *
 *  Lifted out of the console's `components/AlertBell.tsx` on 17 Sep 2026
 *  (spec 015), when the phone got a bell of its own. The console draws this as
 *  a dropdown; the phone draws it as a marker in its top bar and a screen of
 *  its own. The number both of them show - **what is new since this person
 *  last looked** (owner's choice, 11 Sep 2026) - is decided here once, and the
 *  file is on `tools/check_parity.py`'s list, so the two cannot disagree.
 *
 *  Nothing in here draws. `open` is whether the list is on screen right now:
 *  the console's dropdown is open, or the phone's alerts screen is mounted.
 *  While it is, anything that arrives is seen as it arrives. */

/** How often the bell asks whether anything is waiting. Home's list polls at
 *  the same pace, so the two are never far apart. */
const CHECK_MS = 15_000;

/** How many seen items one browser remembers per account. Far more than are
 *  ever open at once; the cap only stops the list growing for ever. */
const SEEN_MAX = 500;

const NONE: WireAttentionItem[] = [];

/** What the bell can honestly say, in the order that decides it.
 *
 *  "Nothing needs attention" needs three things at once: the engine answered,
 *  its feed is running, and the feed is empty. An empty list from a feed that
 *  is not running is not an all-clear, and neither is the last list from an
 *  engine that has stopped answering - so in every other state the bell says
 *  what it cannot know, and shows no list it cannot vouch for. */
export type Feed = 'down' | 'failed' | 'checking' | 'off' | 'ready';

function feedState(engineDown: boolean, capability: Capability | null,
                   error: string | null, loading: boolean): Feed {
  if (engineDown) return 'down';
  if (error) return 'failed';
  if (loading || !capability) return 'checking';
  if (capability.state === 'unavailable') return 'off';
  return 'ready';
}

export interface StatusLine {
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

export interface AlertFeed {
  feed: Feed;
  /** The sentence that says what the bell knows, and its colour. */
  line: StatusLine;
  /** The attention feed's capability: its reason when off, `demo` when demo. */
  capability: Capability | null;
  /** Every open item, worded in the reader's language. Empty unless `ready`. */
  items: AttentionItem[];
  /** Open items this person has not seen yet. */
  unread: AttentionItem[];
  /** A number while the bell knows; "!" while it cannot, because a quiet bell
   *  would read as an all-clear; null while the first answer is on its way. */
  marker: { text: string; color: string } | null;
  /** The bell's accessible name: "Alerts" or "Alerts, 3 new". */
  label: string;
  /** Goes up by one each time something new arrives, never on the first
   *  answer, which is not an arrival, and never on a count going down. */
  rings: number;
  /** What was new when the list opened, plus what arrived while it was open. */
  newGroup: AttentionItem[];
  /** Everything else that is open. */
  seenGroup: AttentionItem[];
  /** Call as the list opens: remembers what was new, then marks it all seen. */
  opened: () => void;
}

export function useAlertFeed(open: boolean): AlertFeed {
  const { language, t } = useLanguage();
  const account = useAccount();
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

  // The top group: what was new when the list opened, plus anything that
  // arrived while it was open.
  const [fresh, setFresh] = useState<string[]>([]);

  function opened() {
    setFresh(unread.map((i) => i.id));
    markSeen(items.map((i) => i.id));
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

  return {
    feed,
    line,
    capability,
    items,
    unread,
    marker,
    label,
    rings,
    newGroup: items.filter((i) => fresh.includes(i.id)),
    seenGroup: items.filter((i) => !fresh.includes(i.id)),
    opened,
  };
}
