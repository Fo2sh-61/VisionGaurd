import { useEffect, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, DataNotice, Field, PageHeader, Select } from '@/components/ui';
import { getWeaponCameras, getWeaponDetections } from '@/services/api';
import { WEAPON_STEPS } from '@/services/content';
import { useSite } from '@/app/SiteContext';
import type { Camera, WeaponDetection, WeaponState, WeaponWindow } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

const WINDOWS: WeaponWindow[] = ['Last 30 days', 'Last 90 days', 'This school year'];

export function Weapons() {
  const capability = useCapability('weapons');
  const [when, setWhen] = useState<WeaponWindow>('Last 90 days');
  const [detections, setDetections] = useState<WeaponDetection[]>([]);
  const [state, setState] = useState<WeaponState>('clear');
  const [cameras, setCameras] = useState<Camera[]>([]);
  const cameraTotal = useSite().site?.camerasTotal ?? 0;

  useEffect(() => {
    void getWeaponCameras().then(setCameras);
  }, []);

  useEffect(() => {
    void getWeaponDetections(when).then(setDetections);
  }, [when]);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Knife detection"
        lead={`Looks for knife-shaped objects on all ${cameraTotal} cameras. Every detection is reviewed by a person before anything happens.`}
      />

      {state === 'clear' && (
        <Card tight className="weapons-status">
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: '50%',
                background: 'var(--chip)',
                color: 'var(--ac)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 19,
                flexShrink: 0,
              }}
            >
              ✓
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 15.5 }}>No knife detected on campus</div>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
                Monitoring all {cameraTotal} cameras · last check 2 seconds ago
              </div>
            </div>
            <button
              type="button"
              className="linkbtn linkbtn--quiet"
              style={{ whiteSpace: 'nowrap' }}
              onClick={() => setState('live')}
            >
              Show a live detection →
            </button>
          </div>
        </Card>
      )}

      {state === 'live' && (
        <div
          className="card"
          style={{ border: '2px solid var(--rd)', padding: 24 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
            <span
              aria-hidden="true"
              style={{
                width: 26,
                height: 26,
                borderRadius: '50%',
                background: 'var(--rd)',
                color: 'var(--card)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 15,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              !
            </span>
            <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em', color: 'var(--rd)' }}>
              Possible knife — Main gate
            </div>
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginBottom: 18 }}>
            Detected 14 seconds ago · knife-shaped object, 78% confidence · nobody has been alerted
            yet.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 1fr', gap: 18, alignItems: 'start' }}>
            <CamGrid title="" cameras={cameras.slice(0, 1)} only />
            <div>
              <div style={{ fontWeight: 700, fontSize: 14.5, marginBottom: 8 }}>
                Before anything happens, a person decides
              </div>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', lineHeight: 1.5, marginBottom: 16 }}>
                The system will not call anyone, lock anything, or notify a parent on its own. Watch
                the clip and say what you see.
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                <button
                  type="button"
                  className="btn"
                  style={{ background: 'var(--rd)', width: '100%' }}
                  onClick={() => setState('confirmed')}
                >
                  This is a knife — alert the team
                </button>
                <button
                  type="button"
                  className="btn btn--ghost"
                  style={{ width: '100%' }}
                  onClick={() => setState('dismissed')}
                >
                  Not a knife — false alarm
                </button>
                <button
                  type="button"
                  className="linkbtn linkbtn--quiet"
                  style={{ height: 40, width: '100%' }}
                  onClick={() => setState('dismissed')}
                >
                  Not sure yet — keep watching
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {state === 'confirmed' && (
        <Card>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span
              aria-hidden="true"
              style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                background: 'var(--rd)',
                color: 'var(--card)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              !
            </span>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              Confirmed by you at 8:47am — team alerted
            </div>
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginBottom: 16 }}>
            Mohamed Fouad confirmed this detection. Everything below is now recorded against the
            incident.
          </div>

          {WEAPON_STEPS.map((step) => (
            <div
              key={step.title}
              style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '11px 0', borderBottom: '1px solid var(--line)' }}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: '50%',
                  background:
                    step.tone === 'bad' ? 'var(--rd)' : step.tone === 'warn' ? 'var(--am)' : 'var(--bg)',
                  color: step.tone === 'neutral' ? 'var(--tx2)' : 'var(--card)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 11,
                  fontWeight: 800,
                  flexShrink: 0,
                }}
              >
                {step.icon}
              </span>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{step.title}</div>
                <div style={{ fontSize: 12.5, color: 'var(--tx3)' }}>{step.sub}</div>
              </div>
            </div>
          ))}

          <div style={{ display: 'flex', gap: 9, marginTop: 16, flexWrap: 'wrap' }}>
            <button type="button" className="btn">
              Save clip to the incident
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setState('clear')}>
              Close incident
            </button>
          </div>
        </Card>
      )}

      {state === 'dismissed' && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div
              style={{
                width: 40,
                height: 40,
                borderRadius: '50%',
                background: 'var(--chip)',
                color: 'var(--ac)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 17,
                flexShrink: 0,
              }}
            >
              ✓
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 15 }}>Marked as a false alarm — nobody was alerted</div>
              <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                Recorded against your name at 8:47am, and added to the list below so the count stays
                honest.
              </div>
            </div>
            <button
              type="button"
              className="linkbtn"
              style={{ whiteSpace: 'nowrap' }}
              onClick={() => setState('clear')}
            >
              Done
            </button>
          </div>
        </Card>
      )}

      <Card>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
            marginBottom: 6,
          }}
        >
          <div>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              {detections.length} {detections.length === 1 ? 'detection' : 'detections'} ·{' '}
              {when.toLowerCase()}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              False alarms are shown honestly — most detections turn out to be harmless.
            </div>
          </div>
          <Field label="Period">
            <Select value={when} onChange={(v) => setWhen(v as WeaponWindow)} options={WINDOWS} />
          </Field>
        </div>

        {detections.map((d) => (
          <div key={d.id} className="row" style={{ gridTemplateColumns: '1.1fr 1.1fr 1fr 1.4fr .7fr' }}>
            <span className="row__muted">{d.time}</span>
            <span className="row__name">{d.location}</span>
            <span>{d.item}</span>
            <span>
              <Badge tone={d.tone}>{d.status}</Badge>
            </span>
            <button type="button" className="linkbtn">
              Watch clip
            </button>
          </div>
        ))}
      </Card>

      <CamGrid
        title="Highest-risk cameras"
        note="Knife detection runs everywhere; entry points are shown first. Green = scanned, nothing found."
        cameras={cameras}
      />
    </>
  );
}
