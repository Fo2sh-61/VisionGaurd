/** The "Needs your attention" feed.
 *
 *  Polls today; this is the seam where the WebSocket lands. When the engine
 *  starts pushing `LiveEvent`s, only this hook changes — Home does not.
 *
 *  Polling rather than a one-shot fetch because the whole point of the feed is
 *  that things appear without the user asking. A weapon detection sitting
 *  unseen until someone reloads the page would defeat it. */

import { useEffect, useState } from 'react';
import { useLanguage, useT, type Translate } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';
import { getAttention } from '@/services/api';
import { formatEventTime, severityToTone } from '@/services/format';
import type { AttentionItem, ToolId } from '@/types';
import type { AttentionItem as WireAttentionItem } from '@/services/wire';

const POLL_MS = 15_000;

/** Which page each kind of alert opens. */
const TARGET: Record<WireAttentionItem['kind'], ToolId> = {
  weapon: 'weapons',
  intrusion: 'intrusion',
  camera: 'system',
  attendance: 'attendance',
  system: 'system',
};

const ACTION: Record<WireAttentionItem['kind'], MessageKey> = {
  weapon: 'attention.action.weapon',
  intrusion: 'attention.action.intrusion',
  camera: 'attention.action.camera',
  attendance: 'attention.action.attendance',
  system: 'attention.action.system',
};

function toAttentionItem(item: WireAttentionItem, t: Translate): AttentionItem {
  const { language } = useLanguage();
  return {
    id: item.id,
    kind: t(item.severity === 'critical'
      ? 'attention.needsReview' : 'attention.forInformation'),
    icon: item.severity === 'critical' ? '!' : 'i',
    tone: severityToTone(item.severity),
    title: item.title,
    sub: `${formatEventTime(item.at, language)} · ${item.detail}`,
    action: t(ACTION[item.kind] ?? 'attention.action.open'),
    to: TARGET[item.kind] ?? 'system',
  };
}

export function useAttention(): AttentionItem[] {
  const [items, setItems] = useState<AttentionItem[]>([]);
  const t = useT();

  useEffect(() => {
    let cancelled = false;

    const load = () =>
      getAttention()
        .then((next) => {
          if (cancelled) return;
          // Acknowledged items drop off the feed but are never deleted — the
          // history endpoints still return them.
          setItems(next.filter((i) => !i.acknowledged)
            .map((i) => toAttentionItem(i, t)));
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
    // `t` is in the dependencies so switching language re-renders the feed
    // with the new wording rather than leaving the last language on screen
    // until the next poll.
  }, [t]);

  return items;
}
