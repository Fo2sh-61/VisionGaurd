/** The cloud trial's engine is a free notebook with a time limit
 *  (specs/021-cloud-trial). Rule 4: it must not just vanish under somebody's
 *  console. When the engine says when it stops, this says so on every page:
 *  the time, then "stopping now", then "stopped" once it no longer answers.
 *
 *  On the workstation `/healthz` carries no `endsAt` and this renders nothing. */

import { useEffect, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import { getHealthz } from '@/services/api';
import { formatSessionEnd } from '@/services/format';

const POLL_MS = 30_000;
const LAST_STRETCH_MS = 15 * 60_000;
const CLOSE_POLL_MS = 10_000;

type State =
  | { kind: 'none' }
  | { kind: 'ends'; at: Date; offsetMs: number }
  | { kind: 'stopping' }
  | { kind: 'stopped' };

export function SessionNotice() {
  const { t, language: lang } = useLanguage();
  const [state, setState] = useState<State>({ kind: 'none' });
  const [, tick] = useState(0);

  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    // Only once an end has been announced does a failed probe mean "stopped".
    let announced = false;

    const poll = async () => {
      let next = POLL_MS;
      try {
        const health = await getHealthz();
        if (!alive) return;
        if (!health.endsAt) {
          setState({ kind: 'none' });
        } else if (health.stopping) {
          announced = true;
          setState({ kind: 'stopping' });
          next = CLOSE_POLL_MS;
        } else {
          announced = true;
          const at = new Date(health.endsAt);
          // The engine's clock, not this computer's, decides how long is left.
          const offsetMs = health.now - Date.now();
          setState({ kind: 'ends', at, offsetMs });
          if (at.getTime() - health.now < LAST_STRETCH_MS) next = CLOSE_POLL_MS;
        }
      } catch {
        if (!alive) return;
        if (announced) {
          setState({ kind: 'stopped' });
          next = CLOSE_POLL_MS;
        }
      }
      timer = window.setTimeout(poll, next);
    };

    poll();
    const minute = window.setInterval(() => tick((n) => n + 1), 30_000);
    return () => {
      alive = false;
      window.clearTimeout(timer);
      window.clearInterval(minute);
    };
  }, []);

  if (state.kind === 'none') return null;

  let text: string;
  let close = true;
  if (state.kind === 'ends') {
    const left = state.at.getTime() - (Date.now() + state.offsetMs);
    const minutes = Math.max(0, Math.round(left / 60_000));
    text = t('session.endsAt', { time: formatSessionEnd(state.at, lang), minutes });
    close = left < LAST_STRETCH_MS;
  } else if (state.kind === 'stopping') {
    text = t('session.stopping');
  } else {
    text = t('session.stopped');
  }

  return (
    <div
      role="status"
      style={{
        padding: '8px 40px',
        background: close ? 'var(--am-bg)' : 'transparent',
        color: close ? 'var(--am)' : 'inherit',
        borderBottom: `1px solid ${close ? 'var(--am)' : 'var(--line)'}`,
        fontSize: 13,
        fontWeight: 600,
      }}
    >
      {text}
    </div>
  );
}
