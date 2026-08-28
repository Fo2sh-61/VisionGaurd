import { useState } from 'react';
import { Card, Empty, LoadError } from '@/components/ui';
import { Plate } from '@/components/Plate';
import { PlateEditor } from '@/components/PlateEditor';
import {
  correctVehiclePlate, getVehicleReader, vehicleCropUrl,
} from '@/services/api';
import { COMFORTABLE_PLATE_PX, formatTime, plateWidthTone } from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** Fast, because this is the card somebody stares at while holding a plate
 *  up to the camera. It is also what boosts the reader — see `getVehicleReader`. */
const REFRESH_MS = 2_000;

const EMPTY: W.GateReaderNow = {
  cameras: [], attempts: [], votesNeeded: 0, reason: null,
};

const COLUMNS = '.7fr 1.1fr .6fr .6fr .7fr 1.1fr .6fr';

const TONE: Record<'green' | 'amber', string> = {
  green: 'var(--ac)',
  amber: 'var(--am)',
};

/** A number the engine measured, or a dash. Never a zero standing in for
 *  "unknown" — a read that produced nothing has no confidence to report. */
function Measured({ value }: { value: number | null }) {
  return (
    <span style={{ color: 'var(--tx2)', fontFamily: 'ui-monospace, Menlo, monospace' }}>
      {value === null ? '—' : value.toFixed(2)}
    </span>
  );
}

/** One gate camera: the plate it is looking at, and the answer so far.
 *
 *  **The photograph is the point.** The per-frame readings wobble by a
 *  character — that is the voting doing its job, and watching it invited an
 *  operator to distrust a system that was working. What a person can actually
 *  judge is the picture beside the settled answer: if those two agree, the
 *  gate is right, and no confidence score adds anything to that.
 */
function CameraNow({ camera, bust, votesNeeded, isAdmin, onCorrected }: {
  camera: W.GateReaderCamera;
  bust: number;
  votesNeeded: number;
  isAdmin: boolean;
  onCorrected: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const agreed = votesNeeded > 0 && camera.readingVotes >= votesNeeded;
  // Only once the row exists. Before that there is nothing to correct — the
  // votes are still gathering and the reader may yet get there on its own.
  const fixable = isAdmin && Boolean(camera.readingPassId);

  async function save(plate: string) {
    if (!camera.readingPassId) return;
    setSaving(true);
    try {
      await correctVehiclePlate(camera.readingPassId, plate);
      setEditing(false);
      onCorrected();
    } finally {
      setSaving(false);
    }
  }

  if (editing && camera.readingPassId) {
    return (
      <div style={{
        border: '1px solid var(--ac)', borderRadius: 12, padding: 14,
        display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap',
      }}>
        {camera.hasCrop && (
          <img
            src={vehicleCropUrl(camera.cameraId, bust)}
            alt="the plate being read"
            style={{
              height: 54, maxWidth: 200, objectFit: 'contain', borderRadius: 4,
              border: '1px solid var(--line)', background: '#fff',
            }}
          />
        )}
        <PlateEditor
          plate={camera.readingPlate ?? ''}
          busy={saving}
          onCancel={() => setEditing(false)}
          onSave={(plate) => { void save(plate); }}
        />
      </div>
    );
  }

  return (
    <div style={{
      border: '1px solid var(--line)', borderRadius: 12, padding: 14,
      display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap',
    }}>
      {/* The crop, or a placeholder the same height, so the card does not
          jump about as cars come and go. */}
      {camera.hasCrop ? (
        <img
          src={vehicleCropUrl(camera.cameraId, bust)}
          alt="the plate being read"
          style={{
            height: 54, maxWidth: 200, objectFit: 'contain',
            borderRadius: 4, border: '1px solid var(--line)', background: '#fff',
          }}
        />
      ) : (
        <div style={{
          height: 54, width: 120, borderRadius: 4,
          border: '1px dashed var(--line)', display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          fontSize: 12, color: 'var(--tx3)',
        }}>
          no car
        </div>
      )}

      <div style={{ flex: 1, minWidth: 170 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{camera.cameraName}</div>
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 1 }}>
          Gate {camera.gate} · {camera.direction}
        </div>
      </div>

      {camera.readingDisplay ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Plate display={camera.readingDisplay} />
          <span style={{
            fontSize: 13, fontWeight: 600,
            fontFamily: 'ui-monospace, Menlo, monospace',
            color: agreed ? 'var(--ac)' : 'var(--tx2)',
          }}>
            {agreed
              ? 'recorded'
              : `${camera.readingVotes}/${votesNeeded} frames agree`}
          </span>
          {fixable && (
            <button
              type="button"
              className="linkbtn"
              onClick={() => setEditing(true)}
              title="Type what the photograph shows"
            >
              Fix
            </button>
          )}
        </div>
      ) : (
        <span style={{ fontSize: 13, color: 'var(--tx3)' }}>
          nothing at this gate
        </span>
      )}
    </div>
  );
}

