import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import type { CameraFeature } from '@/services/api';
import { describeCount } from '@/services/format';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';
import { RecordButton } from './RecordButton';

export function CameraModal({
  camera,
  onClose,
  feature,
  colour,
}: {
  camera: Camera;
  onClose: () => void;
  /** Which overlay the page that opened this was asking about. Counting
   *  wants bodies, not faces — an enlarged view that answered a different
   *  question from the page behind it would put names on a headcount. */
  feature?: CameraFeature;
  colour?: string;
}) {
  const { language } = useLanguage();
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
        {/* Header: which camera and how many people, then LIVE and close. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 16,
            padding: '13px 16px 13px 18px',
          }}
        >
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontWeight: 700,
                fontSize: 16,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}
            >
              {camera.name}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 1 }}>
              {camera.offline ? camera.status : describeCount(count, camera.status, language)}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
            {!camera.offline && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 6,
                  fontSize: 11.5,
                  fontWeight: 700,
                  letterSpacing: '.06em',
                  color: 'var(--ac)',
                  background: 'var(--chip)',
                  padding: '4px 9px',
                  borderRadius: 8,
                }}
              >
                <span className="dot" style={{ width: 6, height: 6, background: 'var(--det-red)' }} />
                LIVE
              </span>
            )}
            <button
              type="button"
              aria-label="Close"
              onClick={onClose}
              style={{
                width: 34,
                height: 34,
                borderRadius: '50%',
                border: 'none',
                background: 'transparent',
                color: 'var(--tx2)',
                fontSize: 17,
                lineHeight: 1,
                cursor: 'pointer',
              }}
            >
              ✕
            </button>
          </div>
        </div>

        {/* The enlarged view is the one place MJPEG is worth the bandwidth. The
            frame carries the stream's own shape; LIVE is in the header. */}
        <CameraFrame
          camera={camera}
          size="lg"
          live
          badge={null}
          onCount={onCount}
          feature={feature}
          colour={colour}
        />

        {/* Footer: what this view is, and what it will record. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            gap: 20,
            padding: '13px 18px 15px',
            borderTop: '1px solid var(--line)',
          }}
        >
          <div style={{ maxWidth: 420, display: 'flex', flexDirection: 'column', gap: 3 }}>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              {camera.offline
                ? 'No signal — this is the last frame received, not a live view.'
                : 'Live view. Boxes and the headcount update as the engine runs.'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 9, flexShrink: 0 }}>
            <button type="button" className="btn btn--ghost" onClick={onClose}>
              Close
            </button>
            <RecordButton
              cameraId={camera.id}
              disabled={camera.offline}
              note="Records from the moment you press it. Nothing before that is kept."
            />
          </div>
        </div>
      </div>
    </div>
  );
}
