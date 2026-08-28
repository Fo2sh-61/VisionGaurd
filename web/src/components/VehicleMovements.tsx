/** The Movements tab: what happened on a day, and who is here now.
 *
 *  Split out of `VehicleGate.tsx` for the same reason the register was — one
 *  page holding three tabs' worth of filter state is how a search box on one
 *  tab ends up narrowing a list on another.
 *
 *  Four things here are load-bearing rather than cosmetic:
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
 *  - **"Inside now" ignores the day picker.** Now is only ever now. Asking who
 *    was inside last Tuesday is asking about a moment that has passed, which
 *    the pass log cannot answer and this must not pretend to.
 *  - **The day scopes the tables; the search scopes them further.** The chart
 *    and the gate totals stay on the whole picked day, because a chart that
 *    silently redrew itself around a search would be a different question
 *    wearing the same title. The scope line says which is which.
 */

import { useState } from 'react';
import { Plate } from '@/components/Plate';
import { VehiclePassesCard } from '@/components/VehiclePasses';
import { Badge, Card, CardHeader, Empty, LoadError } from '@/components/ui';
import {
  deleteVehiclePass, exportVehiclePasses, getVehicleGates,
  getVehicleTraffic, getVehicleVisits,
  getVehiclesInside, vehiclePassSnapshotUrl,
} from '@/services/api';
import { formatDuration, formatTime } from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** Cars pass in seconds; these lists are read by somebody standing at a
 *  screen asking "is it here yet?". */
const MOVEMENT_REFRESH_MS = 5_000;

const NO_GATES: W.GateTotals[] = [];
const NO_VISITS: W.VehicleVisit[] = [];
const NO_HOURS: W.TrafficHour[] = [];

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

/** "8am" · "12pm" — the hour labels under the traffic chart. */
function hourLabel(hour: number): string {
  if (hour === 0) return '12a';
  if (hour === 12) return '12p';
  return hour < 12 ? `${hour}a` : `${hour - 12}p`;
}

/** The photograph kept with a pass, as a thumbnail that opens the full frame.
 *
 *  Only rendered where the visit says the image still exists. A pass row is
 *  kept for ever and its picture is deleted at thirty days, so a thumbnail
 *  drawn on faith would become a broken image on every old row. */
function Shot({ passId, hasSnapshot, label }: {
  passId: string | null;
  hasSnapshot: boolean;
  label: string;
}) {
  if (!passId || !hasSnapshot) {
    return (
      <span style={{
        display: 'block', width: 56, height: 38, borderRadius: 5,
        border: '1px dashed var(--line)',
      }} />
    );
  }
  const href = vehiclePassSnapshotUrl(passId);
  return (
    <a href={href} target="_blank" rel="noreferrer" title={label}>
      <img
        src={href}
        alt={label}
        loading="lazy"
        style={{
          display: 'block', width: 56, height: 38, objectFit: 'cover',
          borderRadius: 5, border: '1px solid var(--line)', cursor: 'pointer',
        }}
      />
    </a>
  );
}

/** In above the line, out below it.
 *
 *  Bars are drawn only for hours that have something in them. A flat bar at
 *  3am would be a drawing of data that does not exist. */
function TrafficChart({ hours }: { hours: W.TrafficHour[] }) {
  const tallest = Math.max(1, ...hours.map((h) => Math.max(h.entered, h.left)));

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 4, height: 170 }}>
        {hours.map((h) => (
          <div
            key={h.hour}
            title={`${hourLabel(h.hour)} — ${h.entered} in, ${h.left} out`}
            style={{
              flex: 1, display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'flex-end', gap: 2,
            }}
          >
            <div style={{
              flex: 1, display: 'flex', flexDirection: 'column',
              justifyContent: 'flex-end', width: '100%',
            }}>
              <div style={{
                width: '100%', background: 'var(--ac)', borderRadius: '3px 3px 0 0',
                height: `${Math.round((h.entered / tallest) * 100)}%`,
              }} />
            </div>
            <div style={{
              flex: 1, display: 'flex', flexDirection: 'column',
              justifyContent: 'flex-start', width: '100%',
            }}>
              <div style={{
                width: '100%', background: 'var(--tx3)', borderRadius: '0 0 3px 3px',
                height: `${Math.round((h.left / tallest) * 100)}%`,
              }} />
            </div>
            <div style={{
              fontSize: 10, color: 'var(--tx3)',
              fontFamily: 'ui-monospace, Menlo, monospace',
            }}>
              {hourLabel(h.hour)}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 18, marginTop: 14, fontSize: 12.5, color: 'var(--tx2)' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 11, height: 11, borderRadius: 3, background: 'var(--ac)' }} />
          In
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 11, height: 11, borderRadius: 3, background: 'var(--tx3)' }} />
          Out
        </span>
      </div>
    </>
  );
}

