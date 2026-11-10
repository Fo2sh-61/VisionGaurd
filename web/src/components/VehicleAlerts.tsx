import { useState } from 'react';
import { Card } from '@/components/ui';
import { dismissVehicleAlert, getVehicleAlerts } from '@/services/api';
import {
  alertAction, alertDismissLabel, alertMessage, formatClock,
} from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';

/** Alerts change when a car passes, not frame by frame. */
const REFRESH_MS = 4_000;

const NONE: W.GateAlert[] = [];

const TONE: Record<W.GateAlert['kind'], { bg: string; fg: string }> = {
  blacklist: { bg: 'var(--rd-bg)', fg: 'var(--rd)' },
  unknown: { bg: 'var(--am-bg)', fg: 'var(--am)' },
  expired: { bg: 'var(--am-bg)', fg: 'var(--am)' },
};

function AlertRow({ alert, isAdmin, onResolve, onDismiss, linkedRef }: {
  alert: W.GateAlert;
  isAdmin: boolean;
  onResolve: (alert: W.GateAlert) => void;
  onDismiss: (alert: W.GateAlert) => void;
  /** Set on the one row an alert elsewhere linked to. */
  linkedRef?: (element: HTMLElement | null) => void;
}) {
  const { language } = useLanguage();
  const [busy, setBusy] = useState(false);
  const tone = TONE[alert.kind];
  const action = alertAction(alert.kind);

  return (
    <div
      ref={linkedRef}
      aria-current={linkedRef ? true : undefined}
      style={{
        ...(linkedRef ? LINKED_STYLE : null),
        display: 'flex', alignItems: 'center', gap: 14, padding: '13px 16px',
        borderRadius: 10, background: tone.bg,
        borderInlineStart: `4px solid ${tone.fg}`, flexWrap: 'wrap',
      }}
    >
      <span style={{
        flex: 1, minWidth: 220, fontSize: 13.5, fontWeight: 600,
        color: tone.fg, lineHeight: 1.4,
      }}>
        {alertMessage(alert, language)}
      </span>

      <span style={{
        fontSize: 12.5, color: 'var(--tx2)',
        fontFamily: 'ui-monospace, Menlo, monospace', whiteSpace: 'nowrap',
      }}>
        {formatClock(alert.at)}
      </span>

      {/* A blacklisted car has the dismissal and nothing else: there is
          nothing the console can do about a car that has already driven in,
          and a button that implied otherwise would be a dead control. Acting
          on the other two means writing the register, which stays
          admin-only — the server refuses it regardless of what this draws. */}
      {action && isAdmin && (
        <button
          type="button"
          className="chip-btn"
          disabled={busy}
          // Only opens the register form. The alert stays until the form
          // has actually saved: dismissing here recorded "acted on" for
          // somebody who then closed the form and did nothing.
          onClick={() => onResolve(alert)}
          style={{
            fontSize: 12.5, fontWeight: 600, color: 'var(--on-ac)',
            cursor: 'pointer', padding: '8px 14px', borderRadius: 9,
            background: tone.fg, border: 'none', whiteSpace: 'nowrap',
          }}
        >
          {action}
        </button>
      )}

      {/* Dismissing is the one write under /vehicles a guard may make — the
          person standing at the gate is a guard, and an alert only an admin
          can clear piles up all shift until nobody reads it. */}
      <button
        type="button"
        className="chip-btn"
        disabled={busy}
        onClick={() => { setBusy(true); onDismiss(alert); }}
        style={{
          fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)',
          cursor: busy ? 'default' : 'pointer', padding: '8px 12px',
          borderRadius: 9, background: 'var(--card)', border: 'none',
          whiteSpace: 'nowrap', opacity: busy ? 0.6 : 1,
        }}
      >
        {busy ? 'Clearing…' : alertDismissLabel(alert.kind)}
      </button>
    </div>
  );
}

/** The alerts strip at the top of the Live tab.
 *
 *  **Every one of these waits for a person, and clearing one is recorded
 *  under their name.** That is the promise the page makes, so the dismissal
 *  is a database row and an audit entry, not a filter this component
 *  remembers — a reload must not resurrect work somebody has already done,
 *  and a colleague on another screen must see it disappear too.
 *
 *  A dismissal applies to the *pass*, never to the car. The same vehicle
 *  passing again raises a fresh alert, which is deliberate: silencing a car
 *  would be a filter somebody set at 8am and then stopped seeing a
 *  blacklisted vehicle for the rest of the day. */
export function VehicleAlerts({ isAdmin, onRegister }: {
  isAdmin: boolean;
  onRegister: (alert: W.GateAlert) => void;
}) {
  const t = useT();
  const toast = useToast();
  const { data: alerts, error, loading, reload } = useAsync(
    () => getVehicleAlerts(), [], NONE, REFRESH_MS);
  // The alert bell and Home land here on one pass: `?pass=` is its id.
  const linked = useLinkedItem('pass');
  // This list is what is waiting, so a pass missing from a list that loaded
  // is a pass nobody is waiting on any more. A list that failed says nothing.
  const linkedMissing = linked.id !== null && !loading && !error
    && !alerts.some((a) => a.passId === linked.id);
  const missingNote = linkedMissing && (
    <div className="linked-missing" role="status">{t('gate.linkedNotWaiting')}</div>
  );

  async function clear(alert: W.GateAlert, actionTaken: boolean) {
    try {
      await dismissVehicleAlert(alert.passId, actionTaken);
      toast.show(t('gate.dismissedToast'));
    } finally {
      // Reload either way. A dismissal that raced another screen comes back
      // 409, and the honest response to that is to show what is actually
      // outstanding now rather than to report an error at this operator.
      reload();
    }
  }

  if (alerts.length === 0) return missingNote || null;

  return (
    <Card>
      {missingNote}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        gap: 12, flexWrap: 'wrap', marginBottom: 12,
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 15.5 }}>
            {alerts.length} {alerts.length === 1 ? 'alert' : 'alerts'} waiting
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 2 }}>
            Each one names the thing that clears it. Dismissing without doing
            it is recorded too, under your name.
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {alerts.map((alert) => (
          <AlertRow
            key={alert.passId}
            alert={alert}
            isAdmin={isAdmin}
            onResolve={(a) => onRegister(a)}
            onDismiss={(a) => { void clear(a, false); }}
            linkedRef={alert.passId === linked.id ? linked.ref : undefined}
          />
        ))}
      </div>
    </Card>
  );
}
