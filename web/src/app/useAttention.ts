/** The "Needs your attention" feed.
 *
 *  Polls today; this is the seam where the WebSocket lands. When the engine
 *  starts pushing `LiveEvent`s, only this hook changes — Home does not.
 *
 *  Polling rather than a one-shot fetch because the whole point of the feed is
 *  that things appear without the user asking. A weapon detection sitting
 *  unseen until someone reloads the page would defeat it. */

import { useCallback, useEffect, useState } from 'react';
import { useLanguage, type Translate } from '@/app/LanguageContext';
import type { Language, MessageKey } from '@/i18n';
import { acknowledgeAttention, getAttention } from '@/services/api';
import { formatEventTime, severityToTone } from '@/services/format';
import { noteText } from '@/services/notes';
import type { AttentionItem, ToolId } from '@/types';
import type { AttentionItem as WireAttentionItem } from '@/services/wire';

const POLL_MS = 15_000;

/** Which page each kind of alert opens. */
const TARGET: Record<WireAttentionItem['kind'], ToolId> = {
  weapon: 'weapons',
  intrusion: 'intrusion',
  vehicles: 'vehicles',
  camera: 'system',
  attendance: 'attendance',
  system: 'system',
};

const ACTION: Record<WireAttentionItem['kind'], MessageKey> = {
  weapon: 'attention.action.weapon',
  intrusion: 'attention.action.intrusion',
  vehicles: 'attention.action.vehicles',
  camera: 'attention.action.camera',
  attendance: 'attention.action.attendance',
  system: 'attention.action.system',
};

/** A plain function, called from a promise callback - so it takes the
 *  language as an argument. It used to call `useLanguage()` itself, which is
 *  a hook outside render; that only went unnoticed because the live feed was
 *  always empty. */
function toAttentionItem(item: WireAttentionItem, t: Translate, language: Language): AttentionItem {
  // What happened: the engine's note, worded here in the reader's language,
  // or the demo store's own detail line.
  const said = noteText(t, item.note) || item.detail;
  const when = formatEventTime(item.at, language);
  return {
    id: item.id,
    kind: t(item.severity === 'critical'
      ? 'attention.needsReview' : 'attention.forInformation'),
    icon: item.severity === 'critical' ? '!' : 'i',
    tone: severityToTone(item.severity),
    title: item.title,
    sub: said ? `${when} · ${said}` : when,
    action: t(ACTION[item.kind] ?? 'attention.action.open'),
    to: TARGET[item.kind] ?? 'system',
  };
}

export interface Attention {
  items: AttentionItem[];
  /** Acknowledge one item under the signed-in account - the engine takes the
   *  name from the session. True when it was acknowledged; on failure the item
   *  stays, because it has not been dealt with. */
  acknowledge: (id: string) => Promise<boolean>;
}

export function useAttention(): Attention {
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [tick, setTick] = useState(0);
  const { language, t } = useLanguage();

  const acknowledge = useCallback(async (id: string) => {
    try {
      await acknowledgeAttention(id);
    } catch {
      setTick((n) => n + 1);
      return false;
    }
    setItems((current) => current.filter((i) => i.id !== id));
    setTick((n) => n + 1);
    return true;
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = () =>
      getAttention()
        .then((next) => {
          if (cancelled) return;
          // Acknowledged items drop off the feed but are never deleted — the
          // history endpoints still return them.
          setItems(next.filter((i) => !i.acknowledged)
            .map((i) => toAttentionItem(i, t, language)));
        })
        .catch(() => {
          /* leave the last known feed rather than blanking it on one bad poll */
        });

    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // `t` and `language` are dependencies so switching language re-renders
    // the feed with the new wording rather than leaving the last language on
    // screen until the next poll; `tick` re-reads after an acknowledgement.
  }, [t, language, tick]);

  return { items, acknowledge };
}
