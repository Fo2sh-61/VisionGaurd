import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { CamGrid } from '@/components/CamGrid';
import { CameraFrame } from '@/components/CameraFrame';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, toneColors, toneGlyph } from '@/components/ui';
import {
  getFallCameras,
  getFalls,
  getFallsNow,
  getFallsStatus,
  markNotAFall,
  respondToFall,
  undoFallResponse,
} from '@/services/api';
import type { Camera, FallEntry, FallsStatus, FallWindow } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useSite } from '@/app/SiteContext';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/** The owner's Falls design (`design/VisionGuard web app design/Falls.dc.html`):
 *  passive watch, optional actions. Somebody who goes down and stays down is
 *  on this page at once, with the camera on them; the two buttons record a
 *  name and change nothing else, and skipping them changes nothing at all. */

const WINDOWS: FallWindow[] = ['today', 'yesterday', 'last7', 'last30', 'last90', 'schoolYear', 'all'];

/** Somebody on the floor is the most time-critical thing this console shows,
 *  so the list is read often. One small indexed query. */
const NOW_REFRESH_MS = 2_000;
const LOG_REFRESH_MS = 3_000;
const CAMERA_REFRESH_MS = 15_000;
const STATUS_REFRESH_MS = 15_000;

const NO_CAMERAS: Camera[] = [];
const NO_LOG: { entries: FallEntry[]; readAt: number } = { entries: [], readAt: 0 };

/** "1:12", "12:05", "1:02:44". Latin digits, like every clock on the console. */
function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

