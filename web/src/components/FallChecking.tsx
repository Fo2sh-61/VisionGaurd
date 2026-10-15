import { useState } from 'react';
import { Badge, Card, Empty, LoadError, Toggle, toneGlyph } from '@/components/ui';
import { editCamera, getCameraSources } from '@/services/api';
import type { CameraSource } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useAsync } from '@/app/useAsync';
import { useT } from '@/app/LanguageContext';

/** "Fall checking" on System Health, from the owner's System Health design.
 *
 *  One switch per camera, and nothing new underneath it: a switch adds or
 *  removes `falls` from that camera's feature list through the same edit the
 *  camera form makes. The engine then starts or stops watching that camera on
 *  its next frame, writes the change to the audit log under the signed-in
 *  name, and refuses a camera too slow for the model (three frames a second)
 *  with a sentence - which is shown here as it is, rather than reworded.
 *
 *  `/sources` is administrator-only on the engine, so for anybody else this
 *  says who can change it rather than drawing switches that would be refused.
 *  The role check here is a courtesy; the engine is the boundary. */

const NO_SOURCES: CameraSource[] = [];
const REFRESH_MS = 15_000;

export function FallChecking() {
  const t = useT();
  const account = useAccount();
  const admin = account.role === 'admin';
  const { data: sources, error, loading, reload } = useAsync(
    () => (admin ? getCameraSources() : Promise.resolve(NO_SOURCES)),
    [admin], NO_SOURCES, REFRESH_MS);
  const [saving, setSaving] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  // Saved, but not running: not a failure, and not drawn as one.
  const [notice, setNotice] = useState<string | null>(null);

  const usable = sources.filter((s) => s.enabled);
  const checked = usable.filter((s) => s.features.includes('falls')).length;

  /** Write one camera's list, and say exactly what the engine said if not. */
  async function set(source: CameraSource, on: boolean): Promise<boolean> {
    const has = source.features.includes('falls');
    if (has === on) return true;
    const features = on
      ? [...source.features, 'falls']
      : source.features.filter((f) => f !== 'falls');
    try {
      const result = await editCamera(source.id, { features });
      // Saved, but the feature itself is not running on this engine: the
      // engine says why, and that is worth more than a switch that looks on.
      const note = result.featureNotes.find((n) => n.feature === 'falls' && !n.running);
      if (note?.reason) setNotice(t('health.falls.savedNotRunning', { reason: note.reason }));
      return true;
    } catch (err) {
      setFailure(t('health.falls.notSaved', {
        reason: err instanceof Error ? err.message : t('common.engineRefused'),
      }));
      return false;
    }
  }

  async function toggle(source: CameraSource) {
    setFailure(null);
    setNotice(null);
    setSaving(source.id);
    try {
      await set(source, !source.features.includes('falls'));
    } finally {
      setSaving(null);
      reload();
    }
  }

  async function all(on: boolean) {
    setFailure(null);
    setNotice(null);
    setSaving('*');
    try {
      // One at a time, so a camera the engine refuses (too slow, say) stops
      // nothing else and its reason is the one left on screen.
      for (const source of usable) {
        await set(source, on);
      }
    } finally {
      setSaving(null);
      reload();
    }
  }

  return (
    <Card>
      <div id="fall-checking" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: 17 }}>{t('health.falls.title')}</div>
          {admin && !loading && !error && (
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {checked > 0
                ? t('health.falls.sub', { count: checked, total: usable.length })
                : t('health.falls.subNone')}
            </div>
          )}
        </div>
        {admin && usable.length > 0 && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button type="button" className="btn btn--ghost" disabled={saving !== null}
              onClick={() => all(true)}>
              {t('health.falls.checkAll')}
            </button>
            <button type="button" className="btn btn--ghost" disabled={saving !== null}
              onClick={() => all(false)}>
              {t('health.falls.stopAll')}
            </button>
          </div>
        )}
      </div>

      {!admin && <Empty>{t('health.falls.adminOnly')}</Empty>}
      {admin && (
        <>
          <LoadError error={error} onRetry={reload} what="load.cameraList" />
          <LoadError error={failure} what="load.change" />
          {notice && (
            <div role="status" style={{ fontSize: 13, color: 'var(--am)', background: 'var(--am-bg)', borderRadius: 'var(--radius-md)', padding: '8px 12px', marginBottom: 8 }}>
              {notice}
            </div>
          )}
          {loading && <Empty>{t('health.falls.loading')}</Empty>}
          {sources.length > 0 && (
            <div
              className="row"
              style={{
                gridTemplateColumns: '1.3fr 1fr 1fr 60px',
                color: 'var(--tx3)',
                fontSize: 12,
                fontWeight: 600,
                letterSpacing: '.03em',
                textTransform: 'uppercase',
              }}
            >
              <span>{t('health.falls.col.camera')}</span>
              <span>{t('health.falls.col.area')}</span>
              <span>{t('health.falls.col.falls')}</span>
              <span />
            </div>
          )}
          {sources.map((source) => {
            const on = source.features.includes('falls');
            return (
              <div key={source.id} className="row" style={{ gridTemplateColumns: '1.3fr 1fr 1fr 60px', alignItems: 'center' }}>
                <span className="row__name">{source.name}</span>
                <span className="row__muted">{source.area}</span>
                <span>
                  {source.enabled ? (
                    <Badge tone={on ? 'good' : 'neutral'} glyph={toneGlyph[on ? 'good' : 'neutral']}>
                      {t(on ? 'health.falls.checked' : 'health.falls.notChecked')}
                    </Badge>
                  ) : (
                    <Badge tone="neutral" glyph={toneGlyph.neutral}>{t('health.falls.switchedOff')}</Badge>
                  )}
                </span>
                <span>
                  {source.enabled && (
                    <Toggle
                      on={on}
                      label={t('health.falls.toggle', { camera: source.name })}
                      onToggle={() => {
                        if (saving === null) void toggle(source);
                      }}
                    />
                  )}
                </span>
              </div>
            );
          })}
        </>
      )}
      <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 10 }}>{t('health.falls.note')}</div>
    </Card>
  );
}
