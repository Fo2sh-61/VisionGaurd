import { Card, Empty, LoadError } from '@/components/ui';
import { Plate } from '@/components/Plate';
import { getVehicleReader } from '@/services/api';
import { COMFORTABLE_PLATE_PX, formatTime, plateWidthTone } from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** Fast, because this is the card somebody stares at while holding a plate
 *  up to the camera. It is also what boosts the reader — see `getVehicleReader`. */
const REFRESH_MS = 2_000;

const EMPTY: W.GateReaderNow = {
  cameras: [], attempts: [], votesNeeded: 0, reason: null,
};

/** The seven columns of the drawing, as a grid template both rows share. */
const COLUMNS = '.7fr 1.1fr .6fr .6fr .7fr 1.1fr .6fr';

const BOX_COLOUR: Record<'green' | 'amber', string> = {
  green: 'var(--ac)',
  amber: 'var(--am)',
};

/** A number the engine measured, or a dash. Never a zero standing in for
 *  "unknown" — a read that produced nothing has no confidence to report, and
 *  `0.00` would claim it measured one and found it terrible. */
function Measured({ value }: { value: number | null }) {
  return (
    <span style={{ color: 'var(--tx2)', fontFamily: 'ui-monospace, Menlo, monospace' }}>
      {value === null ? '—' : value.toFixed(2)}
    </span>
  );
}

/** One line per gate camera: which models are loaded, and how long a read takes.
 *
 *  The design mocked this as "reader easyocr · detector plate_detector.pt ·
 *  41 ms". The names here are whatever is **actually loaded** instead, so a
 *  model that fell back off its accelerated build is visible on the page where
 *  its work shows rather than only on System Health. */
function CameraLine({ camera }: { camera: W.GateReaderCamera }) {
  return (
    <div style={{ fontSize: 12.5, color: 'var(--tx3)', lineHeight: 1.6 }}>
      <b style={{ color: 'var(--tx2)' }}>{camera.cameraName}</b>
      {' · '}Gate {camera.gate} {camera.direction}
      {' · '}finds with {camera.finder}
      {' · '}reads with {camera.reader}
      {' · '}{camera.form}
      {/* Null until the first read. "0 ms" would claim a timing nobody took. */}
      {camera.readMs !== null && ` · ${Math.round(camera.readMs)} ms per read`}
    </div>
  );
}

function AttemptRow({ attempt, multiCamera }: {
  attempt: W.ReaderAttempt;
  multiCamera: boolean;
}) {
  const tone = BOX_COLOUR[plateWidthTone(attempt.widthPx)];
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
        {/* Only when there is more than one gate camera. With one, naming it
            on every row is noise; with two, an unlabelled stream is unreadable. */}
        {multiCamera && (
          <span style={{ display: 'block', fontSize: 11, color: 'var(--tx3)' }}>
            {attempt.cameraName}
          </span>
        )}
      </span>

      <span>
        {/* "read nothing" in words. A blank cell reads as data we failed to
            load, and this row is the whole reason the card exists. */}
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

/** "What the reader is seeing now" — every attempt, not just the wins.
 *
 *  **This card exists because the pass log cannot answer the question it
 *  answers.** The log contains successes by construction, so a gate that
 *  records nothing produces an identical empty log whether the camera is too
 *  far away, the model is failing, or plate reading never started. Those need
 *  three different fixes. Here they look different:
 *
 *  - widths in amber, every row      → the camera is too far from the plates
 *  - "read nothing", or a new answer
 *    every frame with votes stuck    → the model, not the placement
 *  - a reason and no table           → nothing is reading at all
 */
export function VehicleReader() {
  const { data, error, loading } = useAsync(
    () => getVehicleReader(), [], EMPTY, REFRESH_MS);

  const multiCamera = data.cameras.length > 1;

  return (
    <Card>
      <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
        What the reader is seeing now
      </div>
      <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 4px' }}>
        {data.reason ?? (
          <>
            Every attempt, including the ones that came to nothing. A plate is
            only recorded once {data.votesNeeded} frames agree on the same text
            — this is where you watch that happen.
          </>
        )}
      </div>

      {data.cameras.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          {data.cameras.map((camera) => (
            <CameraLine key={camera.cameraId} camera={camera} />
          ))}
        </div>
      )}

      {error && <LoadError error={error} />}

      {!error && data.attempts.length === 0 && !loading && (
        <Empty>
          {data.reason
            ? data.reason
            : 'Nothing has been read yet. A row appears here for every look '
              + 'the reader takes at a plate, whether or not it manages to '
              + 'read one.'}
        </Empty>
      )}

      {data.attempts.length > 0 && (
        <>
          <div
            style={{
              display: 'grid', gridTemplateColumns: COLUMNS, gap: 12,
              paddingBottom: 8, fontSize: 11.5, fontWeight: 600,
              color: 'var(--tx3)', letterSpacing: '.04em',
              textTransform: 'uppercase',
            }}
          >
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

          <div style={{
            fontSize: 12.5, color: 'var(--tx2)', marginTop: 14, paddingTop: 14,
            borderTop: '1px solid var(--line)', lineHeight: 1.5,
          }}>
            If “what it read” is always empty the reader cannot see the plate
            at all — check the width column first, since anything under{' '}
            {COMFORTABLE_PLATE_PX}px is being read from further away than the
            model is comfortable with. If it reads something different every
            time, the votes never gather and no pass is recorded: that is the
            model rather than the camera, and no setting fixes it.
          </div>
        </>
      )}
    </Card>
  );
}
