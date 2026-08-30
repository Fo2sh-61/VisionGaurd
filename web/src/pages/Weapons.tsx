import { useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, toneGlyph } from '@/components/ui';
import { getWeaponCameras, getWeaponDetections, reviewWeapon } from '@/services/api';
import type { Camera, WeaponDetection, WeaponWindow } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useSite } from '@/app/SiteContext';
import { useAsync } from '@/app/useAsync';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

const WINDOWS: WeaponWindow[] = [
  'today',
  'yesterday',
  'last7',
  'last30',
  'last90',
  'schoolYear',
  'all',
];

/** A scene becomes watchable the moment the knife leaves view, which happens
 *  while somebody is looking at this page rather than because they did
 *  anything. Without a poll the only way to see a new video was to navigate
 *  away and come back. P6-FR-016. */
const LOG_REFRESH_MS = 3_000;

/** The camera list changes when somebody edits the roster, not on its own. */
const CAMERA_REFRESH_MS = 15_000;

const NO_DETECTIONS: WeaponDetection[] = [];
const NO_CAMERAS: Camera[] = [];

export function Weapons() {
  const { language } = useLanguage();
  const capability = useCapability('weapons');
  const t = useT();
  // Read, never printed. The engine deletes by its own configured
  // `clip_retention_days`; a number typed in here would be a promise the
  // engine is not required to keep.
  const retentionDays = useSite().site?.clipRetentionDays;
  const [when, setWhen] = useState<WeaponWindow>('last30');

  const { data: cameras } = useAsync(
    () => getWeaponCameras(language), [language], NO_CAMERAS, CAMERA_REFRESH_MS);
  const {
    data: detections, error, loading, reload,
  } = useAsync(() => getWeaponDetections(when, language),
    [when, language], NO_DETECTIONS, LOG_REFRESH_MS);

  // The whole entry, not just its id: the log refreshes underneath the player,
  // and looking the entry up each render would make the video vanish mid-watch
  // if the list moved.
  const [playing, setPlaying] = useState<WeaponDetection | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [reviewError, setReviewError] = useState<string | null>(null);

  // Nothing on this page may claim the school is clear unless the detector is
  // actually running. An empty list from a feature that never started is not
  // an all-clear, and on this feature above all others that difference is the
  // whole point.
  const running = capability?.state === 'live';
  const notRunning = capability?.reason ?? t('weapons.notRunning');
  const counted = !loading && !error;
  const stillListed = playing !== null && detections.some((d) => d.id === playing.id);
  const inView = detections.filter((d) => d.running).length;

  async function decide(entry: WeaponDetection, verdict: 'confirmed' | 'dismissed') {
    setReviewError(null);
    setReviewing(entry.id);
    try {
      await reviewWeapon(entry.id, verdict, language, reasons[entry.id]?.trim() || undefined);
      // Re-read rather than patching in place: the verdict, the reviewer and
      // the time all come from the engine, and inventing them here is how a
      // page ends up showing a save that did not happen.
      reload();
    } catch (err) {
      setReviewError(
        t('weapons.verdictNotSaved', {
          reason: err instanceof Error ? err.message : t('common.engineRefused'),
        }),
      );
    } finally {
      setReviewing(null);
    }
  }

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title={t('weapons.title')}
        lead={t('weapons.lead')}
      />

      <Card>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
            marginBottom: 14,
          }}
        >
          <div>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              {counted
                ? t(detections.length === 1 ? 'weapons.entryCountOne' : 'weapons.entryCount', {
                  count: detections.length,
                  window: t(`window.${when}` as MessageKey),
                })
                : t('weapons.entriesHeading', {
                  window: t(`window.${when}` as MessageKey),
                })}
            </div>
            {/* Never "No knife detected". What this line says is how many
                cameras are being checked — a fact — and when nothing is
                running it says that instead. */}
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {running
                ? t(cameras.length === 1
                  ? 'weapons.camerasCheckedOne' : 'weapons.camerasChecked',
                { count: cameras.length })
                  + (inView > 0
                    ? ` · ${t('weapons.stillInView', { count: inView })}` : '')
                : notRunning}
            </div>
          </div>
          <Field label={t('weapons.period')}>
            <Select
              value={when}
              onChange={(v) => setWhen(v as WeaponWindow)}
              options={WINDOWS}
              label={(o) => t(`window.${o}` as MessageKey)}
            />
          </Field>
        </div>

        <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 10 }}>
          {retentionDays
            ? `${t(retentionDays === 1
              ? 'weapons.keptForOneDay' : 'weapons.keptForDays', { days: retentionDays })} `
            : `${t('weapons.keptUnknown')} `}
          {t('weapons.neverRemoved')}
        </div>

        <LoadError error={error} onRetry={reload} what="load.detectionLog" />
        <LoadError error={reviewError} what="load.verdict" />
        {loading && <Empty>{t('weapons.loading')}</Empty>}

        {/* Two different empty states, because they are two different claims.
            An empty list from a running detector means nothing was seen; an
            empty list from a detector that never started means nothing was
            looked for, and reading the second as the first is exactly the
            failure this page exists to avoid. */}
        {counted && detections.length === 0 && running && (
          <Empty>{t('weapons.nothingSeen', { window: t(`window.${when}` as MessageKey) })}</Empty>
        )}
        {counted && detections.length === 0 && !running && <Empty>{notRunning}</Empty>}

        {detections.map((entry) => (
          <div
            key={entry.id}
            className="row"
            style={{ gridTemplateColumns: '1.1fr .9fr .9fr .8fr .6fr 1.2fr 1.4fr' }}
          >
            <span className="row__name">{entry.camera}</span>
            <span className="row__muted">{entry.area}</span>
            <span className="row__muted">{entry.time}</span>
            <span className="row__muted">
              {entry.duration}
              {entry.cut && (
                <span style={{ display: 'block', fontSize: 11.5 }}>cut at two minutes</span>
              )}
            </span>
            <span className="row__muted">{entry.confidence}</span>
            <span>
              <Badge tone={entry.tone} glyph={toneGlyph[entry.tone]}>
                {entry.status}
              </Badge>
            </span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              {/* No dead buttons. A video either plays or the control is gone
                  and a sentence says why. */}
              {entry.clipUrl ? (
                <>
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() =>
                      setPlaying((current) => (current?.id === entry.id ? null : entry))
                    }
                  >
                    {t(playing?.id === entry.id ? 'weapons.hide' : 'weapons.watch')}
                  </button>
                  <a href={entry.clipUrl} target="_blank" rel="noopener" className="linkbtn">
                    {t('weapons.open')}
                  </a>
                </>
              ) : (
                <span style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                  {entry.clipReason ?? t('weapons.noVideo')}
                </span>
              )}
            </span>

            {entry.verdict === 'pending' && (
              <span
                style={{
                  gridColumn: '1 / -1',
                  display: 'flex',
                  gap: 8,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  paddingTop: 8,
                }}
              >
                <button
                  type="button"
                  className="btn"
                  disabled={reviewing === entry.id}
                  onClick={() => decide(entry, 'confirmed')}
                >
                  {t('weapons.confirmKnife')}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={reviewing === entry.id}
                  onClick={() => decide(entry, 'dismissed')}
                >
                  {t('weapons.falseAlarm')}
                </button>
                <input
                  type="text"
                  placeholder={t('weapons.reasonOptional')}
                  value={reasons[entry.id] ?? ''}
                  onChange={(e) =>
                    setReasons((r) => ({ ...r, [entry.id]: e.target.value }))
                  }
                  style={{ flex: '1 1 220px', minWidth: 180 }}
                />
              </span>
            )}
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
            {/* Dropped out of the chosen period while it was being watched.
                Saying so beats the player silently disappearing. */}
            {!stillListed && (
              <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 6 }}>
                {t('weapons.entryNoLongerListed', { window: t(`window.${when}` as MessageKey) })}
              </div>
            )}
          </div>
        )}
      </Card>

      {/* `tileOverlay` is the one place in the product a grid tile draws its
          own overlay. A knife is the overlay worth seeing without clicking
          first: the question it answers is "is that a knife", and you should
          not have to open a camera to ask it. Owner decision, 22 Aug 2026. */}
      <CamGrid
        title={t('weapons.gridTitle')}
        note={t('weapons.gridNote')}
        cameras={cameras}
        feature="weapons"
        tileOverlay
      />
    </>
  );
}
