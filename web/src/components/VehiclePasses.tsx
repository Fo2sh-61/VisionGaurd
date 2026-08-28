import { useState } from 'react';
import { Plate } from '@/components/Plate';
import { Badge, Card, CardHeader, Empty, LoadError } from '@/components/ui';
import {
  deleteVehiclePass, getVehiclePasses, vehiclePassSnapshotUrl,
} from '@/services/api';
import {
  directionLabel, formatTime, plateStatusLabel, plateStatusTone,
} from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** A car passes in seconds. This list is read by somebody at the gate. */
const REFRESH_MS = 3_000;

const NONE: W.VehiclePass[] = [];

/** Every car recorded, newest first — the plain record of what happened.
 *
 *  **This list came back on 28 Aug, and why is worth writing down.** It was
 *  removed at the owner's request, on the understanding that "inside now" and
 *  the visit tables would carry the day's record instead. They cannot: both
 *  are derived from *pairing* an entry with an exit, and a gate with one
 *  camera has no exit to pair against, so they correctly refuse to print a
 *  figure. The result was a gate that recorded nine cars and showed none of
 *  them anywhere. A page that hides real recorded data is as dishonest as one
 *  that invents it.
 *
 *  So it is back, smaller: the photograph, the plate, when, which way, and
 *  what the register said. No confidence scores and no vote counts — those
 *  live behind Details on the reader card, where somebody diagnosing a
 *  problem will look for them.
 */
export function VehiclePassesCard({ isAdmin, day }: {
  isAdmin: boolean;
  /** Empty means today. Follows the day picker above it. */
  day: string;
}) {
  const [removing, setRemoving] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const { data: passes, error, loading, reload } = useAsync(
    () => getVehiclePasses({ limit: 100, day }), [day], NONE, REFRESH_MS);

  async function remove(pass: W.VehiclePass) {
    setRemoving(pass.id);
    setProblem(null);
    try {
      await deleteVehiclePass(pass.id);
      reload();
    } catch (err) {
      setProblem(err instanceof Error
        ? err.message : 'That row could not be removed.');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Every car recorded"
        sub={isAdmin
          ? 'Newest first. Remove takes the row, its photograph and its plate crop for good — one click, no undo. The audit entry naming the plate stays.'
          : 'Newest first, with the photograph each one was recorded from.'}
      />

      {error && <LoadError error={error} />}
      {problem && (
        <div style={{ fontSize: 13, color: 'var(--rd)', marginBottom: 10 }}>
          {problem}
        </div>
      )}

      {!error && !loading && passes.length === 0 && (
        <Empty>
          No car has been recorded {day ? 'on this day' : 'yet today'}. A row
          appears here within a few seconds of a car reaching the gate.
        </Empty>
      )}

      {passes.map((pass) => (
        <div
          key={pass.id}
          className="row"
          style={{
            gridTemplateColumns: '68px 120px 1fr .7fr .6fr 1fr',
            gap: 14, alignItems: 'center', padding: '12px 0',
            borderTop: '1px solid var(--line)',
            opacity: removing === pass.id ? 0.45 : 1,
          }}
        >
          {/* The photograph it was recorded from. Absent once the image has
              aged out at thirty days — the row itself is kept for ever. */}
          {pass.hasSnapshot ? (
            <a
              href={vehiclePassSnapshotUrl(pass.id)}
              target="_blank"
              rel="noreferrer"
              title="the frame this was read from"
            >
              <img
                src={vehiclePassSnapshotUrl(pass.id)}
                alt=""
                loading="lazy"
                style={{
                  display: 'block', width: 56, height: 38, objectFit: 'cover',
                  borderRadius: 5, border: '1px solid var(--line)',
                }}
              />
            </a>
          ) : (
            <span style={{
              display: 'block', width: 56, height: 38, borderRadius: 5,
              border: '1px dashed var(--line)',
            }} />
          )}

          <Plate display={pass.plateDisplay} />

          <span style={{ minWidth: 0 }}>
            {/* Never blank. "Not in the register" is a fact about the car; an
                empty cell reads as data we failed to load. */}
            <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
              {pass.owner ?? 'Not in the register'}
            </span>
            <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
              {pass.gateName}
            </span>
          </span>

          <span>
            <Badge tone="neutral">{directionLabel(pass.direction)}</Badge>
          </span>

          <span style={{
            fontSize: 13, color: 'var(--tx2)',
            fontFamily: 'ui-monospace, Menlo, monospace',
          }}>
            {formatTime(pass.at)}
          </span>

          <span style={{
            display: 'flex', alignItems: 'center', gap: 10,
            justifyContent: 'flex-end', flexWrap: 'wrap',
          }}>
            <Badge tone={plateStatusTone(pass.status)}>
              {plateStatusLabel(pass.status)}
            </Badge>

            {/* One click. The old version asked twice, which is what made it
                unusable when a gate under test throws up a nonsense row every
                few seconds. Permanent, admin-only, audited before the row
                goes — the safeguards are on the engine, not in the clicking. */}
            {isAdmin && (
              <button
                type="button"
                className="linkbtn"
                disabled={removing === pass.id}
                onClick={() => { void remove(pass); }}
                title="Remove this row, its photograph and its plate crop. Permanent."
                style={{ color: 'var(--rd)' }}
              >
                {removing === pass.id ? 'Removing…' : 'Remove'}
              </button>
            )}
          </span>
        </div>
      ))}
    </Card>
  );
}