function AttemptRow({ attempt, multiCamera }: {
  attempt: W.ReaderAttempt;
  multiCamera: boolean;
}) {
  const tone = TONE[plateWidthTone(attempt.widthPx)];
  const agreed = attempt.votes >= attempt.votesNeeded;

  return (
    <div
      className="row"
      style={{
        gridTemplateColumns: COLUMNS, gap: 12, alignItems: 'center',
        padding: '9px 0', borderTop: '1px solid var(--line)', fontSize: 13.5,
      }}
    >
      <span style={{ color: 'var(--tx2)', fontFamily: 'ui-monospace, Menlo, monospace' }}>
        {formatTime(attempt.at)}
        {multiCamera && (
          <span style={{ display: 'block', fontSize: 11, color: 'var(--tx3)' }}>
            {attempt.cameraName}
          </span>
        )}
      </span>

      <span>
        {attempt.display
          ? <Plate display={attempt.display} compact />
          : <span style={{ color: 'var(--rd)', fontSize: 13 }}>read nothing</span>}
      </span>

      <Measured value={attempt.confidence} />
      <Measured value={attempt.plausibility} />

      <span style={{ color: tone, fontFamily: 'ui-monospace, Menlo, monospace' }}>
        {attempt.widthPx}px
      </span>

      <span>
        {attempt.leaderDisplay
          ? <Plate display={attempt.leaderDisplay} compact />
          : <span style={{ color: 'var(--tx3)' }}>—</span>}
      </span>

      <span style={{
        fontWeight: 600, fontFamily: 'ui-monospace, Menlo, monospace',
        color: agreed ? 'var(--ac)' : 'var(--tx2)',
      }}>
        {attempt.votes}/{attempt.votesNeeded}
      </span>
    </div>
  );
}

/** What the gate is reading, right now.
 *
 *  **Two layers, and which one is on top matters.**
 *
 *  On top: the plate photograph and the answer the votes settled on. That is
 *  everything an operator needs, and it is the truth — the settled answer is
 *  what gets written to the log.
 *
 *  Underneath, collapsed: every individual read attempt with its confidence,
 *  plausibility, width and vote count. Those wobble by a character frame to
 *  frame, which is the voting working exactly as designed, and showing them
 *  by default made a working gate look broken. They stay because they are the
 *  only way to tell three different failures apart when one happens — the
 *  camera is too far away (widths amber), the model is failing (a new answer
 *  every frame, votes never gathering), or nothing is reading at all.
 */
export function VehicleReader({ isAdmin = false }: { isAdmin?: boolean }) {
  const [showDetails, setShowDetails] = useState(false);
  const { data, error, loading, reload } = useAsync(
    () => getVehicleReader(), [], EMPTY, REFRESH_MS);

  // Bumped every poll so the browser fetches a fresh crop. Without it an
  // <img> at a fixed URL keeps showing the last car's plate — a stale picture
  // presented as live, which is the one thing this product does not do.
  const [bust, setBust] = useState(0);
  const [seen, setSeen] = useState('');
  const stamp = data.attempts[0]?.at.utc ?? '';
  if (stamp !== seen) {
    setSeen(stamp);
    setBust((n) => n + 1);
  }

  const multiCamera = data.cameras.length > 1;

  return (
    <Card>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        gap: 12, flexWrap: 'wrap',
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
            At the gate now
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 14px' }}>
            {data.reason ?? (
              <>
                The plate as the camera sees it, beside what the gate decided
                it says. A plate is only recorded once {data.votesNeeded} frames
                agree on it.
              </>
            )}
          </div>
        </div>

        {/* The diagnostics are for when something is wrong. Out of the way
            until somebody goes looking for them. */}
        {!data.reason && (
          <button
            type="button"
            className="linkbtn"
            onClick={() => setShowDetails((on) => !on)}
          >
            {showDetails ? 'Hide details' : 'Details'}
          </button>
        )}
      </div>

      {error && <LoadError error={error} />}

      {!error && data.cameras.length === 0 && !loading && (
        <Empty>{data.reason ?? 'No gate camera is being read.'}</Empty>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {data.cameras.map((camera) => (
          <CameraNow
            key={camera.cameraId}
            camera={camera}
            bust={bust}
            votesNeeded={data.votesNeeded}
            isAdmin={isAdmin}
            onCorrected={reload}
          />
        ))}
      </div>

      {showDetails && (
        <div style={{
          marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--line)',
        }}>
          <div style={{
            fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.5, marginBottom: 10,
          }}>
            Every read attempt, including the ones that came to nothing. These
            wobble by a character on purpose — no single frame is trusted, and
            the “leading candidate” column is the one that actually gets
            recorded. Use this when a gate stops working: widths under{' '}
            {COMFORTABLE_PLATE_PX}px everywhere means the camera is too far
            away; a different answer every frame with the votes never gathering
            means the model rather than the placement.
          </div>

          {data.cameras.map((camera) => (
            <div
              key={camera.cameraId}
              style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.6 }}
            >
              <b style={{ color: 'var(--tx2)' }}>{camera.cameraName}</b>
              {' · '}finds with {camera.finder}
              {' · '}reads with {camera.reader}
              {' · '}{camera.form}
              {camera.readMs !== null && ` · ${Math.round(camera.readMs)} ms per read`}
            </div>
          ))}

          {data.attempts.length === 0 ? (
            <Empty>Nothing has been read yet.</Empty>
          ) : (
            <>
              <div style={{
                display: 'grid', gridTemplateColumns: COLUMNS, gap: 12,
                padding: '14px 0 8px', fontSize: 11.5, fontWeight: 600,
                color: 'var(--tx3)', letterSpacing: '.04em',
                textTransform: 'uppercase',
              }}>
                <span>Time</span><span>What it read</span><span>Conf.</span>
                <span>Plausible</span><span>Width</span>
                <span>Leading candidate</span><span>Votes</span>
              </div>
              {data.attempts.map((attempt, i) => (
                <AttemptRow
                  key={`${attempt.cameraId}-${attempt.at.utc}-${i}`}
                  attempt={attempt}
                  multiCamera={multiCamera}
                />
              ))}
            </>
          )}
        </div>
      )}
    </Card>
  );
}