function VisitRow({ visit, showLeft, isAdmin, onRemoved }: {
  visit: W.VehicleVisit;
  showLeft: boolean;
  /** Only on "inside now", and only for an administrator: with no exit
   *  camera nobody is ever seen leaving, so clearing a car that has gone is
   *  a manual job until a second camera exists. Removing the entry pass is
   *  what takes it off this list — the same permanent, audited delete as
   *  anywhere else. */
  isAdmin?: boolean;
  onRemoved?: () => void;
}) {
  const [removing, setRemoving] = useState(false);

  async function remove() {
    if (!visit.entryPassId) return;
    setRemoving(true);
    try {
      await deleteVehiclePass(visit.entryPassId);
      onRemoved?.();
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div
      className="row"
      style={{
        gridTemplateColumns: showLeft
          ? '68px 120px 1fr .8fr .8fr .9fr'
          : '68px 120px 1fr .8fr .9fr',
        gap: 14, alignItems: 'center', padding: '12px 0',
        borderTop: '1px solid var(--line)',
      }}
    >
      <Shot
        passId={visit.entryPassId}
        hasSnapshot={visit.entryHasSnapshot}
        label={`${visit.plateDisplay} arriving`}
      />
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
        {isAdmin && onRemoved && visit.entryPassId && (
          <button
            type="button"
            className="linkbtn"
            disabled={removing}
            onClick={() => { void remove(); }}
            title="This car has gone. Removes its pass, photograph and crop. Permanent."
            style={{ color: 'var(--rd)' }}
          >
            {removing ? 'Removing…' : 'Gone'}
          </button>
        )}
      </span>
    </div>
  );
}

export function VehicleMovementsTab({ isAdmin, summary }: {
  isAdmin: boolean;
  summary: W.GateSummary | null;
}) {
  // Empty means today. Kept empty rather than filled with today's date so the
  // engine decides what "today" is — the site's midnight, not the browser's.
  const [day, setDay] = useState('');
  const [query, setQuery] = useState('');
  const [gate, setGate] = useState('');
  const [exporting, setExporting] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const { data: gates } = useAsync(
    () => getVehicleGates(day), [day], NO_GATES, MOVEMENT_REFRESH_MS);
  const { data: hours } = useAsync(
    () => getVehicleTraffic(day), [day], NO_HOURS, MOVEMENT_REFRESH_MS);
  const {
    data: inside, error: insideError, reload: reloadInside,
  } = useAsync(
    () => getVehiclesInside(), [], NO_VISITS, MOVEMENT_REFRESH_MS);
  const { data: visits } = useAsync(
    () => getVehicleVisits(day), [day], NO_VISITS, MOVEMENT_REFRESH_MS);

  // Where no gate has both an entry and an exit camera, nothing can be paired
  // and the answer to "who is inside" is a sentence, not a number.
  const paired = summary?.pairingAvailable ?? false;
  const notReading = summary?.reason ?? null;

  const needle = query.trim().toLowerCase();
  const matches = (visit: W.VehicleVisit) =>
    (!gate || String(visit.entryGate) === gate)
    && (!needle
      || visit.plateDisplay.includes(query.trim())
      || (visit.owner ?? '').toLowerCase().includes(needle));

  const insideShown = inside.filter(matches);
  const visitsShown = visits.filter(matches);
  const filtering = Boolean(needle || gate);

  // **One unpairable gate makes the total unknowable, not smaller.** Summing
  // the gates that can be paired and printing that as "all gates" would be a
  // partial sum wearing the name of a total — the reader has no way to tell
  // it is missing a gate, and it is wrong in the reassuring direction.
  const everyGatePairs = gates.length > 0 && gates.every((r) => r.inside !== null);
  const totals = {
    entered: gates.reduce((n, r) => n + r.entered, 0),
    left: gates.reduce((n, r) => n + r.left, 0),
    inside: everyGatePairs
      ? gates.reduce((n, r) => n + (r.inside ?? 0), 0)
      : null,
  };

  async function download() {
    setExporting(true);
    setProblem(null);
    try {
      await exportVehiclePasses({
        day, gate: gate ? Number(gate) : undefined,
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
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
              Day
            </span>
            <input
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
              style={inputStyle}
            />
          </label>

          <label style={{
            display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 190,
          }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
              Plate or owner
            </span>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="ب ج د ١٢٣٤ or a name"
              style={inputStyle}
            />
          </label>

          <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
              Gate
            </span>
            <select
              value={gate}
              onChange={(e) => setGate(e.target.value)}
              style={inputStyle}
            >
              <option value="">All gates</option>
              {gates.map((row) => (
                <option key={row.gate} value={String(row.gate)}>{row.name}</option>
              ))}
            </select>
          </label>

          {/* Admin only, and audited before the file is built. A guard reads
              the gate log; taking a copy of it away is a different act. */}
          {isAdmin && (
            <button
              type="button"
              className="chip-btn chip-btn--on"
              onClick={() => { void download(); }}
              disabled={exporting}
              style={{ height: 40, padding: '0 18px', borderRadius: 10 }}
            >
              {exporting ? 'Preparing…' : 'Export this day'}
            </button>
          )}
        </div>

        {problem && (
          <div style={{ fontSize: 13, color: 'var(--rd)', marginTop: 10 }}>
            {problem}
          </div>
        )}

        {/* Which numbers the filters moved and which they did not. Without
            this line a filtered visit list beside unfiltered totals reads as
            an arithmetic error. */}
        <div style={{ fontSize: 13, color: 'var(--tx3)', marginTop: 12 }}>
          {filtering
            ? `Filtered — ${insideShown.length} inside, ${visitsShown.length} `
              + 'completed visits. The chart and the gate totals stay on the '
              + 'whole day.'
            : day
              ? 'Everything below is that day, except “inside now”, which is '
                + 'always now.'
              : 'Everything below is today.'}
        </div>
      </Card>

      {/* First, because on a gate with one camera this is the ONLY place a
          recorded car appears: everything below needs an exit camera to pair
          against and correctly refuses to guess without one. */}
      <VehiclePassesCard isAdmin={isAdmin} day={day} />

      <Card>
        <CardHeader
          title="Traffic through the day"
          sub="In above the line, out below it. Only hours something happened in are drawn."
        />
        {hours.length === 0 ? (
          <Empty>
            {notReading ?? 'Nothing passed a gate on this day.'}
          </Empty>
        ) : (
          <TrafficChart hours={hours} />
        )}
      </Card>

      <Card>
        <CardHeader
          title="Gate by gate"
          sub="Counted from the passes recorded at each gate."
        />

        {gates.length === 0 && (
          <Empty>
            {notReading
              ?? 'No gate recorded anything on this day. Totals appear here as '
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

        {gates.length > 1 && (
          <div style={{
            display: 'flex', gap: 24, alignItems: 'baseline', marginTop: 16,
            paddingTop: 14, borderTop: '2px solid var(--line)', fontSize: 14,
          }}>
            <span style={{ fontWeight: 700 }}>All gates</span>
            <span><b>{totals.entered}</b> in</span>
            <span><b>{totals.left}</b> out</span>
            <span>
              {/* One gate without an exit camera makes the total unknowable,
                  not smaller — so it is a dash, not a partial sum. */}
              <b style={{ color: totals.inside === null ? 'var(--tx3)' : 'var(--ac)' }}>
                {totals.inside === null ? '—' : totals.inside}
              </b>
              {' '}inside
            </span>
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Inside now"
          sub="Cars seen coming in with no exit recorded since. Always now, whichever day is picked above."
        />

        {insideError && <LoadError error={insideError} />}

        {/* With no exit camera nobody is ever *seen* leaving, so this list is
            every car that came in — an over-count, and said so in words above
            the rows rather than withheld.

            It used to be withheld entirely, which was the wrong call. On a
            single-camera gate — what every deployment starts as — that left a
            page with nine recorded cars and nothing on it. An over-count
            labelled as one is honest; an empty page is not more honest for
            being emptier. The *number* on the Live tile is still absent,
            because a tile has nowhere to carry the caveat. */}
        {!paired && insideShown.length > 0 && (
          <div style={{
            fontSize: 12.5, color: 'var(--am)', lineHeight: 1.45,
            padding: '10px 12px', borderRadius: 10,
            background: 'var(--am-bg)', marginBottom: 12,
          }}>
            No exit camera is configured, so no car is ever seen leaving.
            This is therefore every car that came in — an over-count, not a
            count of what is on site. Adding a second camera with{' '}
            <code>direction: exit</code> at this gate is what turns it into
            an answer. Until then, remove a row by hand once you know the car
            has gone.
          </div>
        )}

        {insideShown.length === 0 && !insideError && (
          <Empty>
            {filtering
              ? 'No car inside matches that search.'
              : notReading ?? (paired
                ? 'No car is inside. Every car that came in today has been '
                  + 'seen leaving.'
                : 'No car has come in today.')}
          </Empty>
        )}

        {insideShown.map((visit) => (
          <VisitRow
            key={`${visit.plate}-${visit.entered.utc}`}
            visit={visit}
            showLeft={false}
            isAdmin={isAdmin}
            onRemoved={reloadInside}
          />
        ))}
      </Card>

      <Card>
        <CardHeader
          title="Completed visits"
          sub="Came in and left again. An exit the cameras never saw is marked estimated."
        />

        {visitsShown.length === 0 && (
          <Empty>
            {filtering
              ? 'No completed visit matches that search.'
              : notReading ?? 'No visit was completed on this day.'}
          </Empty>
        )}

        {visitsShown.map((visit) => (
          <VisitRow key={`${visit.plate}-${visit.entered.utc}`} visit={visit}
                    showLeft />
        ))}
      </Card>
    </>
  );
}
