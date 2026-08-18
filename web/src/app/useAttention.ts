/** The "Needs your attention" feed.
 *
 *  Polls today; this is the seam where the WebSocket lands. When the engine
 *  starts pushing `LiveEvent`s, only this hook changes — Home does not.
 *
 *  Polling rather than a one-shot fetch because the whole point of the feed is
 *  that things appear without the user asking. A weapon detection sitting
 *  unseen until someone reloads the page would defeat it. */

import { useEffect, useState } from 'react';
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

const ACTION: Record<WireAttentionItem['kind'], string> = {
  weapon: 'Review the detection',
  intrusion: 'See the breach',
  camera: 'Check the camera',
  attendance: 'Open attendance',
  system: 'Open system health',
};

function toAttentionItem(item: WireAttentionItem): AttentionItem {
  return {
    id: item.id,
    kind: item.severity === 'critical' ? 'Needs review' : 'For information',
    icon: item.severity === 'critical' ? '!' : 'i',
    tone: severityToTone(item.severity),
    title: item.title,
    sub: `${formatEventTime(item.at)} · ${item.detail}`,
    action: ACTION[item.kind] ?? 'Open',
    to: TARGET[item.kind] ?? 'system',
  };
}

export function useAttention(): AttentionItem[] {
  const [items, setItems] = useState<AttentionItem[]>([]);

  useEffect(() => {
    let cancelled = false;

    const load = () =>
      getAttention()
        .then((next) => {
          if (cancelled) return;
          // Acknowledged items drop off the feed but are never deleted — the
          // history endpoints still return them.
          setItems(next.filter((i) => !i.acknowledged).map(toAttentionItem));
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
  }, []);

  return items;
}
