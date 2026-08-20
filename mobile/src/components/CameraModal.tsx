import { useEffect } from 'react';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';

/** Bottom sheet — same honesty note as the web console's modal: this is a
 *  detection frame, not a live stream. */
export function CameraModal({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal__backdrop" onClick={onClose} role="presentation">
      <div className="modal__panel" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={camera.name}>
        <CameraFrame camera={camera} height={240} />
        <div style={{ padding: 18 }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{camera.name}</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>{camera.status}</div>
          <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8, lineHeight: 1.4 }}>
            Live streaming isn’t connected in this prototype — this is the detection frame the AI saw.
          </div>
          <div style={{ display: 'flex', gap: 9, marginTop: 16 }}>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Close
            </button>
            {/* Disabled, and it says why. The mobile app runs entirely on
                fixtures, so there is no engine here to ask for a recording -
                and a button that quietly does nothing is what the console
                just finished removing. */}
            <button
              type="button"
              className="btn"
              disabled
              title="This prototype is not connected to the engine, so nothing can be recorded."
            >
              Save clip
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
