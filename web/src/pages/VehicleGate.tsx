import { useRef, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { DeletePass } from '@/components/DeletePass';
import { Plate } from '@/components/Plate';
import { VehicleMovementsTab } from '@/components/VehicleMovements';
import { VehicleReader } from '@/components/VehicleReader';
import { VehicleRegisterTab } from '@/components/VehicleRegister';
import { Badge, Card, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getVehicleCameras, getVehiclePasses, getVehicleSummary } from '@/services/api';
import { directionLabel, formatEventTime, plateStatusLabel, plateStatusTone } from '@/services/format';
import type * as W from '@/services/wire';
import type { Camera } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

/** A car passes in seconds. The list has to keep up with the barrier. */
const PASS_REFRESH_MS = 2_000;

/** The tiles change as cars pass, not as fast as the frames do. */
const SUMMARY_REFRESH_MS = 3_000;

/** The camera roster changes when somebody edits it, not on its own. */
const CAMERA_REFRESH_MS = 15_000;

const NO_PASSES: W.VehiclePass[] = [];
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
  // Set when somebody clicks Register on an unregistered pass: the register
  // form opens with the plate already filled in from the photograph. This is
  // the fastest way to fill an empty register in the first week.
  const prefill = useRef<string | null>(null);

  const { data: summary } = useAsync(
    () => getVehicleSummary(), [], null, SUMMARY_REFRESH_MS);
  const { data: cameras } = useAsync(
    () => getVehicleCameras(), [], NO_CAMERAS, CAMERA_REFRESH_MS);
  const {
    data: passes, error, loading, reload: reloadPasses,
  } = useAsync(() => getVehiclePasses({ limit: 12 }), [], NO_PASSES, PASS_REFRESH_MS);

  // Nothing on this page may imply cars are being read unless they are. An
  // empty list from a feature that never started is not "no cars today".
  const running = capability?.state === 'live';
  const notRunning = capability?.reason ?? 'Plate reading is not running.';

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
            <Tile
              label="Needs review"
              value={summary?.needsReview ?? null}
              note="weak reads, kept not discarded"
              tone="warn"
            />
          </div>

          {/* The reason the tiles are dashes, said once and in full rather
              than repeated under each one. */}
          {summary?.reason && (
            <Card>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', lineHeight: 1.5 }}>
                {summary.reason}
              </div>
            </Card>
          )}

          <Card>
            <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
              Passing now
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 14px' }}>
              {running
                ? 'The last few reads, newest first. A plate is only recorded once three frames agree on it.'
                : notRunning}
            </div>

            {error && <LoadError error={error} />}
            {!error && !loading && passes.length === 0 && (
              <Empty>
                {running
                  ? 'No car has passed yet today. Passes appear here within a '
                    + 'few seconds of a car reaching the gate.'
                  : notRunning}
              </Empty>
            )}

            {passes.map((pass) => (
              <div
                key={pass.id}
                className="row"
                style={{
                  gridTemplateColumns: '120px 1fr .8fr .6fr 1fr',
                  gap: 14, alignItems: 'center', padding: '12px 0',
                  borderTop: '1px solid var(--line)',
                }}
              >
                <Plate display={pass.plateDisplay} />
                <span style={{ minWidth: 0 }}>
                  {/* Never blank. "Not in the register" is a fact about the
                      car; an empty cell reads as data we failed to load. */}
                  <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
                    {pass.owner ?? 'Not in the register'}
                  </span>
                  <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                    {pass.unit ?? '—'}
                  </span>
                </span>
                <span style={{ fontSize: 13.5, color: 'var(--tx2)' }}>{pass.gateName}</span>
                <span>
                  <Badge tone="neutral">{directionLabel(pass.direction)}</Badge>
                </span>
                <span style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  justifyContent: 'flex-end', flexWrap: 'wrap',
                }}>
                  <Badge tone={plateStatusTone(pass.status)}>
                    {plateStatusLabel(pass.status)}
                  </Badge>
                  {/* A weak read is kept, flagged, and shows its own numbers
                      so a guard can judge rather than take a flag on faith. */}
                  {pass.needsReview && (
                    <span style={{ fontSize: 11, color: 'var(--am)' }}>
                      needs review · {pass.confidence.toFixed(2)} over {pass.votes} frames
                    </span>
                  )}
                  {/* The fastest way to fill an empty register: the plate
                      is already read, so it should not have to be typed. */}
                  {isAdmin && pass.status === 'unknown' && (
                    <button
                      type="button"
                      className="linkbtn"
                      onClick={() => {
                        prefill.current = pass.plateDisplay;
                        setTab('register');
                      }}
                    >
                      Register
                    </button>
                  )}
                  {/* Here as well as in the pass log, because this is where a
                      nonsense read is seen first — a reflection, half a
                      lorry, a plate that belongs to nobody. */}
                  {isAdmin && (
                    <DeletePass passId={pass.id} onDeleted={reloadPasses} />
                  )}
                  <span style={{ fontSize: 12.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
                    {formatEventTime(pass.at)}
                  </span>
                </span>
              </div>
            ))}
          </Card>

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
