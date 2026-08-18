import { useEffect, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, Field, PageHeader, Select } from '@/components/ui';
import { getFightCameras, getFights, markNotAFight } from '@/services/api';
import type { Camera, FightIncident, FightPlace, IntrusionWindow, Tone } from '@/types';

const WINDOWS: IntrusionWindow[] = ['Today', 'Last 7 days', 'Last 30 days'];
const PLACES: FightPlace[] = ['Anywhere', 'Corridors', 'Outdoor areas'];

function toneFor(incident: FightIncident): Tone {
  if (incident.critical) return 'bad';
  if (incident.status.startsWith('Marked')) return 'neutral';
  return 'good';
}

export function Fights() {
  const [when, setWhen] = useState<IntrusionWindow>('Last 7 days');
  const [place, setPlace] = useState<FightPlace>('Anywhere');
  const [incidents, setIncidents] = useState<FightIncident[]>([]);
  const [dismissed, setDismissed] = useState<Record<string, true>>({});
  const [cameras, setCameras] = useState<Camera[]>([]);

  useEffect(() => {
    void getFightCameras().then(setCameras);
  }, []);

  useEffect(() => {
    void getFights(when, place).then(setIncidents);
  }, [when, place]);

  function notAFight(id: string) {
    setDismissed((current) => ({ ...current, [id]: true }));
    void markNotAFight(id);
  }

  const sub = `${when} · ${place.toLowerCase()}`;

  return (
    <>
      <PageHeader
        title="Fights"
        lead="Altercations confirmed over 3 or more seconds, always with the video. If it wasn’t a fight, say so — that teaches the system."
      />

      <Card tight>
        <div className="filters">
          <Field label="Period">
            <Select value={when} onChange={(v) => setWhen(v as IntrusionWindow)} options={WINDOWS} />
          </Field>
          <Field label="Place">
            <Select value={place} onChange={(v) => setPlace(v as FightPlace)} options={PLACES} />
          </Field>
        </div>
      </Card>

      {incidents.length === 0 ? (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 21 }}>No fights detected</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>{sub}</div>
        </Card>
      ) : (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>
            {incidents.length} {incidents.length === 1 ? 'incident' : 'incidents'}
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 16px' }}>{sub}</div>

          <div className="grid-2">
            {incidents.map((incident) => (
              <div
                key={incident.id}
                style={{ background: 'var(--bg)', borderRadius: 12, padding: 16 }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 8,
                    marginBottom: 6,
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 14.5 }}>{incident.location}</div>
                  <Badge tone={toneFor(incident)}>{incident.status}</Badge>
                </div>
                <div style={{ fontSize: 13, color: 'var(--tx2)' }}>{incident.time}</div>
                <div style={{ fontSize: 13, color: 'var(--tx2)' }}>{incident.meta}</div>

                <div style={{ marginTop: 12, display: 'flex', gap: 16, alignItems: 'center' }}>
                  <button type="button" className="linkbtn">
                    Watch clip
                  </button>
                  {dismissed[incident.id] ? (
                    <span style={{ color: 'var(--ac2)', fontSize: 13, fontWeight: 600 }}>
                      ✓ Noted — thanks, this improves detection
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="linkbtn linkbtn--muted"
                      onClick={() => notAFight(incident.id)}
                    >
                      Not a fight
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <CamGrid
        title="Cameras where fight detection is on"
        note="Red boxes mark the detected altercation. Detection is off in sports halls and PE areas, where rough movement is normal."
        cameras={cameras}
      />
    </>
  );
}