/** A clock that moves between polls. One tick a second, only while mounted. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);
  return now;
}

export function Falls() {
  const { language } = useLanguage();
  const t = useT();
  const account = useAccount();
  const capability = useCapability('falls');
  // Read, never printed as a promise of our own: the engine deletes by its
  // own `clip_retention_days`.
  const retentionDays = useSite().site?.clipRetentionDays;
  const [params] = useSearchParams();
  const asked = params.get('window') as FallWindow | null;
  const [when, setWhen] = useState<FallWindow>(asked && WINDOWS.includes(asked) ? asked : 'last7');
  // An alert lands here on one entry: `?entry=` is the fall the engine named.
  const linked = useLinkedItem('entry');
  const now = useNow();

  const { data: cameras } = useAsync(
    () => getFallCameras(language), [language], NO_CAMERAS, CAMERA_REFRESH_MS);
  const { data: status } = useAsync<FallsStatus | null>(
    () => getFallsStatus(), [], null, STATUS_REFRESH_MS);
  // When the list was read travels with it: the live clocks count on from the
  // engine's own `seconds` at that moment, so a computer whose clock is wrong
  // still shows how long somebody has really been down.
  const { data: log, error, loading, reload } = useAsync(
    () => getFalls(when, language).then((entries) => ({ entries, readAt: Date.now() })),
    [when, language], NO_LOG, LOG_REFRESH_MS);
  const entries = log.entries;
  // Who is down NOW, read on its own and never from the history above: the
  // period picker is for reading back, and "Yesterday" must not hide - or
  // print the all-clear over - somebody on the floor at this moment.
  const { data: current, error: nowError, loading: nowLoading } = useAsync(
    () => getFallsNow(language).then((entries) => ({ entries, readAt: Date.now() })),
    [language], NO_LOG, NOW_REFRESH_MS);

  const [playing, setPlaying] = useState<FallEntry | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // Nothing here may say "nobody is on the ground" unless something is
  // actually looking. An empty list from a feature that is not running is not
  // an all-clear.
  const running = capability?.state === 'live';
  const notRunning = capability?.reason ?? t('falls.notRunning');
  const counted = !loading && !error;
  const downSeconds = status?.downSeconds ?? null;
  const checking = status?.camerasChecked ?? cameras.length;
  const stillListed = playing !== null && entries.some((e) => e.id === playing.id);
  // Somebody down now has a live card whatever the period, so a link to
  // them is never "not in this list".
  const linkedMissing = linked.id !== null && counted && !entries.some((e) => e.id === linked.id)
    && !current.entries.some((e) => e.id === linked.id);

  // The live cards: down long enough to count, still down, and nobody has
  // said it was not a fall. Longest down first.
  const down = current.entries
    .filter((e) => e.alerted && !e.notAFall)
    .sort((a, b) => b.seconds - a.seconds);
  // Seconds since each list was read, for the clocks that count on between
  // polls. One per list: they are read at different moments.
  const elapsed = Math.max(0, (now - log.readAt) / 1000);
  const elapsedNow = Math.max(0, (now - current.readAt) / 1000);

  async function act(entry: FallEntry, action: (id: string, lang: typeof language) => Promise<FallEntry>) {
    setActionError(null);
    setBusy(entry.id);
    try {
      await action(entry.id, language);
      // Re-read rather than patch: who, and when, come from the engine.
      reload();
    } catch (err) {
      setActionError(t('falls.actionNotSaved', {
        reason: err instanceof Error ? err.message : t('common.engineRefused'),
      }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('falls.title')} lead={t('falls.lead')} />
      <LoadError error={actionError} what="load.change" />

      {down.map((entry) => {
        const camera = cameras.find((c) => c.id === entry.cameraId);
        const downFor = entry.seconds + elapsedNow;
        const agoSeconds = entry.respondedAtMs !== undefined
          // The engine's moment of pressing, against the engine's own clock
          // as the list carried it - never this computer's clock.
          ? Math.max(0, downFor - (entry.respondedAtMs - entry.downSinceMs) / 1000)
          : 0;
        const mine = entry.responder === account.name;
        return (
          <div
            key={entry.id}
            ref={entry.id === linked.id ? linked.ref : undefined}
            className="card"
            style={{
              padding: 0,
              overflow: 'hidden',
              border: `1.5px solid ${toneColors.bad.fg}`,
              marginBottom: 14,
              ...(entry.id === linked.id ? LINKED_STYLE : null),
            }}
          >
            <div
              role="alert"
              style={{
                background: toneColors.bad.bg,
                color: toneColors.bad.fg,
                padding: '10px 20px',
                display: 'flex',
                alignItems: 'center',
                gap: 9,
                fontSize: 13.5,
                fontWeight: 700,
              }}
            >
              <span className="glyph" style={{ width: 16, height: 16, fontSize: 10.5, background: toneColors.bad.fg, color: toneColors.bad.bg }}>!</span>
              {t('falls.downBanner')}
            </div>
            <div
              style={{
                display: 'grid',
                // `min(100%, …)` so a narrow window stacks the two halves
                // instead of letting the picture push the clock off the card.
                gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 300px), 1fr))',
                gap: 22,
                padding: 20,
              }}
            >
              <div style={{ minWidth: 0 }}>
                {camera ? (
                  // The stream with this feature's own overlay: a box round the
                  // person down, never a name (rule 1). `sm` scale, because `lg`
                  // has a 380 px floor that would push the clock off the card;
                  // the picture still fills its half at the camera's own shape.
                  <CameraFrame camera={camera} live feature="falls" badge="LIVE" />
                ) : (
                  <Empty>{entry.camera}</Empty>
                )}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
                    {t('falls.cameraLine', { area: entry.area, camera: entry.camera })}
                  </div>
                  <div
                    style={{
                      fontSize: 44,
                      fontWeight: 700,
                      letterSpacing: '-.02em',
                      lineHeight: 1.05,
                      marginTop: 4,
                      fontVariantNumeric: 'tabular-nums',
                      color: toneColors.bad.fg,
                    }}
                    dir="ltr"
                  >
                    {clock(downFor)}
                  </div>
                  <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
                    {t('falls.onGroundSince', { time: entry.sinceClock })}
                  </div>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)', fontSize: 13.5 }}>
                  <span style={{ color: 'var(--tx2)' }}>{t('falls.confidence')}</span>
                  <span style={{ fontWeight: 600 }}>{entry.confidence}</span>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{t('falls.nothingSent')}</div>
                <div style={{ borderTop: '1px solid var(--line)', paddingTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--tx3)', letterSpacing: '.03em', textTransform: 'uppercase' }}>
                    {t('falls.optional')}
                  </div>
                  {entry.responder ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 13.5 }}>
                      <Badge tone="good" glyph={toneGlyph.good}>
                        {t('falls.onTheWay', { name: entry.responder, ago: clock(agoSeconds) })}
                      </Badge>
                      {/* Only the person who pressed it is offered Undo here.
                          A hint, not the boundary: the engine records who
                          took a name off, whoever they are. */}
                      {mine && (
                        <button
                          type="button"
                          className="linkbtn"
                          disabled={busy === entry.id}
                          onClick={() => act(entry, undoFallResponse)}
                        >
                          {t('falls.undo')}
                        </button>
                      )}
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busy === entry.id}
                        onClick={() => act(entry, respondToFall)}
                      >
                        {t('falls.onMyWay')}
                      </button>
                      <button
                        type="button"
                        className="btn btn--ghost"
                        disabled={busy === entry.id}
                        onClick={() => act(entry, markNotAFall)}
                      >
                        {t('falls.notAFall')}
                      </button>
                    </div>
                  )}
                  <div style={{ fontSize: 12, color: 'var(--tx3)' }}>{t('falls.pressNote')}</div>
                </div>
              </div>
            </div>
          </div>
        );
      })}

      {/* Only ever said when something is actually watching. */}
      <LoadError error={nowError} what="load.detectionLog" />
      {running && !nowLoading && !nowError && current.readAt > 0 && down.length === 0 && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="glyph" style={{ width: 22, height: 22, fontSize: 12, background: 'var(--ac)', color: 'var(--on-ac)', flexShrink: 0 }}>✓</span>
            <div>
              <div style={{ fontWeight: 600, fontSize: 15 }}>{t('falls.calmTitle')}</div>
              {downSeconds !== null && (
                <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                  {t(checking === 1 ? 'falls.calmSubOne' : 'falls.calmSub', {
                    count: checking,
                    seconds: Math.round(downSeconds),
                  })}
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

      <Card>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
          <div style={{ flex: '1 1 320px', minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              {counted
                ? t(entries.length === 1 ? 'falls.entryCountOne' : 'falls.entryCount', {
                  count: entries.length,
                  window: t(`window.${when}` as MessageKey),
                })
                : t('falls.entriesHeading', { window: t(`window.${when}` as MessageKey) })}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2, maxWidth: 520 }}>
              {running
                ? (downSeconds !== null
                  ? t('falls.shortNote', { seconds: Math.round(downSeconds) })
                  : null)
                : notRunning}
            </div>
          </div>
          <Field label={t('falls.period')}>
            <Select
              value={when}
              onChange={(v) => setWhen(v as FallWindow)}
              options={WINDOWS}
              label={(o) => t(`window.${o}` as MessageKey)}
            />
          </Field>
        </div>

        <LoadError error={error} onRetry={reload} what="load.detectionLog" />
        {loading && <Empty>{t('falls.loading')}</Empty>}
        {linkedMissing && (
          <div className="linked-missing" role="status">
            {t('falls.linkedNotListed', { window: t(`window.${when}` as MessageKey) })}
          </div>
        )}
        {/* Two empty states, because they are two different claims: nobody
            fell, or nothing was looking. */}
        {counted && entries.length === 0 && running && (
          <Empty>{t('falls.nothingSeen', { window: t(`window.${when}` as MessageKey) })}</Empty>
        )}
        {counted && entries.length === 0 && !running && <Empty>{notRunning}</Empty>}

        {entries.length > 0 && (
          <div
            className="row"
            style={{
              gridTemplateColumns: '1fr .8fr .9fr .6fr 1.4fr 1.2fr',
              color: 'var(--tx3)',
              fontSize: 12,
              fontWeight: 600,
              letterSpacing: '.03em',
              textTransform: 'uppercase',
            }}
          >
            <span>{t('falls.col.camera')}</span>
            <span>{t('falls.col.area')}</span>
            <span>{t('falls.col.when')}</span>
            <span>{t('falls.col.downFor')}</span>
            <span>{t('falls.col.saw')}</span>
            <span />
          </div>
        )}

        {entries.map((entry) => (
          <div
            key={entry.id}
            ref={entry.id === linked.id && !down.some((d) => d.id === entry.id) ? linked.ref : undefined}
            aria-current={entry.id === linked.id || undefined}
            className="row"
            style={{
              gridTemplateColumns: '1fr .8fr .9fr .6fr 1.4fr 1.2fr',
              ...(entry.id === linked.id ? LINKED_STYLE : null),
            }}
          >
            <span className="row__name">{entry.camera}</span>
            <span className="row__muted">{entry.area}</span>
            <span className="row__muted">{entry.time}</span>
            <span className="row__muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
              {entry.running ? clock(entry.seconds + elapsed) : clock(entry.seconds)}
            </span>
            <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
              <Badge tone={entry.tone} glyph={toneGlyph[entry.tone]}>{entry.outcome}</Badge>
              {entry.by && <span style={{ fontSize: 12, color: 'var(--tx3)' }}>{entry.by}</span>}
            </span>
            <span>
              {/* No dead buttons: a video plays, or a sentence says why not. */}
              {entry.clipUrl ? (
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => setPlaying((current) => (current?.id === entry.id ? null : entry))}
                >
                  {t(playing?.id === entry.id ? 'falls.hide' : 'falls.watch')}
                </button>
              ) : (
                <span style={{ fontSize: 12, color: 'var(--tx2)' }}>
                  {entry.clipReason ?? t('falls.noVideo')}
                </span>
              )}
            </span>
          </div>
        ))}

        {playing?.clipUrl && (
          <div style={{ marginTop: 12 }}>
            <video
              key={playing.id}
              src={playing.clipUrl}
              controls
              autoPlay
              style={{ width: '100%', maxHeight: 420, borderRadius: 8 }}
            />
            {!stillListed && (
              <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 6 }}>
                {t('falls.entryNoLongerListed', { window: t(`window.${when}` as MessageKey) })}
              </div>
            )}
          </div>
        )}

        <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 12 }}>
          {retentionDays
            ? `${t(retentionDays === 1 ? 'falls.keptForOneDay' : 'falls.keptForDays', { days: retentionDays })} `
            : `${t('falls.keptUnknown')} `}
          {t('falls.neverRemoved')}
        </div>
      </Card>

      {/* A box round somebody down is the overlay worth seeing without
          clicking first, the reason the knife grid draws its own. */}
      <CamGrid
        title={t('falls.gridTitle')}
        note={t('falls.gridNote')}
        cameras={cameras}
        only
        feature="falls"
        tileOverlay
      />
      <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 8 }}>
        <Link to="/system#fall-checking" style={{ fontWeight: 600 }}>{t('falls.gridSettings')}</Link>
      </div>
    </>
  );
}
