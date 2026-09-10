import { CameraSources } from '@/components/CameraSources';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, Empty, LoadError, PageHeader, Stats, toneGlyph } from '@/components/ui';
import { getSystemHealth } from '@/services/api';
import { formatWorkerQueue, formatWorkerThroughput } from '@/services/format';
import type { SystemHealth as SystemHealthData } from '@/types';
import { useAsync } from '@/app/useAsync';
import { useLanguage, useT } from '@/app/LanguageContext';

export function SystemHealth() {
  const { language } = useLanguage();
  const t = useT();
  const { data: health, error, loading, reload } = useAsync<SystemHealthData | null>(
    () => getSystemHealth(language),
    [language],
    null,
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

      <Card>
        <CardHeader
          title={t('health.camerasOnline', {
            online: health.camerasOnline, total: health.camerasTotal,
          })}
          sub={health.summary}
        />
        <Stats items={health.stats} columns={4} />

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
      />
    </>
  );
}
