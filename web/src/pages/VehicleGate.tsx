import { useRef, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { VehicleAlerts } from '@/components/VehicleAlerts';
import { VehicleMovementsTab } from '@/components/VehicleMovements';
import { VehicleReader } from '@/components/VehicleReader';
import { VehicleRegisterTab } from '@/components/VehicleRegister';
import { Card, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getVehicleCameras, getVehicleSummary } from '@/services/api';
import type { Camera } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

/** The tiles change as cars pass, not as fast as the frames do. */
const SUMMARY_REFRESH_MS = 3_000;

/** The camera roster changes when somebody edits it, not on its own. */
const CAMERA_REFRESH_MS = 15_000;

const NO_CAMERAS: Camera[] = [];

type Tab = 'live' | 'movements' | 'register';

const TABS: [Tab, string][] = [
  ['live', 'Live'],
  ['movements', 'Movements'],
  ['register', 'Registered vehicles'],
];

/** One stat tile.
 *
 *  **`value` is nullable and that is the whole point of this component.** A
 *  number means the engine measured it. `null` means it declined to claim
 *  one, and the tile shows a dash with the reason underneath rather than a
 *  `0` — because `0` is a measurement, and "no car came through today" and
 *  "we are not looking" must never render identically. SC-010.
 */
function Tile({ label, value, note, tone }: {
  label: string;
  value: number | null;
  note: string;
  tone?: 'accent' | 'warn' | 'bad';
}) {
  const colour = value === null ? 'var(--tx3)'
    : tone === 'bad' ? 'var(--rd)'
      : tone === 'warn' ? 'var(--am)'
        : tone === 'accent' ? 'var(--ac)' : 'var(--tx)';

  return (
    <div style={{
      background: 'var(--card)', borderRadius: 14, padding: '16px 18px',
      boxShadow: 'var(--sh)',
    }}>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{label}</div>
      <div style={{
        fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', color: colour,
      }}>
        {value === null ? '—' : value.toLocaleString()}
      </div>
      <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>{note}</div>
    </div>
  );
}

export function VehicleGate() {
  const capability = useCapability('vehicles');
  const [tab, setTab] = useState<Tab>('live');
  // An interface hint only. The server decides, and refuses a write from a
  // guard whatever this page draws.
  const isAdmin = useAccount().role === 'admin';
  // Set when somebody acts on an unregistered car's alert: the register form
  // opens with the plate already filled in from the read. With the pass list
  // gone this is the only route from "a car nobody knows just drove in" to a
  // register entry, which is why the alert carries the action rather than
  // merely announcing the problem.
  const prefill = useRef<string | null>(null);

  const { data: summary, error: summaryError } = useAsync(
    () => getVehicleSummary(), [], null, SUMMARY_REFRESH_MS);
  const { data: cameras, error: camerasError, loading: camerasLoading } = useAsync(
    () => getVehicleCameras(), [], NO_CAMERAS, CAMERA_REFRESH_MS);


  // Only where a gate has both an entry and an exit camera. Without one, an
  // exit can never be matched to an entry, so "inside now" is not a number
  // this engine can produce and must not be drawn as one.
  const paired = summary?.pairingAvailable ?? false;

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Vehicle gate"
        lead="Every car that passes a gate is photographed and its plate read, then matched against the registered list. Nothing is ever blocked by the software — a car that is not on the list still passes, and is still recorded."
      />

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
        {TABS.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className="chip-btn"
            style={{
              background: tab === key ? 'var(--card)' : 'transparent',
              color: tab === key ? 'var(--ac)' : 'var(--tx2)',
              boxShadow: tab === key ? 'var(--sh)' : 'none',
              border: 'none', borderRadius: 10, padding: '9px 16px',
              fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'live' && (
        <>
          {/* Above everything, because these are the only things on the page
              that are waiting for somebody to do something. */}
          <VehicleAlerts
            isAdmin={isAdmin}
            onRegister={(alert) => {
              prefill.current = alert.plateDisplay;
              setTab('register');
            }}
          />

          {/* A request that threw must not leave six dashes on screen: a
              dash means "the engine declined to claim a number", and a failed
              fetch means "we do not know whether it would have". Those read
              identically and are not the same thing. */}
          {summaryError && <LoadError error={summaryError} />}

          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))',
            gap: 12, marginBottom: 14,
          }}>
            <Tile
              label="Entered today"
              value={summary?.entered ?? null}
              note={summary?.gates
                ? `across ${summary.gates} gate${summary.gates === 1 ? '' : 's'}`
                : 'no gate is configured'}
            />
            <Tile
              label="Left today"
              value={summary?.left ?? null}
              note={paired ? 'each matched to its entry' : 'no exit camera is configured'}
            />
            <Tile
              label="Inside now"
              value={summary?.inside ?? null}
              note={paired ? 'entries with no exit yet' : 'needs an exit camera to compute'}
              tone="accent"
            />
            <Tile
              label="Not registered"
              value={summary?.unknown ?? null}
              note="logged, never blocked"
              tone="warn"
            />
            <Tile
              label="Blacklisted"
              value={summary?.blacklist ?? null}
              note="raised on the Home page"
              tone="bad"
            />
            {/* Replaced "Needs review", which retired with the pass list —
                weak reads are still recorded and still flagged, they simply
                no longer have a list to be reviewed in. This answers a
                question that stayed unanswerable: a gate camera that is down
                is not reading plates, and every other tile looks perfectly
                healthy while it happens. */}
            <Tile
              label="Cameras reading"
              value={summary?.camerasReading ?? null}
              note={summary?.camerasTotal
                ? `of ${summary.camerasTotal} gate camera${summary.camerasTotal === 1 ? '' : 's'}`
                : 'no gate camera is configured'}
              tone={summary && summary.camerasNote ? 'warn' : undefined}
            />
          </div>

          {/* Which camera is down, and what it costs. Only when one is. */}
          {summary?.camerasNote && (
            <Card>
              <div style={{ fontSize: 13.5, color: 'var(--am)', lineHeight: 1.5 }}>
                {summary.camerasNote}
              </div>
            </Card>
          )}

          {/* The reason the tiles are dashes, said once and in full rather
              than repeated under each one. */}
          {summary?.reason && (
            <Card>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', lineHeight: 1.5 }}>
                {summary.reason}
              </div>
            </Card>
          )}

          {camerasError && <LoadError error={camerasError} />}

          {/* No gate camera at all is the state every deployment starts in,
              and an empty grid under a "Gate cameras" heading reads as a
              loading failure. Say which it is. */}
          {!camerasError && !camerasLoading && cameras.length === 0 && (
            <Card>
              <Empty>
                No camera is set up as a gate, so no plate is being read. A
                gate camera needs a gate number and a direction in
                <code style={{ margin: '0 4px' }}>engine.yaml</code>
                before anything appears here.
              </Empty>
            </Card>
          )}

          {/* The pass list that stood here is gone, and the engine still
              records every pass exactly as before — the photograph, the
              crop, the confidence, the votes and the review flag. What
              changed is the console: the owner asked for it on 27 Aug
              knowing the costs (P6-FR-052). Registering from a read now
              lives on the alert above; the day's record lives in the
              Movements export. */}

          {/* `feature="vehicles"` is what keeps names off this grid, and it
              is worth being precise about why. The overlay request carries
              the feature (`getCameraDetections(id, feature)`) and the engine
              dispatches on it in `_boxes`, so a vehicles tile can only ever
              receive plate boxes — recognition is not consulted at all.

              `detections={false}` would be the wrong tool here: it switches
              the overlay off entirely, taking the plate boxes with it. That
              flag is for a tile showing a bare picture with no feature named,
              where the poll would otherwise fall through to faces. */}
          <CamGrid
            title="Gate cameras"
            note="One camera per direction at each gate — that is what makes entry and exit a fact rather than a guess from plate size. Green = registered, amber = not registered, red = blacklisted. The number beside each box is the plate's width in pixels: 100px or more is a comfortable read, below that still reads with less confidence. Nothing is rejected for being small — width only changes the weight of that frame's vote."
            cameras={cameras}
            feature="vehicles"
            tileOverlay
            // Exactly these, not merged over the roster. A camera with no
            // gate number is not watching a gate, and showing it under this
            // heading would imply plates are being read from it.
            only
          />

          {/* Under the cameras, deliberately: it explains what the boxes above
              are doing, and it is the only place a read that FAILED shows up
              at all — the pass log holds successes by construction. */}
          <VehicleReader />
        </>
      )}

      {tab === 'register' && (
        <VehicleRegisterTab isAdmin={isAdmin} prefillPlate={prefill} />
      )}

      {tab === 'movements' && (
        <VehicleMovementsTab isAdmin={isAdmin} summary={summary} />
      )}
    </>
  );
}
