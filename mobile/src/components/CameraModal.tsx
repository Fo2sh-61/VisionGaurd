import { useCallback, useEffect, useState } from 'react';
import { useLanguage } from '@/app/LanguageContext';
import type { CameraFeature } from '@/services/api';
import { describeCount } from '@/services/format';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';
import { Icon } from './Icon';
import { RecordButton } from './RecordButton';

/** One camera, enlarged, over the tool that opened it.
 *
 *  On the console this is a dialog. On a phone a dialog would leave the
 *  picture the size of a stamp, so it covers the screen, with a back arrow
 *  where the phone always puts one (spec 015). The tool underneath stays
 *  mounted, so closing this returns to it exactly as it was - results, filters
 *  and scroll position.
 *
 *  Everything it says and does is the console's: the headcount from the same
 *  poll that draws the boxes, the live/last-frame note, and Record. */
export function CameraModal({
  camera,
  onClose,
  feature,
  colour,
  detections = true,
}: {
  camera: Camera;
  onClose: () => void;
  /** Which overlay the page that opened this was asking about. Counting
   *  wants bodies, not faces — an enlarged view that answered a different
   *  question from the page behind it would put names on a headcount. */
  feature?: CameraFeature;
  colour?: string;
  /** False on a screen that must not name anybody (System health). */
  detections?: boolean;
}) {
  const { language, t } = useLanguage();
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
    <div className="modal__backdrop" role="presentation">
      <div className="modal__panel" role="dialog" aria-modal="true" aria-label={camera.name}>
        <header className="screenhead">
          <button type="button" className="iconbtn" aria-label={t('phone.back')} onClick={onClose}>
            <Icon name="back" size={22} strokeWidth={2} mirror />
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div className="screenhead__title">{camera.name}</div>
            <div className="li__sub" style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {camera.offline ? camera.status : describeCount(count, camera.status, language)}
            </div>
          </div>
          {!camera.offline && (
            <span className="badge" style={{ background: 'var(--chip)', color: 'var(--ac2)', letterSpacing: '.06em' }}>
              <span className="dot" style={{ width: 6, height: 6, background: 'var(--det-red)' }} />
              LIVE
            </span>
          )}
        </header>

        <div className="modal__body">
          {/* The enlarged view is the one place MJPEG is worth the bandwidth. */}
          <CameraFrame
            camera={camera}
            size="lg"
            live
            badge={null}
            onCount={onCount}
            feature={feature}
            colour={colour}
            detections={detections}
          />

          <div className="screen" style={{ paddingTop: 14 }}>
            <p className="note">
              {camera.offline
                ? 'No signal — this is the last frame received, not a live view.'
                : 'Live view. Boxes and the headcount update as the engine runs.'}
            </p>
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
