import { useEffect, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, Field, PageHeader, Select, Toggle, toneGlyph } from '@/components/ui';
import { getBreaches, getIntrusionCameras, getZones, setZoneEnabled } from '@/services/api';
import type { Breach, Camera, IntrusionWindow, Zone } from '@/types';

const WINDOWS: IntrusionWindow[] = ['Today', 'Last 7 days', 'Last 30 days'];

export function Intrusion() {
  const [zones, setZones] = useState<Zone[]>([]);
  const [when, setWhen] = useState<IntrusionWindow>('Today');
  const [breaches, setBreaches] = useState<Breach[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);

  useEffect(() => {
    void getZones().then(setZones);
    void getIntrusionCameras().then(setCameras);
  }, []);

  useEffect(() => {
    void getBreaches(when).then(setBreaches);
  }, [when]);

  function toggleZone(zone: Zone) {
    const next = !zone.enabled;
    setZones((current) => current.map((z) => (z.id === zone.id ? { ...z, enabled: next } : z)));
    void setZoneEnabled(zone.id, next);
  }

  const open = breaches.filter((b) => b.status === 'Open').length;

  return (
    <>
      <PageHeader
        title="Restricted zones"
        lead="Restricted areas that alert when someone enters outside allowed hours."
      />

      <Card tight>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Protected areas</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          Switch an area off during maintenance, then back on. Pauses are visible to everyone.
        </div>
        {zones.map((zone) => (
          <div
            key={zone.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              padding: '13px 0',
              borderBottom: '1px solid var(--line)',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{zone.name}</div>
              <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{zone.hours}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Badge tone={zone.enabled ? 'good' : 'warn'} glyph={zone.enabled ? '✓' : '⏸'}>
                {zone.enabled ? 'Protected' : 'Paused'}
              </Badge>
              <Toggle
                on={zone.enabled}
                onToggle={() => toggleZone(zone)}
                label={`Protection for ${zone.name}`}
              />
            </div>
          </div>
        ))}
      </Card>

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
              {breaches.length} {breaches.length === 1 ? 'breach' : 'breaches'} ·{' '}
              {when.toLowerCase()}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {open} still needs review
            </div>
          </div>
          <Field label="Period">
            <Select
              value={when}
              onChange={(v) => setWhen(v as IntrusionWindow)}
              options={WINDOWS}
            />
          </Field>
        </div>

        {breaches.map((breach) => (
          <div
            key={breach.id}
            className="row"
            style={{ gridTemplateColumns: '1.2fr 1fr 1.2fr 1fr .7fr' }}
          >
            <span className="row__name">{breach.zone}</span>
            <span className="row__muted">{breach.time}</span>
            <span className="row__muted">{breach.who}</span>
            <span>
              <Badge tone={breach.tone} glyph={toneGlyph[breach.tone]}>
                {breach.status}
              </Badge>
            </span>
            <button type="button" className="linkbtn">
              Watch clip
            </button>
          </div>
        ))}
      </Card>

      <CamGrid
        title="Cameras watching restricted areas"
        note="The orange outline is the protected zone drawn on that camera. A paused zone stays visible so nothing is hidden."
        cameras={cameras}
      />
    </>
  );
}
