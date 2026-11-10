import { CameraSources } from '@/components/CameraSources';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, Empty, LoadError, PageHeader, Stats, toneGlyph } from '@/components/ui';
import { getSystemHealth } from '@/services/api';
import {
  capacityShare, capacityTone, formatCapacityAsks, formatCapacityRow, formatCount,
  formatEngineBusy, formatWorkerQueue, formatWorkerThroughput,
} from '@/services/format';
import type { MessageKey } from '@/i18n/keys';
import type { SystemHealth as SystemHealthData } from '@/types';
import { useCameras } from '@/app/CameraContext';
import { useAsync } from '@/app/useAsync';
import { useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';

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
  // is RIGHT NOW, and until 3 Sep 2026 it loaded once and sat there - a
  // reading with no refresh is a snapshot pretending to be a gauge.
  const { data: health, error, loading, reload } = useAsync<SystemHealthData | null>(
    () => getSystemHealth(language),
    [language],
    null,
    3000,
  );

  // This page is the one an operator opens when something is wrong, so it is
  // the one page that must never fail quietly. It used to render
  // `lead="Loading…"` whenever health was null — and a failed request leaves
  // it null forever, so the page that exists to report faults sat there
  // claiming to be loading, indefinitely, with no error and no retry.
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

        {/* One reading for the whole machine. With no graphics reading the
            board has one pool that the processor and the graphics share, and
            the label says so rather than implying a card of its own. */}
        {health.memoryUsedMb != null && health.memoryTotalMb != null && (
          <div className="row__muted" style={{ marginTop: 12 }}>
            <span style={{ fontWeight: 600 }}>
              {t(health.hasGpuReading ? 'health.memory' : 'health.memoryShared')}
            </span>
            {' · '}
            {t('health.memoryValue', {
              used: formatCount(health.memoryUsedMb, language),
              total: formatCount(health.memoryTotalMb, language),
            })}
          </div>
        )}

        <div className="section-title">{t('health.pipeline')}</div>
        {health.pipeline.length === 0 && (
          <Empty>{t('health.noStages')}</Empty>
        )}
        {health.pipeline.map((p) => (
          <div key={p.name} className="row" style={{ gridTemplateColumns: '1.2fr 1.6fr 1fr' }}>
            <span className="row__name">{p.name}</span>
            <span className="row__muted">{p.detail}</span>
            <span>
              {/* The engine rates every stage. Hardcoding `tone="good"` here
                  drew "Needs attention" inside a healthy green badge. */}
              <Badge tone={p.tone} glyph={toneGlyph[p.tone]}>{p.status}</Badge>
            </span>
            {/* No Restart here: no endpoint restarts anything, and the
                button this row used to carry did nothing when pressed. */}
            {/* Per-worker load, on the one row that carries it.
                Every figure is a counter the engine already kept and never
                showed, which is why a saturated machine used to look
                identical to a comfortable one. `behind` is the engine's
                call - full queue AND dropping - not a threshold invented
                here. */}
            {p.workers?.length ? (
              <div className="row__sub" style={{ gridColumn: '1 / -1' }}>
                {p.workers.map((w) => (
                  <div
                    key={w.name}
                    className="row"
                    style={{ gridTemplateColumns: '1fr 1fr 1fr 1fr' }}
                  >
                    <span className="row__muted">{w.name}</span>
                    <span className="row__muted">
                      {formatWorkerThroughput(w, language)}
                    </span>
                    <span className="row__muted">
                      {formatWorkerQueue(w, language)}
                    </span>
                    <span>
                      {w.behind ? (
                        <Badge tone="warn" glyph={toneGlyph.warn}>
                          {t('health.behind')}
                        </Badge>
                      ) : (
                        <span className="row__muted">
                          {t('health.keepingUp')}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </Card>

      {/* How full the machine is.
          The bars are READINGS: the driver's own utilisation figure for the
          graphics card and the OS's for the processor, whole device, every
          program, refreshed every three seconds. Under each bar: how much of
          that is this engine, measured over the last few seconds; and, kept
          apart and labelled, what the configuration asks for - the
          projection that lets somebody see the wall before adding the
          camera that hits it.

          The first version drew the projection AS the bar, and it read
          100% over a card the driver had at 18%. A bar is a claim about
          now; only a measurement gets to make it.

          The second version stopped drawing it as the bar but kept a
          percentage under it, worked out from the workers' own wall clock
          as though 1,000 ms a second were the whole card. Wall clock
          inside analyse() counts preparing the frame and reading the
          result back too, so that share ran ahead of the driver's figure
          directly above it. The graphics row now states milliseconds and
          leaves the share to the driver; see formatEngineBusy.

          Two bars, never one number. Face recognition is OpenCV with no
          CUDA path, so its milliseconds and the person detector's are not
          the same milliseconds. The whole card is absent when no worker is
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
          <div className="row__muted" style={{ marginTop: 4, fontSize: 12.5, lineHeight: 1.5 }}>
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
          <div className="row__muted" style={{ marginTop: 4, fontSize: 12.5, lineHeight: 1.5 }}>
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
          {health.capacity.rows.map((r) => (
            <div
              key={r.name}
              className="row"
              style={{ gridTemplateColumns: '1fr 1.7fr .8fr 1.4fr' }}
            >
              <span className="row__name">{r.name}</span>
              {/* The reading: what it did, over the window. */}
              <span className="row__muted">
                {r.onDemand && r.analysedPerSecond === 0
                  ? t('health.capacityOnDemand')
                  : formatCapacityRow(r, language)}
                {r.shared && ` · ${t('health.capacityShared')}`}
              </span>
              <span className="row__muted">
                {t('health.capacityBusyNow', { ms: Math.round(r.busyMsPerSecond) })}
              </span>
              {/* The projection, kept apart and badged for where its cost
                  came from. An em dash, never a zero, for a worker whose
                  rate nothing fixes. */}
              <span className="row__muted">
                {r.msPerSecond == null ? '—' : formatCapacityAsks(r, language)}
                {' '}
                <Badge tone={r.measured ? 'good' : 'neutral'}>
                  {t(r.measured ? 'health.capacityMeasured' : 'health.capacityEstimate')}
                </Badge>
              </span>
            </div>
          ))}

          {!health.capacity.allMeasured && (
            <div className="row__muted" style={{ marginTop: 10, lineHeight: 1.5 }}>
              {t('health.capacityEstimateNote')}
            </div>
          )}
          {health.capacity.unplacedMsPerSecond > 0 && (
            <div className="row__muted" style={{ marginTop: 6, lineHeight: 1.5 }}>
              {t('health.capacityUnplaced', {
                ms: Math.round(health.capacity.unplacedMsPerSecond),
              })}
            </div>
          )}
        </Card>
      )}

      <CameraSources />

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
  // badge anywhere else in the console.
  const colour =
    tone === 'bad' ? 'var(--rd)' : tone === 'warn' ? 'var(--am)' : 'var(--ac)';

  return (
    <div style={{ marginTop: 12 }}>
      <div
        style={{
          display: 'flex', justifyContent: 'space-between',
          alignItems: 'baseline', gap: 12, fontSize: 13,
        }}
      >
        <span style={{ fontWeight: 600 }}>{label}</span>
        <span style={{ color: 'var(--tx3)', fontSize: 12.5 }}>
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
