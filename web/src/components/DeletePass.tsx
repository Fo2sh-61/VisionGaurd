/** Delete one pass from the gate log.
 *
 *  Its own component because it appears in two places — the Live tab, where a
 *  nonsense read is first seen, and the pass log, where it is found again
 *  later — and the two must behave identically. State is local to the button
 *  rather than lifted into either page: one row's confirmation is nobody
 *  else's business, and a page-level `confirming` id is how the wrong row
 *  ends up armed when the list refreshes underneath it.
 *
 *  **Two steps, and the second one says what it will do.** This is permanent:
 *  "inside now" and the visit list are computed from the pass table, so the
 *  engine deletes the row rather than hiding it and there is nothing to put
 *  back. The audit entry outlives the row and names the plate, which is how
 *  the log can lose a pass without the system losing the knowledge that it
 *  did.
 */

import { useState } from 'react';
import { deleteVehiclePass } from '@/services/api';

export function DeletePass({ passId, onDeleted }: {
  passId: string;
  /** Re-read the list. Never patch it here — the engine decides what the log
   *  now contains, and a list edited locally is how a page shows a delete
   *  that did not happen the way it thinks it did. */
  onDeleted: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      await deleteVehiclePass(passId);
      setConfirming(false);
      onDeleted();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That was not deleted.');
    } finally {
      setBusy(false);
    }
  }

  if (problem) {
    return (
      <span style={{ fontSize: 12, color: 'var(--rd)' }}>
        {problem}{' '}
        <button type="button" className="linkbtn"
                onClick={() => { setProblem(null); setConfirming(false); }}>
          Close
        </button>
      </span>
    );
  }

  if (!confirming) {
    return (
      <button type="button" className="linkbtn"
              onClick={() => setConfirming(true)}>
        Delete
      </button>
    );
  }

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      fontSize: 12, color: 'var(--tx2)',
    }}>
      Delete this pass and its photograph, for good?
      <button
        type="button"
        className="linkbtn"
        disabled={busy}
        style={{ color: 'var(--rd)', fontWeight: 600 }}
        onClick={() => void remove()}
      >
        {busy ? 'Deleting…' : 'Delete'}
      </button>
      <button type="button" className="linkbtn" disabled={busy}
              onClick={() => setConfirming(false)}>
        Keep it
      </button>
    </span>
  );
}
