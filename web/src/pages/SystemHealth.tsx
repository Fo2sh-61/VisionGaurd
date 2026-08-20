import { CameraSources } from '@/components/CameraSources';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, Empty, LoadError, PageHeader, Stats, toneGlyph } from '@/components/ui';
import { getSystemHealth } from '@/services/api';
import type { SystemHealth as SystemHealthData } from '@/types';
import { useAsync } from '@/app/useAsync';

export function SystemHealth() {
  const { data: health, error, loading, reload } = useAsync<SystemHealthData | null>(
    () => getSystemHealth(),
    [],
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
        <PageHeader title="System health" lead="Cameras, recorders and the AI server." />
        <LoadError error={error} onRetry={reload} what="system health" />
        <Card>
          {loading ? (
            <Empty>Checking the system…</Empty>
          ) : (
            <Empty>
              The engine did not answer, so nothing here can be reported. That is itself a
              fault worth acting on — the engine may be stopped or unreachable.
            </Empty>
          )}
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHeader title="System health" lead="Cameras, recorders and the AI server." />
      <LoadError error={error} onRetry={reload} what="the latest system health" />

      <Card>
        <CardHeader
          title={`${health.camerasOnline} of ${health.camerasTotal} cameras online`}
          sub={health.summary}
        />
        <Stats items={health.stats} columns={4} />

        <div className="section-title">AI pipeline</div>
        {health.pipeline.length === 0 && (
          <Empty>No pipeline stages are running.</Empty>
        )}
        {health.pipeline.map((p) => (
          <div key={p.name} className="row" style={{ gridTemplateColumns: '1.2fr 1.6fr 1fr .8fr' }}>
            <span className="row__name">{p.name}</span>
            <span className="row__muted">{p.detail}</span>
            <span>
              {/* The engine rates every stage. Hardcoding `tone="good"` here
                  drew "Needs attention" inside a healthy green badge. */}
              <Badge tone={p.tone} glyph={toneGlyph[p.tone]}>{p.status}</Badge>
            </span>
            {p.action ? (
              <button type="button" className="linkbtn">
                {p.action}
              </button>
            ) : (
              <span />
            )}
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
        title="Cameras needing attention"
        note="Offline cameras show their last received frame, clearly marked — never a frozen image pretending to be live."
        cameras={health.cameras}
      />
    </>
  );
}
