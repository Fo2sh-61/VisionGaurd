import { useState } from 'react';
import { CameraSources } from '@/components/CameraSources';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, Empty, LoadError, PageHeader, Stats, toneGlyph } from '@/components/ui';
import { getSystemHealth } from '@/services/api';
import {
  capacityShare, capacityTone, formatCapacityAsks, formatCapacityRow,
  formatEngineBusy, formatWorkerQueue, formatWorkerThroughput,
} from '@/services/format';
import type { MessageKey } from '@/i18n/keys';
import type { SystemHealth as SystemHealthData } from '@/types';
import { useCameras } from '@/app/CameraContext';
import { useAsync } from '@/app/useAsync';
import { useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';

/*  System health, laid out for a phone (spec 015, P13-FR-049).
 *
 *  Built from `web/src/pages/SystemHealth.tsx`: the same poll (every three
 *  seconds), the same checking / engine-silent / LoadError-over-stale states,
 *  the same linked-camera notice, and every figure the console shows -
 *  nothing invented, nothing dropped. Only the markup changed: the console's
 *  multi-column rows (pipeline stages, per-worker load, capacity rows) become
 *  stacked cards, and per-stage workers hide behind a Show/Hide button so a
 *  screen with a dozen stages does not open as a wall of numbers.
 *
 *  CameraSources - credentials, network scan, DVR pull - stays the console's
 *  own component untouched, inside `.legacy` so its wide rows and native
 *  inputs fold to the phone the way research R6 describes. */
export function SystemHealth() {
  const { language } = useLanguage();
  const t = useT();
  // A dark-camera alert lands here on that camera: `?camera=` is its id, and
  // its tile in the grid below is outlined and brought into view.
  const linked = useLinkedItem('camera');
  const { cameras: roster, loading: rosterLoading } = useCameras();
  const linkedMissing = linked.id !== null && !rosterLoading
    && !roster.some((c) => c.id === linked.id);
  // Every three seconds. This is the page that says how full the machine
  // is RIGHT NOW, and a reading with no refresh is a snapshot pretending to
  // be a gauge.
  const { data: health, error, loading, reload } = useAsync<SystemHealthData | null>(
    () => getSystemHealth(language),
    [language],
    null,
    3000,
  );

  // Which stages have their workers open. Collapsed by default: a stage's
  // name, detail and status are the fact a guard opens this page to check;
  // per-worker load is there for whoever needs it, one tap away.
  const [openStages, setOpenStages] = useState<Record<string, boolean>>({});

  // This page is the one an operator opens when something is wrong, so it is
  // the one page that must never fail quietly. A failed request leaves
  // `health` null forever, so the page that exists to report faults must not
  // sit there claiming to be loading, indefinitely, with no error and no
  // retry.
  if (!health) {
    return (
      <>
        <PageHeader title={t('health.title')} lead={t('health.lead')} />
        <LoadError error={error} onRetry={reload} what="load.systemHealth" />
        <Card>
          {loading ? (
            <Empty>{t('health.checking')}</Empty>
          ) : (
            <Empty>
              {t('health.engineSilent')}
            </Empty>
          )}
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t('health.title')} lead={t('health.lead')} />
      <LoadError error={error} onRetry={reload} what="load.latestSystemHealth" />
      {linkedMissing && (
        <div className="linked-missing" role="status">{t('health.linkedCameraMissing')}</div>
      )}

      <Card>
        <CardHeader
          title={t('health.camerasOnline', {
            online: health.camerasOnline, total: health.camerasTotal,
          })}
          sub={
            health.camerasDisabled > 0
              ? `${health.summary} ${t('health.camerasDisabled', { count: health.camerasDisabled })}`
              : health.summary
          }
        />
        <Stats items={health.stats} columns={4} />
      </Card>

      <div className="sechead" style={{ margin: '0 2px' }}>
        <span className="sechead__title">{t('health.pipeline')}</span>
      </div>
      {health.pipeline.length === 0 && (
        <Card><Empty>{t('health.noStages')}</Empty></Card>
      )}
      {health.pipeline.length > 0 && (
        <div className="list">
          {health.pipeline.map((p) => {
            const open = !!openStages[p.name];
            return (
              <div key={p.name} className="li stack" style={{ minHeight: 0, flexDirection: 'column', alignItems: 'stretch', padding: '12px 14px', gap: 8 }}>
                <div className="spread" style={{ alignItems: 'flex-start' }}>
                  <span className="li__title">{p.name}</span>
                  {/* The engine rates every stage. Hardcoding a tone here
                      drew "Needs attention" inside a healthy green badge. */}
                  <Badge tone={p.tone} glyph={toneGlyph[p.tone]}>{p.status}</Badge>
                </div>
                <span className="li__sub">{p.detail}</span>

                {/* Per-worker load, on the one row that carries it. Every
                    figure is a counter the engine already kept and never
                    showed, which is why a saturated machine used to look
                    identical to a comfortable one. `behind` is the engine's
                    call - full queue AND dropping - not a threshold invented
                    here. Collapsed by default so a dozen stages does not
                    open as a wall of numbers. */}
                {p.workers?.length ? (
                  <>
                    <button
                      type="button"
                      className="btn btn--ghost btn--sm btn--block"
                      aria-expanded={open}
                      onClick={() => setOpenStages((c) => ({ ...c, [p.name]: !open }))}
                    >
                      {open
                        ? t('phone.workers.hide')
                        : t('phone.workers.show', { count: p.workers.length })}
                    </button>
                    {open && (
                      <div className="stack" style={{ gap: 8 }}>
                        {p.workers.map((w) => (
                          <div
                            key={w.name}
                            className="stack"
                            style={{ gap: 2, padding: '8px 10px', background: 'var(--bg)', borderRadius: 10 }}
                          >
                            <div className="spread">
                              <span className="li__title" style={{ fontSize: 13.5 }}>{w.name}</span>
                              {w.behind ? (
                                <Badge tone="warn" glyph={toneGlyph.warn}>{t('health.behind')}</Badge>
                              ) : (
                                <span className="li__sub">{t('health.keepingUp')}</span>
                              )}
                            </div>
                            <span className="li__sub">
                              {formatWorkerThroughput(w, language)} · {formatWorkerQueue(w, language)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            );
          })}
        </div>
      )}

      {/* How full the machine is.
          The bars are READINGS: the driver's own utilisation figure for the
          graphics card and the OS's for the processor, whole device, every
          program, refreshed every three seconds. Under each bar: how much of
          that is this engine, measured over the last few seconds; and, kept
          apart and labelled, what the configuration asks for - the
          projection that lets somebody see the wall before adding the
          camera that hits it. A bar is a claim about now; only a
          measurement gets to make it - see `web/src/pages/SystemHealth.tsx`
          for the history of why. The whole card is absent when no worker is
          running - zeros would read as a machine with room to spare. */}
      {health.capacity && (
        <Card>
          <CardHeader
            title={t('health.capacity')}
            sub={t('health.capacityNote', {
              cores: health.capacity.cores,
              window: Math.round(health.capacity.windowSeconds),
            })}
          />

          <CapacityBar
            label={t('health.capacityGpu')}
            percent={health.capacity.gpuPercent}
            t={t}
          />
          <div className="li__sub" style={{ marginTop: 4 }}>
            {formatEngineBusy('gpu', health.capacity.gpuBusyMsPerSecond,
                              health.capacity.gpuBudgetMs, language)}
            {' · '}
            {t('health.capacityAsksTotal', {
              ms: Math.round(health.capacity.gpuMsPerSecond),
            })}
            {health.capacity.gpuMemoryUsedMb != null && health.capacity.gpuMemoryTotalMb != null && (
              <>
                {' · '}
                {t('health.capacityGpuMemory', {
                  used: Math.round(health.capacity.gpuMemoryUsedMb).toLocaleString(),
                  total: Math.round(health.capacity.gpuMemoryTotalMb).toLocaleString(),
                })}
              </>
            )}
          </div>

          <CapacityBar
            label={t('health.capacityCpu', { cores: health.capacity.cores })}
            percent={health.capacity.cpuMachinePercent}
            t={t}
          />
          <div className="li__sub" style={{ marginTop: 4 }}>
            {formatEngineBusy('cpu', health.capacity.cpuBusyMsPerSecond,
                              health.capacity.cpuBudgetMs, language)}
            {health.capacity.cpuEnginePercent != null && (
              <>
                {' · '}
                {t('health.capacityCpuEngine', {
                  percent: Math.round(health.capacity.cpuEnginePercent),
                })}
              </>
            )}
            {' · '}
            {t('health.capacityAsksTotal', {
              ms: Math.round(health.capacity.cpuMsPerSecond),
            })}
          </div>

          <div className="section-title" style={{ marginTop: 14 }}>
            {t('health.capacityRows')}
          </div>
          <div className="stack" style={{ gap: 0 }}>
            {health.capacity.rows.map((r) => (
              <div
                key={r.name}
                className="stack"
                style={{ gap: 3, padding: '10px 0', borderTop: '1px solid var(--line)' }}
              >
                <span className="li__title" style={{ fontSize: 14 }}>{r.name}</span>
                {/* The reading: what it did, over the window. */}
                <span className="li__sub">
                  {r.onDemand && r.analysedPerSecond === 0
                    ? t('health.capacityOnDemand')
                    : formatCapacityRow(r, language)}
                  {r.shared && ` · ${t('health.capacityShared')}`}
                </span>
                <span className="li__sub">
                  {t('health.capacityBusyNow', { ms: Math.round(r.busyMsPerSecond) })}
                </span>
                {/* The projection, kept apart and badged for where its cost
                    came from. An em dash, never a zero, for a worker whose
                    rate nothing fixes. */}
                <div className="hstack" style={{ gap: 6, flexWrap: 'wrap' }}>
                  <span className="li__sub">
                    {r.msPerSecond == null ? '—' : formatCapacityAsks(r, language)}
                  </span>
                  <Badge tone={r.measured ? 'good' : 'neutral'}>
                    {t(r.measured ? 'health.capacityMeasured' : 'health.capacityEstimate')}
                  </Badge>
                </div>
              </div>
            ))}
          </div>

          {!health.capacity.allMeasured && (
            <div className="li__sub" style={{ marginTop: 10 }}>
              {t('health.capacityEstimateNote')}
            </div>
          )}
          {health.capacity.unplacedMsPerSecond > 0 && (
            <div className="li__sub" style={{ marginTop: 6 }}>
              {t('health.capacityUnplaced', {
                ms: Math.round(health.capacity.unplacedMsPerSecond),
              })}
            </div>
          )}
        </Card>
      )}

      {/* CameraSources: the console's own component, unchanged - credentials,
          network scan, DVR pull, per-camera edit. Wrapped so its wide rows
          and native inputs fold to the phone (research R6, R1). */}
      <div className="legacy">
        <CameraSources />
      </div>

      <Card dashed>
        <div style={{ fontWeight: 600, fontSize: 14.5, color: 'var(--tx2)' }}>
          Live video streaming — not connected yet
        </div>
        <div style={{ fontSize: 13, color: 'var(--tx3)', marginTop: 2 }}>
          This prototype shows detection frames, not real streams. The RTSP gateway is planned for
          the next build; nothing here pretends otherwise.
        </div>
      </Card>

      <CamGrid
        title={t('health.camerasNeedingAttention')}
        note={t('health.camerasNeedingAttentionNote')}
        cameras={health.cameras}
        activeId={linked.id ?? undefined}
        activeRef={linked.ref}
        detections={false}
      />
    </>
  );
}


/** One reading, drawn as a bar.
 *
 *  `percent` is the driver's or the OS's own figure for the whole device.
 *  Absent means "could not be asked", and the bar says so rather than
 *  drawing an empty track that would read as idle. The bar is clamped at
 *  its own end; the number is not.
 */
function CapacityBar({
  label,
  percent,
  t,
}: {
  label: string;
  percent: number | undefined;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}) {
  const known = percent != null;
  const share = known ? capacityShare(percent, 100) : 0;
  const tone = known ? capacityTone(percent, 100) : 'good';
  // The page's own status colours, so a full bar reads the same as a red
  // badge anywhere else in the app.
  const colour =
    tone === 'bad' ? 'var(--rd)' : tone === 'warn' ? 'var(--am)' : 'var(--ac)';

  return (
    <div style={{ marginTop: 12 }}>
      <div className="spread" style={{ alignItems: 'baseline' }}>
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{label}</span>
        <span className="li__sub">
          {known
            ? t('health.capacityPercent', { percent: Math.round(percent) })
            : t('health.capacityUnreadable')}
        </span>
      </div>
      <div
        role="img"
        aria-label={`${label}: ${known ? `${share}%` : t('health.capacityUnreadable')}`}
        style={{
          height: 8, borderRadius: 999, marginTop: 6,
          background: 'var(--toggle-off)', overflow: 'hidden',
        }}
      >
        <div style={{ width: `${share}%`, height: '100%', background: colour }} />
      </div>
    </div>
  );
}
