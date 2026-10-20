import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import { Card } from '@/components/ui';
import { getPushDevices, getPushKey, registerPushDevice, removePushDevice } from '@/services/api';

/** "Notifications on this phone" (spec 020, P9-FR-101/105).
 *
 *  Turning it on asks the phone's permission, subscribes this browser to the
 *  site's own push key, and registers the phone with the engine - switched
 *  OFF. It says "waiting for an administrator" until one switches it on in
 *  Settings → Alerts, the same as a new email recipient. Turning it off here
 *  unsubscribes and removes the phone from the list.
 *
 *  Which registration is this phone's is remembered in this browser only
 *  (`localStorage`): a convenience, never the truth. The truth is the
 *  engine's list, read every time this card opens. */

const DEVICE_KEY = 'vg.pushDevice';

type State =
  | { kind: 'checking' }
  | { kind: 'unsupported' }
  | { kind: 'blocked' }
  | { kind: 'off' }
  | { kind: 'waiting' }
  | { kind: 'on' }
  | { kind: 'problem'; reason: string };

function remembered(): string | null {
  try {
    return localStorage.getItem(DEVICE_KEY);
  } catch {
    return null;
  }
}

function remember(id: string | null): void {
  try {
    if (id) localStorage.setItem(DEVICE_KEY, id);
    else localStorage.removeItem(DEVICE_KEY);
  } catch {
    /* private mode: the card asks the engine again next time */
  }
}

/** The VAPID key as the browser wants it: base64url to bytes. */
function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (base64url.length % 4)) % 4);
  const text = atob(padded);
  const bytes = new Uint8Array(new ArrayBuffer(text.length));
  for (let i = 0; i < text.length; i += 1) bytes[i] = text.charCodeAt(i);
  return bytes;
}

function supported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
}

async function registration(): Promise<ServiceWorkerRegistration | undefined> {
  return navigator.serviceWorker.getRegistration();
}

export function PhoneNotifications() {
  const { t } = useLanguage();
  const [state, setState] = useState<State>({ kind: 'checking' });
  const [busy, setBusy] = useState(false);

  const check = useCallback(async () => {
    if (!supported() || !(await registration())) {
      setState({ kind: 'unsupported' });
      return;
    }
    if (Notification.permission === 'denied') {
      setState({ kind: 'blocked' });
      return;
    }
    const id = remembered();
    const subscribed = await (await registration())?.pushManager.getSubscription();
    if (!id || !subscribed) {
      setState({ kind: 'off' });
      return;
    }
    try {
      const mine = (await getPushDevices()).find((d) => d.id === id);
      // Not in the engine's list: an administrator removed it, or the push
      // service forgot it. Either way it receives nothing now.
      if (!mine) {
        remember(null);
        setState({ kind: 'off' });
        return;
      }
      setState({ kind: mine.enabled ? 'on' : 'waiting' });
    } catch (error) {
      setState({ kind: 'problem', reason: error instanceof Error ? error.message : String(error) });
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  async function turnOn() {
    setBusy(true);
    try {
      const key = await getPushKey();
      if (!key.available || !key.publicKey) {
        setState({ kind: 'problem', reason: key.reason ?? '' });
        return;
      }
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        setState({ kind: permission === 'denied' ? 'blocked' : 'off' });
        return;
      }
      const worker = await registration();
      if (!worker) {
        setState({ kind: 'unsupported' });
        return;
      }
      const subscription = await worker.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: keyBytes(key.publicKey),
      });
      const raw = subscription.toJSON();
      const device = await registerPushDevice({
        endpoint: raw.endpoint ?? subscription.endpoint,
        keys: { p256dh: raw.keys?.p256dh ?? '', auth: raw.keys?.auth ?? '' },
        label: /Android/i.test(navigator.userAgent) ? `Android ${t('push.defaultLabel')}` : t('push.defaultLabel'),
      });
      remember(device.id);
      setState({ kind: device.enabled ? 'on' : 'waiting' });
    } catch (error) {
      setState({ kind: 'problem', reason: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    try {
      const id = remembered();
      if (id) await removePushDevice(id);
      await (await (await registration())?.pushManager.getSubscription())?.unsubscribe();
      remember(null);
      setState({ kind: 'off' });
    } catch (error) {
      setState({ kind: 'problem', reason: error instanceof Error ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  const line: Record<State['kind'], string | null> = {
    checking: null,
    unsupported: t('push.unsupported'),
    blocked: t('push.blocked'),
    off: null,
    waiting: t('push.waiting'),
    on: t('push.on'),
    problem: state.kind === 'problem' ? t('push.failed', { reason: state.reason }) : null,
  };
  const canTurnOn = state.kind === 'off' || state.kind === 'problem';
  const canTurnOff = state.kind === 'waiting' || state.kind === 'on';

  return (
    <Card>
      <div style={{ fontWeight: 700, fontSize: 15 }}>{t('push.title')}</div>
      <div className="li__sub" style={{ margin: '2px 0 10px' }}>{t('push.lead')}</div>
      {line[state.kind] && (
        <div
          role="status"
          style={{
            fontSize: 13.5,
            marginBottom: 10,
            color: state.kind === 'on' ? 'var(--ac2)' : state.kind === 'waiting' ? 'var(--am)' : 'var(--tx2)',
          }}
        >
          {line[state.kind]}
        </div>
      )}
      {canTurnOn && (
        <button type="button" className="btn" disabled={busy} onClick={() => void turnOn()}>
          {busy ? t('push.working') : t('push.turnOn')}
        </button>
      )}
      {canTurnOff && (
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => void turnOff()}>
          {busy ? t('push.working') : t('push.turnOff')}
        </button>
      )}
    </Card>
  );
}
