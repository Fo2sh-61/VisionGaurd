/** The Movements tab: who came in, who is still here, and the full log.
 *
 *  Split out of `VehicleGate.tsx` for the same reason the register was — one
 *  page holding three tabs' worth of filter state is how a search box on one
 *  tab ends up narrowing a list on another.
 *
 *  Two things here are load-bearing rather than cosmetic:
 *
 *  - **"Inside now" needs an exit camera, and says so when there is none.**
 *    With entries only, every car that ever drove in is still "inside" for
 *    ever. That is not a number this engine can produce, so where
 *    `pairingAvailable` is false the tab prints the sentence instead of the
 *    figure. P6-FR-012.
 *  - **An exit nobody saw is labelled, never presented as observed.** A visit
 *    closed because the car was seen entering *again* is marked estimated.
 *    The car did leave; the engine did not watch it go, and the difference
 *    matters to anybody using this to answer "is that car still here?".
 */

import { useState } from 'react';
import { Plate } from '@/components/Plate';
import { Badge, Card, CardHeader, Empty, LoadError } from '@/components/ui';
import { DeletePass } from '@/components/DeletePass';
import {
  exportVehiclePasses, getVehicleGates, getVehiclePasses, getVehicleVisits,
  getVehiclesInside,
} from '@/services/api';
import {
  directionLabel, formatDuration, formatEventTime, formatTime,
  plateStatusLabel, plateStatusTone,
} from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** Cars pass in seconds; these lists are read by somebody standing at a
 *  screen asking "is it here yet?". */
const MOVEMENT_REFRESH_MS = 5_000;

const NO_GATES: W.GateTotals[] = [];
const NO_VISITS: W.VehicleVisit[] = [];
const NO_PASSES: W.VehiclePass[] = [];

const DIRECTIONS: [string, string][] = [
  ['', 'In and out'],
  ['entry', 'In only'],
  ['exit', 'Out only'],
];

const STATUSES: [string, string][] = [
  ['', 'Any status'],
  ['known', 'Registered'],
  ['unknown', 'Not registered'],
  ['blacklist', 'Blacklisted'],
  ['expired', 'Permit expired'],
];

const inputStyle = {
  height: 40, border: '1px solid var(--line)', borderRadius: 10,
  padding: '0 12px', fontSize: 13.5, background: 'var(--card)',
  color: 'var(--tx)', outline: 'none', boxSizing: 'border-box' as const,
};

/** How long a car has been here, or was. `null` when the engine did not
 *  compute one — rendered as a dash, never as "0 minutes". */
function length(minutes: number | null): string {
  return minutes === null ? '—' : formatDuration(minutes * 60);
}

