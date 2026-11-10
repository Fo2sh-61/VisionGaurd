/** Start and stop recording one camera.
 *
 *  This replaced three "Save clip" buttons that did nothing when pressed. The
 *  thing it must not become is the subtler version of the same lie — a button
 *  that says a file was saved when none was written. So every answer from the
 *  engine is shown, including the refusals, and "saved" is only ever printed
 *  next to a path the engine actually returned.
 *
 *  Two facts the operator has to be told rather than discover:
 *
 *  **It records from the press, not from the alert.** Nothing is buffered, so
 *  on the Weapons page the detection that prompted the press is not in the
 *  video. `note` is where that sentence goes.
 *
 *  **It stops itself.** A recording nobody ended fills the disk overnight, so
 *  there is a limit and the button says what it is before it is reached.
 *
 *  The button disables itself when the engine says recording is unavailable,
 *  with the engine's own reason as the tooltip — a disabled control with no
 *  explanation is the thing this whole change exists to remove. */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import { useCapability } from '@/app/CapabilityContext';
import { getRecording, startRecording, stopRecording } from '@/services/api';
import type { Recording } from '@/types';

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function RecordButton({
  cameraId,
  note,
  disabled = false,
}: {
  cameraId: string;
  /** One line about what this recording will and will not contain. */
  note?: string;
  disabled?: boolean;
}) {
  const { language } = useLanguage();
  const capability = useCapability('recording');
  const [recording, setRecording] = useState<Recording | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const started = useRef<number>(0);

  const running = recording?.state === 'recording';

  // What this camera is already doing. Someone else may have started it, or
  // this panel may have been closed and reopened mid-recording.
  useEffect(() => {
    let cancelled = false;
    void getRecording(cameraId, language)
      .then((result) => {
        if (cancelled || !result.ok) return;
        if (result.recording?.state === 'recording') {
          setRecording(result.recording);
          started.current = Date.now() - result.recording.seconds * 1000;
        }
      })
      .catch(() => {
        /* the capability banner covers an unreachable engine */
      });
    return () => {
      cancelled = true;
    };
  }, [cameraId]);

  // A local timer, not a poll: the engine already told us when it started, and
  // asking it every second for a number we can count ourselves is traffic for
  // nothing.
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - started.current) / 1000)),
      500,
    );
    return () => clearInterval(timer);
  }, [running]);

  const press = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      const result = running
        ? await stopRecording(cameraId, language)
        : await startRecording(cameraId, language);

      setRecording(result.recording);
      if (result.recording?.state === 'recording') {
        started.current = Date.now() - result.recording.seconds * 1000;
        setElapsed(0);
      }

      // Everything the engine said, verbatim. A refusal, a file path, or the
      // reason a recording ended by itself — all of them are things the person
      // who just pressed the button needs to read.
      if (!result.ok) setMessage(result.reason);
      else if (result.recording?.state === 'saved')
        setMessage(`Saved to ${result.recording.file}`);
      else if (result.recording?.state === 'failed')
        setMessage(result.recording.reason);
    } catch (err) {
      setMessage(
        `The engine did not answer (${err instanceof Error ? err.message : 'no response'}).`,
      );
    } finally {
      setBusy(false);
    }
  }, [cameraId, language, running]);

  const unavailable = capability !== null && capability.state !== 'live';
  const blocked = disabled || unavailable;
  const limit = recording?.maxSeconds ?? 600;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
      <button
        type="button"
        className={running ? 'btn btn--danger' : 'btn'}
        onClick={() => void press()}
        disabled={blocked || busy}
        title={blocked ? (capability?.reason ?? 'Recording is not available.') : undefined}
      >
        {running ? `Stop recording · ${clock(elapsed)}` : 'Start recording'}
      </button>

      {blocked && (
        <div style={{ fontSize: 12, color: 'var(--tx3)', maxWidth: 320, textAlign: 'end' }}>
          {capability?.reason ?? 'Recording is not available on this camera.'}
        </div>
      )}

      {!blocked && !running && note && (
        <div style={{ fontSize: 12, color: 'var(--tx3)', maxWidth: 320, textAlign: 'end' }}>
          {note}
        </div>
      )}

      {running && (
        <div style={{ fontSize: 12, color: 'var(--tx3)', maxWidth: 320, textAlign: 'end' }}>
          Stops on its own after {Math.round(limit / 60)} minutes.
        </div>
      )}

      {message && (
        <div style={{ fontSize: 12, color: 'var(--tx2)', maxWidth: 320, textAlign: 'end' }}>
          {message}
        </div>
      )}
    </div>
  );
}
