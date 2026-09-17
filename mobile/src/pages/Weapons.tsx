import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CamGrid } from '@/components/CamGrid';
import { Badge, DataNotice, Empty, Field, LoadError, PageHeader, Select, toneGlyph } from '@/components/ui';
import { getWeaponCameras, getWeaponDetections, reviewWeapon } from '@/services/api';
import type { Camera, WeaponDetection, WeaponWindow } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useSite } from '@/app/SiteContext';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/*  Knife detection, laid out for a phone (spec 015, P13-FR-052).
 *
 *  Built from `web/src/pages/Weapons.tsx`: the same calls, polls, windows,
 *  notices, empty states, linked entry and wording. What changed is the
 *  arrangement. Each entry is a card with its clip, its facts and - while it
 *  waits for a person - the reason field and the two decisions, all inside
 *  one 360-px screen, so a guard never scrolls past the video to decide.
 *
 *  Unchanged on purpose: every entry waits for a human, both decisions are
 *  open to any signed-in role (the engine decides), the verdict shown is the
 *  one the engine sends back, and there is no delete. */

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
  const [params] = useSearchParams();
  const asked = params.get('window') as WeaponWindow | null;
  const [when, setWhen] = useState<WeaponWindow>(
    asked && WINDOWS.includes(asked) ? asked : 'last30');
  // An alert lands here on one entry: `?entry=` is the scene the engine named.
  const linked = useLinkedItem('entry');

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
  const linkedMissing = linked.id !== null && counted
    && !detections.some((d) => d.id === linked.id);
  const windowName = t(`window.${when}` as MessageKey);

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
      <PageHeader title={t('weapons.title')} lead={t('weapons.lead')} />

      <section className="card stack" style={{ gap: 12 }}>
        <div>
          <div className="card__title" style={{ fontSize: 18 }}>
            {counted
              ? t(detections.length === 1 ? 'weapons.entryCountOne' : 'weapons.entryCount', {
                count: detections.length,
                window: windowName,
              })
              : t('weapons.entriesHeading', { window: windowName })}
          </div>
          {/* Never "No knife detected". What this line says is how many
              cameras are being checked — a fact — and when nothing is
              running it says that instead. */}
          <div className="li__sub" style={{ marginTop: 2 }}>
            {running
              ? t(cameras.length === 1 ? 'weapons.camerasCheckedOne' : 'weapons.camerasChecked',
                { count: cameras.length })
                + (inView > 0 ? ` · ${t('weapons.stillInView', { count: inView })}` : '')
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
        <p className="note">
          {retentionDays
            ? `${t(retentionDays === 1
              ? 'weapons.keptForOneDay' : 'weapons.keptForDays', { days: retentionDays })} `
            : `${t('weapons.keptUnknown')} `}
          {t('weapons.neverRemoved')}
        </p>
      </section>

      <LoadError error={error} onRetry={reload} what="load.detectionLog" />
      <LoadError error={reviewError} what="load.verdict" />
      {loading && <Empty>{t('weapons.loading')}</Empty>}
      {linkedMissing && (
        <div className="linked-missing" role="status">
          {t('weapons.linkedNotListed', { window: windowName })}
        </div>
      )}

      {/* Two different empty states, because they are two different claims.
          An empty list from a running detector means nothing was seen; an
          empty list from a detector that never started means nothing was
          looked for. */}
      {counted && detections.length === 0 && running && (
        <div className="card"><Empty>{t('weapons.nothingSeen', { window: windowName })}</Empty></div>
      )}
      {counted && detections.length === 0 && !running && (
        <div className="card"><Empty>{notRunning}</Empty></div>
      )}

      {/* Dropped out of the chosen period while it was being watched. The
          player stays, and says so, rather than silently disappearing. */}
      {playing?.clipUrl && !stillListed && (
        <div className="card stack" style={{ gap: 8 }}>
          <video key={playing.id} src={playing.clipUrl} controls autoPlay playsInline
                 style={{ width: '100%', borderRadius: 10, background: '#000' }} />
          <p className="note">{t('weapons.entryNoLongerListed', { window: windowName })}</p>
        </div>
      )}

      {detections.map((entry) => {
        const isPlaying = playing?.id === entry.id && !!entry.clipUrl;
        const busy = reviewing === entry.id;
        return (
          <article
            key={entry.id}
            ref={entry.id === linked.id ? linked.ref : undefined}
            aria-current={entry.id === linked.id || undefined}
            className="card card--flush"
            style={entry.id === linked.id ? LINKED_STYLE : undefined}
          >
            {isPlaying && (
              <video key={entry.id} src={entry.clipUrl} controls autoPlay playsInline
                     style={{ width: '100%', display: 'block', background: '#000' }} />
            )}

            <div className="stack" style={{ padding: 14, gap: 12 }}>
              <div className="spread" style={{ alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <div className="li__title">
                    {entry.camera}
                    {entry.area && <span className="muted" style={{ fontWeight: 500 }}> · {entry.area}</span>}
                  </div>
                  <div className="li__sub">
                    {[entry.time, entry.duration, entry.confidence].filter(Boolean).join(' · ')}
                  </div>
                  {entry.cut && <div className="li__sub">cut at two minutes</div>}
                </div>
                <Badge tone={entry.tone} glyph={toneGlyph[entry.tone]}>{entry.status}</Badge>
              </div>

              {/* No dead buttons. A video either plays or the control is gone
                  and a sentence says why. */}
              {entry.clipUrl ? (
                <div className="btnrow">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    aria-expanded={isPlaying}
                    onClick={() => setPlaying((current) => (current?.id === entry.id ? null : entry))}
                  >
                    {t(isPlaying ? 'weapons.hide' : 'weapons.watch')}
                  </button>
                  <a href={entry.clipUrl} target="_blank" rel="noopener" className="btn btn--ghost btn--sm">
                    {t('weapons.open')}
                  </a>
                </div>
              ) : (
                <p className="note">{entry.clipReason ?? t('weapons.noVideo')}</p>
              )}

              {entry.verdict === 'pending' && (
                <>
                  <label className="field">
                    <span className="field__label">{t('weapons.reasonOptional')}</span>
                    <input
                      className="input"
                      type="text"
                      value={reasons[entry.id] ?? ''}
                      onChange={(e) => setReasons((r) => ({ ...r, [entry.id]: e.target.value }))}
                    />
                  </label>
                  <div className="btnrow">
                    <button
                      type="button"
                      className="btn btn--ghost"
                      disabled={busy}
                      onClick={() => void decide(entry, 'dismissed')}
                    >
                      {t('weapons.falseAlarm')}
                    </button>
                    <button
                      type="button"
                      className="btn btn--danger"
                      disabled={busy}
                      onClick={() => void decide(entry, 'confirmed')}
                    >
                      {t('weapons.confirmKnife')}
                    </button>
                  </div>
                </>
              )}
            </div>
          </article>
        );
      })}

      {/* `tileOverlay` is the one place in the product a grid tile draws its
          own overlay. A knife is the overlay worth seeing without clicking
          first. Owner decision, 22 Aug 2026. */}
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