function VisitRow({ visit, showLeft }: {
  visit: W.VehicleVisit;
  showLeft: boolean;
}) {
  return (
    <div
      className="row"
      style={{
        gridTemplateColumns: showLeft ? '120px 1fr .8fr .8fr .9fr' : '120px 1fr .8fr .9fr',
        gap: 14, alignItems: 'center', padding: '12px 0',
        borderTop: '1px solid var(--line)',
      }}
    >
      <Plate display={visit.plateDisplay} />
      <span style={{ minWidth: 0 }}>
        <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
          {visit.owner ?? 'Not in the register'}
        </span>
        <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
          {visit.unit ?? '—'}
        </span>
      </span>
      <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
        in at {formatTime(visit.entered)}
        <span style={{ display: 'block', fontSize: 12, color: 'var(--tx3)' }}>
          gate {visit.entryGate}
        </span>
      </span>
      {showLeft && (
        <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
          out at {formatTime(visit.leftAt)}
          <span style={{ display: 'block', fontSize: 12, color: 'var(--tx3)' }}>
            {visit.exitGate === null ? 'gate not observed' : `gate ${visit.exitGate}`}
          </span>
        </span>
      )}
      <span style={{
        display: 'flex', alignItems: 'center', gap: 10,
        justifyContent: 'flex-end', flexWrap: 'wrap',
      }}>
        {/* An exit nobody watched. Said out loud rather than folded into the
            same badge as an observed one. */}
        {visit.inferred && (
          <Badge tone="warn">Exit estimated</Badge>
        )}
        <span style={{ fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' }}>
          {length(visit.minutes)}
        </span>
      </span>
    </div>
  );
}

export function VehicleMovementsTab({ isAdmin, summary }: {
  isAdmin: boolean;
  summary: W.GateSummary | null;
}) {
  const [plate, setPlate] = useState('');
  const [direction, setDirection] = useState('');
  const [status, setStatus] = useState('');
  const [gate, setGate] = useState('');
  const [exporting, setExporting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const { data: gates } = useAsync(
    () => getVehicleGates(), [], NO_GATES, MOVEMENT_REFRESH_MS);
  const { data: inside, error: insideError } = useAsync(
    () => getVehiclesInside(), [], NO_VISITS, MOVEMENT_REFRESH_MS);
  const { data: visits } = useAsync(
    () => getVehicleVisits(), [], NO_VISITS, MOVEMENT_REFRESH_MS);
  const {
    data: passes, error: logError, loading, reload: reloadLog,
  } = useAsync(
    () => getVehiclePasses({
      limit: 200,
      plate,
      direction,
      status,
      gate: gate ? Number(gate) : undefined,
    }),
    [plate, direction, status, gate], NO_PASSES);

  // Where no gate has both an entry and an exit camera, nothing can be paired
  // and the answer to "who is inside" is a sentence, not a number.
  const paired = summary?.pairingAvailable ?? false;
  const notReading = summary?.reason ?? null;

  async function download() {
    setExporting(true);
    setProblem(null);
    try {
      await exportVehiclePasses({
        plate, direction, status, gate: gate ? Number(gate) : undefined,
      });
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'The export did not run.');
    } finally {
      setExporting(false);
    }
  }

  return (
    <>
      <Card>
        <CardHeader
          title="Today, gate by gate"
          sub="Counted from the passes recorded since midnight at the school."
        />

        {gates.length === 0 && (
          <Empty>
            {notReading
              ?? 'No gate has recorded anything today. Totals appear here as '
                + 'cars pass.'}
          </Empty>
        )}

        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(220px,1fr))',
          gap: 12,
        }}>
          {gates.map((row) => (
            <div
              key={row.gate}
              style={{
                border: '1px solid var(--line)', borderRadius: 12,
                padding: '14px 16px',
              }}
            >
              <div style={{ fontWeight: 700, fontSize: 15 }}>{row.name}</div>
              <div style={{ display: 'flex', gap: 18, margin: '10px 0 6px' }}>
                <span>
                  <span style={{ fontSize: 22, fontWeight: 700 }}>{row.entered}</span>
                  <span style={{ fontSize: 12, color: 'var(--tx3)', display: 'block' }}>
                    in
                  </span>
                </span>
                <span>
                  <span style={{ fontSize: 22, fontWeight: 700 }}>{row.left}</span>
                  <span style={{ fontSize: 12, color: 'var(--tx3)', display: 'block' }}>
                    out
                  </span>
                </span>
                <span>
                  {/* Absent, not zero. There is nothing to pair against. */}
                  <span style={{
                    fontSize: 22, fontWeight: 700,
                    color: row.inside === null ? 'var(--tx3)' : 'var(--ac)',
                  }}>
                    {row.inside === null ? '—' : row.inside}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--tx3)', display: 'block' }}>
                    inside
                  </span>
                </span>
              </div>
              {!row.pairingAvailable && (
                <div style={{ fontSize: 12, color: 'var(--am)', lineHeight: 1.4 }}>
                  This gate has no exit camera, so a car leaving is not seen and
                  nothing can be matched to its entry.
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Inside now"
          sub="Cars seen coming in today with no exit recorded since."
        />

        {insideError && <LoadError error={insideError} />}

        {/* The whole tab's honesty hinges on this branch. With entries only,
            every car that ever drove in stays "inside" for ever, and printing
            that list under this heading would be a lie by arithmetic. */}
        {!paired && (
          <Empty>
            No exit camera is configured, so no car can be matched to its exit
            and this list cannot be produced. A gate needs a second camera with
            <code style={{ margin: '0 4px' }}>direction: exit</code>
            before "inside now" means anything.
          </Empty>
        )}

        {paired && inside.length === 0 && !insideError && (
          <Empty>
            {notReading ?? 'No car is inside. Every car that came in today has '
              + 'been seen leaving.'}
          </Empty>
        )}

        {paired && inside.map((visit) => (
          <VisitRow key={`${visit.plate}-${visit.entered.utc}`} visit={visit}
                    showLeft={false} />
        ))}
      </Card>

      <Card>
        <CardHeader
          title="Completed visits"
          sub="Came in and left again today. An exit the cameras never saw is marked estimated."
        />

        {visits.length === 0 && (
          <Empty>
            {notReading ?? 'No visit has been completed today.'}
          </Empty>
        )}

        {visits.map((visit) => (
          <VisitRow key={`${visit.plate}-${visit.entered.utc}`} visit={visit}
                    showLeft />
        ))}
      </Card>

      <Card>
        <CardHeader
          title="Pass log"
          sub={isAdmin
            ? 'Every read, newest first. A weak read is kept and flagged rather than dropped, so a guard can judge it. Delete removes a pass and its photograph for good — the audit entry stays.'
            : 'Every read, newest first. A weak read is kept and flagged rather than dropped, so a guard can judge it.'}
        />

        <div style={{
          display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center',
          marginBottom: 14,
        }}>
          <input
            value={plate}
            placeholder="Plate"
            onChange={(e) => setPlate(e.target.value)}
            style={{ ...inputStyle, width: 150 }}
          />
          <input
            value={gate}
            placeholder="Gate"
            inputMode="numeric"
            onChange={(e) => setGate(e.target.value.replace(/[^0-9]/g, ''))}
            style={{ ...inputStyle, width: 90 }}
          />
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            style={inputStyle}
          >
            {DIRECTIONS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            style={inputStyle}
          >
            {STATUSES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          {/* Administrator only, and not as a courtesy: the export is a POST
              because the engine writes the audit entry before it builds the
              file, and the same path rule that guards the register guards
              this. A guard reading the log on screen is the job; taking a
              copy of it away is a decision with a name against it. */}
          {isAdmin && (
            <button
              type="button"
              disabled={exporting}
              onClick={() => void download()}
              style={{
                height: 40, padding: '0 18px', border: 'none', borderRadius: 10,
                background: 'var(--ac)', color: 'var(--on-ac)', fontWeight: 600,
                fontSize: 13.5, cursor: exporting ? 'not-allowed' : 'pointer',
                opacity: exporting ? 0.6 : 1, marginLeft: 'auto',
              }}
            >
              {exporting ? 'Preparing…' : 'Export what is shown'}
            </button>
          )}
        </div>

        {problem && (
          <div style={{ fontSize: 13, color: 'var(--rd)', marginBottom: 10 }}>
            {problem}
          </div>
        )}

        {logError && <LoadError error={logError} />}

        {!logError && !loading && passes.length === 0 && (
          <Empty>
            {plate || direction || status || gate
              ? 'No pass matches those filters. Clear one and try again.'
              : notReading ?? 'No car has passed a gate today.'}
          </Empty>
        )}

        {passes.map((pass) => (
          <div
            key={pass.id}
            className="row"
            style={{
              gridTemplateColumns: '120px 1fr .8fr .5fr .9fr',
              gap: 14, alignItems: 'center', padding: '11px 0',
              borderTop: '1px solid var(--line)',
            }}
          >
            <Plate display={pass.plateDisplay} />
            <span style={{ minWidth: 0 }}>
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
              {pass.needsReview && (
                <span style={{ fontSize: 11, color: 'var(--am)' }}>
                  needs review · {pass.confidence.toFixed(2)} over {pass.votes} frames
                </span>
              )}

              {isAdmin && (
                <DeletePass passId={pass.id} onDeleted={reloadLog} />
              )}

              <span style={{ fontSize: 12.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
                {formatEventTime(pass.at)}
              </span>
            </span>
          </div>
        ))}
      </Card>
    </>
  );
}
