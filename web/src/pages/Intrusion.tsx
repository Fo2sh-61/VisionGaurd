import { useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, Toggle, toneGlyph } from '@/components/ui';
import { getBreaches, getIntrusionCameras, getZones, setZoneEnabled } from '@/services/api';
import type { Breach, Camera, IntrusionWindow, Zone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const WINDOWS: IntrusionWindow[] = ['Today', 'Last 7 days', 'Last 30 days'];

/** A scene becomes watchable the moment the person leaves frame, which is a
 *  thing that happens while somebody is looking at this page rather than
 *  because they did anything. Without a poll the only way to see a new clip
 *  was to navigate away and come back. */
const LOG_REFRESH_MS = 3_000;

/** The toggles and their per-camera counts. Slower: these change when a
 *  person presses something, not on their own. */
const ZONE_REFRESH_MS = 15_000;

const NO_ZONES: Zone[] = [];
const NO_BREACHES: Breach[] = [];
const NO_CAMERAS: Camera[] = [];

export function Intrusion() {
  const capability = useCapability('breaches');
  const [when, setWhen] = useState<IntrusionWindow>('Today');

  const {
    data: loadedZones, error: zonesError, loading: zonesLoading, reload: reloadZones,
  } = useAsync(() => getZones(), [], NO_ZONES, ZONE_REFRESH_MS);
  const {
    data: breaches, error: breachError, loading: breachLoading, reload: reloadBreaches,
  } = useAsync(() => getBreaches(when), [when], NO_BREACHES, LOG_REFRESH_MS);
  const { data: cameras } = useAsync(
    () => getIntrusionCameras(), [], NO_CAMERAS, ZONE_REFRESH_MS);

  // Pending toggles, laid over what the engine last told us. A camera is only
  // drawn as restricted once the engine has agreed it is.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [toggleError, setToggleError] = useState<string | null>(null);
  // The whole entry, not just its id: the log refreshes underneath the player,
  // and an entry whose clip has just been replaced leaves the list. Looking it
  // up each render would make the video vanish mid-watch.
  const [playing, setPlaying] = useState<Breach | null>(null);
  const zones = loadedZones.map((z) => (z.id in pending ? { ...z, enabled: pending[z.id] } : z));
  const anyRestricted = zones.some((z) => z.enabled);

  async function toggleZone(zone: Zone) {
    const next = !zone.enabled;
    setToggleError(null);
    // Optimistic, so the switch feels immediate...
    setPending((p) => ({ ...p, [zone.id]: next }));
    try {
      await setZoneEnabled(zone.id, next);
      // ...and confirmed from the engine, not assumed. This used to be a
      // fire-and-forget `void setZoneEnabled(...)`: a failed call left the
      // switch showing "Paused" while the camera was still armed, or worse,
      // "Protected" while it was not. This state is a safety claim.
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
  const running = breaches.filter((b) => b.status === 'Still there').length;
  const clips = breaches.filter((b) => b.clipUrl).length;
  // The engine lists only what is still watchable, so the number of rows is
  // not the number of things that happened. This is, for today.
  const detectionsToday = zones.reduce((n, z) => n + z.detectionsToday, 0);
  const stillListed = playing !== null && breaches.some((b) => b.id === playing.id);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Restricted zones"
        lead="Mark a camera as a restricted area. Anyone who appears there is logged and recorded."
      />

      <Card tight>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Restricted cameras</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          A camera switched on here is restricted around the clock. Switch one off during
          maintenance, then back on — pauses are visible to everyone.
        </div>
        <LoadError error={zonesError} onRetry={reloadZones} what="the camera list" />
        <LoadError error={toggleError} what="that change" />
        {zonesLoading && <Empty>Loading cameras…</Empty>}
        {!zonesLoading && !zonesError && zones.length === 0 && (
          // Never demo cameras. An empty roster is an empty list.
          <Empty>No cameras are configured yet. Add one on the Cameras page.</Empty>
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
              <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                {zone.enabled
                  ? `The whole camera view is restricted · ${zone.detectionsToday} today`
                  : 'Not restricted'}
              </div>
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
                ? `${clips} ${clips === 1 ? 'clip' : 'clips'} · ${when.toLowerCase()}`
                : `Clips · ${when.toLowerCase()}`}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {counted
                ? running === 0
                  ? 'Nobody is in a restricted area right now'
                  : `${running} still in view`
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

        {/* The list is not the whole story and must not read as if it were.
            Each camera keeps three clips; everything older is still recorded,
            it just has nothing left to watch. */}
        {counted && anyRestricted && (
          <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 10 }}>
            {when === 'Today' && detectionsToday > 0
              ? `${detectionsToday} ${detectionsToday === 1 ? 'detection' : 'detections'} today. `
              : ''}
            Each camera keeps its last 3 clips — older entries drop off this list once
            their clip is replaced.
          </div>
        )}

        <LoadError error={breachError} onRetry={reloadBreaches} what="the detection log" />
        {breachLoading && <Empty>Loading detections…</Empty>}
        {/* Two different empty states, because they mean different things. An
            empty log with nothing switched on is not the same claim as an
            empty log on a camera that has been watching all day. */}
        {counted && breaches.length === 0 && !anyRestricted && (
          <Empty>No cameras are set as restricted areas. Switch one on above.</Empty>
        )}
        {counted && breaches.length === 0 && anyRestricted && (
          <Empty>Nothing has been detected since the engine started.</Empty>
        )}

        {breaches.map((breach) => (
          <div
            key={breach.id}
            className="row"
            style={{ gridTemplateColumns: '1.2fr 1fr .8fr .9fr .8fr 1.1fr' }}
          >
            <span className="row__name">{breach.zone}</span>
            <span className="row__muted">{breach.time}</span>
            <span className="row__muted">
              {breach.people === 1 ? '1 person' : `${breach.people} people`}
            </span>
            <span className="row__muted">{breach.duration}</span>
            <span>
              <Badge tone={breach.tone} glyph={toneGlyph[breach.tone]}>
                {breach.status}
              </Badge>
            </span>
            {/* No dead buttons. A clip either plays or the control is disabled
                and says why beside it. */}
            {breach.clipUrl ? (
              <button
                type="button"
                className="linkbtn"
                onClick={() =>
                  setPlaying((current) => (current?.id === breach.id ? null : breach))
                }
              >
                {playing?.id === breach.id ? 'Hide clip' : 'Watch clip'}
              </button>
            ) : (
              <span style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                {breach.clipReason ?? 'No clip was saved for this detection.'}
              </span>
            )}
          </div>
        ))}

        {playing?.clipUrl && (
          <div style={{ marginTop: 12 }}>
            <video
              key={playing.id}
              src={playing.clipUrl}
              controls
              autoPlay
              style={{ width: '100%', maxHeight: 420, borderRadius: 8 }}
            />
            {/* Replaced while it was being watched. Saying so beats the player
                silently disappearing, or failing halfway with no explanation. */}
            {!stillListed && (
              <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 6 }}>
                A newer scene on {playing.zone} has replaced this clip, so it has dropped
                off the list. It may stop playing.
              </div>
            )}
          </div>
        )}
      </Card>

      <CamGrid
        title="Cameras watching restricted areas"
        note="The whole camera view is the restricted area — there is no outline, because there is no line. Boxes mark the people detected."
        cameras={cameras}
      />
    </>
  );
}
