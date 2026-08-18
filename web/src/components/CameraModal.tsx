import { useCallback, useEffect, useState } from 'react';
import { describeCount } from '@/services/format';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';

export function CameraModal({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const [count, setCount] = useState<number | null>(null);

  // The frame already polls detections ~10x a second; it hands the headcount
  // back from the same response rather than the modal running its own timer
  // against a second endpoint. One inference pass, one poll, one number — so
  // the count can never disagree with the boxes drawn beside it.
  const onCount = useCallback((next: number | null) => setCount(next), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="modal__backdrop" onClick={onClose} role="presentation">
      <div
        className="modal__panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={camera.name}
      >
        {/* The enlarged view is the one place MJPEG is worth the bandwidth. */}
        <CameraFrame camera={camera} size="lg" live onCount={onCount} />

        <div style={{ padding: '18px 22px' }}>
          <div style={{ fontWeight: 700, fontSize: 16 }}>{camera.name}</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
            {camera.offline ? camera.status : describeCount(count, camera.status)}
          </div>
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 8 }}>
            {camera.offline
              ? 'No signal — this is the last frame received, not a live view.'
              : 'Live view. Boxes and the headcount update as the engine runs.'}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 9, marginTop: 14 }}>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Close
            </button>
            <button type="button" className="btn">
              Save clip
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
