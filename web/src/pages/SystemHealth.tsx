import { useEffect, useState } from 'react';
import { CameraSources } from '@/components/CameraSources';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, PageHeader, Stats } from '@/components/ui';
import { getSystemHealth } from '@/services/api';
import type { SystemHealth as SystemHealthData } from '@/types';

export function SystemHealth() {
  const [health, setHealth] = useState<SystemHealthData | null>(null);

  useEffect(() => {
    void getSystemHealth().then(setHealth);
  }, []);

  if (!health) return <PageHeader title="System health" lead="Loading…" />;

  return (
    <>
      <PageHeader title="System health" lead="Cameras, recorders and the AI server." />

      <Card>
        <CardHeader
          title={`${health.camerasOnline} of ${health.camerasTotal} cameras online`}
          sub={health.summary}
        />
        <Stats items={health.stats} columns={4} />

        <div className="section-title">AI pipeline</div>
        {health.pipeline.map((p) => (
          <div key={p.name} className="row" style={{ gridTemplateColumns: '1.2fr 1.6fr 1fr .8fr' }}>
            <span className="row__name">{p.name}</span>
            <span className="row__muted">{p.detail}</span>
            <span>
              <Badge tone="good">{p.status}</Badge>
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
