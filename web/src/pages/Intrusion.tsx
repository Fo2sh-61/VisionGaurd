import { useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, Toggle, toneGlyph } from '@/components/ui';
import { getBreaches, getIntrusionCameras, getZones, setZoneEnabled } from '@/services/api';
import type { Breach, Camera, IntrusionWindow, Zone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const WINDOWS: IntrusionWindow[] = ['Today', 'Last 7 days', 'Last 30 days'];

const NO_ZONES: Zone[] = [];
const NO_BREACHES: Breach[] = [];
const NO_CAMERAS: Camera[] = [];

export function Intrusion() {
  const capability = useCapability('breaches');
  const [when, setWhen] = useState<IntrusionWindow>('Today');

  const {
    data: loadedZones, error: zonesError, loading: zonesLoading, reload: reloadZones,
  } = useAsync(() => getZones(), [], NO_ZONES);
  const {
    data: breaches, error: breachError, loading: breachLoading, reload: reloadBreaches,
  } = useAsync(() => getBreaches(when), [when], NO_BREACHES);
  const { data: cameras } = useAsync(() => getIntrusionCameras(), [], NO_CAMERAS);

  // Pending toggles, laid over what the engine last told us. A zone is only
  // drawn as paused once the engine has agreed it is paused.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [toggleError, setToggleError] = useState<string | null>(null);
  const zones = loadedZones.map((z) => (z.id in pending ? { ...z, enabled: pending[z.id] } : z));

  async function toggleZone(zone: Zone) {
    const next = !zone.enabled;
    setToggleError(null);
    // Optimistic, so the switch feels immediate...
    setPending((p) => ({ ...p, [zone.id]: next }));
    try {
      await setZoneEnabled(zone.id, next);
      // ...and confirmed from the engine, not assumed. This used to be a
      // fire-and-forget `void setZoneEnabled(...)`: a failed call left the
      // switch showing "Paused" while the zone was still armed, or worse,
      // "Protected" while it was not. A zone's state is a safety claim.
      reloadZones();
      setPending((p) => {
        const { [zone.id]: _dropped, ...rest } = p;
        return rest;
      });
    } catch (error) {
      setPending((p) => {
        const { [zone.id]: _dropped, ...rest } = p;
        return rest;
      });
      setToggleError(
        `${zone.name} was not changed: ${error instanceof Error ? error.message : 'the engine did not accept it'}`,
      );
    }
  }

  const counted = !breachLoading && !breachError;
  const open = breaches.filter((b) => b.status === 'Open').length;

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Restricted zones"
        lead="Restricted areas that alert when someone enters outside allowed hours."
      />

      <Card tight>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Protected areas</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          Switch an area off during maintenance, then back on. Pauses are visible to everyone.
        </div>
        <LoadError error={zonesError} onRetry={reloadZones} what="the zone list" />
        <LoadError error={toggleError} what="that change" />
        {zonesLoading && <Empty>Loading zones…</Empty>}
        {!zonesLoading && !zonesError && zones.length === 0 && (
          <Empty>No restricted zones have been set up yet.</Empty>
        )}
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
              {counted
                ? `${breaches.length} ${breaches.length === 1 ? 'breach' : 'breaches'} · ${when.toLowerCase()}`
                : `Breaches · ${when.toLowerCase()}`}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {counted
                ? `${open} still needs review`
                : breachError
                  ? 'Not counted — the list could not be loaded.'
                  : 'Counting…'}
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

        <LoadError error={breachError} onRetry={reloadBreaches} what="the breach list" />
        {breachLoading && <Empty>Loading breaches…</Empty>}
        {counted && breaches.length === 0 && (
          <Empty>No breaches {when.toLowerCase()}. Nobody entered a restricted area outside its hours.</Empty>
        )}

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
