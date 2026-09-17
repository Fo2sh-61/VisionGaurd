import { useCallback, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useCameras } from '@/app/CameraContext';
import { useLanguage } from '@/app/LanguageContext';
import { usePageTitle } from '@/app/PageChrome';
import { tileRefreshMs } from '@/components/CamGrid';
import { CameraFrame } from '@/components/CameraFrame';
import { RecordButton } from '@/components/RecordButton';
import { ApiError } from '@/services/http';
import { startFollow, type CameraFeature } from '@/services/api';
import { describeCount, formatCount } from '@/services/format';
import type { DetectionBox } from '@/types';
import type { MessageKey } from '@/i18n';

/** One camera, full width, with a choice of which feature draws on it
 *  (spec 015, P13-FR-047).
 *
 *  Rule 3 - each feature draws its own overlay - is kept by construction: the
 *  picture asks the engine for ONE feature's boxes (`getCameraDetections(id,
 *  feature)` inside CameraFrame), and switching asks for another. Two
 *  features' boxes are never on the picture at once, and the headcount comes
 *  from the same poll as the boxes it counts.
 *
 *  There is no colour legend. The same colours mean different things per
 *  feature - on Faces an unknown face is blue, on Track blue is a clothing
 *  match - so a legend here would be wrong on some overlay. "In view now" says
 *  it in words instead.
 *
 *  "In view now" lists what the Faces overlay drew. A name appears only on a
 *  green box - a face identified in this frame (the engine's label, with its
 *  score). Everything else reads "Not identified". It is a live annotation,
 *  re-read on every poll, never kept.
 *
 *  Follow hands the body under a face to Track a person: `startFollow` with the
 *  box centre as a fraction of the frame (rule 6), then the Track screen,
 *  which picks up the running follow on its first poll. */

const FEATURES: { id: CameraFeature; label: MessageKey }[] = [
  { id: 'attendance', label: 'phone.camera.faces' },
  { id: 'counting', label: 'phone.camera.counting' },
  { id: 'lost', label: 'phone.camera.lost' },
  { id: 'weapons', label: 'phone.camera.knife' },
];

export function CameraView() {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const { id = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const { cameras, loading } = useCameras();
  const camera = cameras.find((c) => c.id === id) ?? null;
  usePageTitle(camera?.name);

  const asked = params.get('feature') as CameraFeature | null;
  const feature: CameraFeature = FEATURES.some((f) => f.id === asked) ? asked! : 'attendance';

  const [boxes, setBoxes] = useState<DetectionBox[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [followError, setFollowError] = useState('');
  const [following, setFollowing] = useState(false);
  const onBoxes = useCallback((next: DetectionBox[]) => setBoxes(next), []);
  const onCount = useCallback((next: number | null) => setCount(next), []);

  function choose(next: CameraFeature) {
    setBoxes([]);
    setCount(null);
    setFollowError('');
    setParams(next === 'attendance' ? {} : { feature: next }, { replace: true });
  }

  async function follow(box: DetectionBox) {
    if (!camera) return;
    setFollowing(true);
    setFollowError('');
    try {
      await startFollow(camera.id, (box.x + box.w / 2) / 100, (box.y + box.h / 2) / 100);
      navigate('/track');
    } catch (err) {
      const status = err instanceof ApiError ? err.status : 0;
      setFollowError(status === 404
        ? t('track.nobodyThereToFollow')
        : err instanceof ApiError ? err.message : t('track.couldNotStartFollowing'));
    } finally {
      setFollowing(false);
    }
  }

  if (!camera) {
    return loading
      ? <div className="empty">{t('bell.checking')}</div>
      : <div className="card empty">{t('phone.camera.notListed')}</div>;
  }

  const others = cameras.filter((c) => c.id !== camera.id);

  return (
    <>
      {/* The picture edge to edge: out of the screen's 16 px gutter. */}
      <div style={{ margin: '-4px -16px 0' }}>
        <CameraFrame
          key={`${camera.id}:${feature}`}
          camera={camera}
          size="lg"
          live
          feature={feature}
          onBoxes={onBoxes}
          onCount={onCount}
        />
      </div>

      <div className="spread" role="status">
        <span className="li__sub" style={camera.offline ? { color: 'var(--rd)', fontWeight: 600 } : undefined}>
          {camera.offline
            ? `${t('phone.camera.noSignal')} · ${t('phone.camera.lastPicture', { time: camera.time ?? '—' })}`
            : describeCount(count, camera.status, language)}
        </span>
        {camera.area && <span className="li__sub">{camera.area}</span>}
      </div>

      <div className="field">
        <span className="field__label" id="boxes-by">{t('phone.camera.boxesBy')}</span>
        <div className="seg" role="group" aria-labelledby="boxes-by">
          {FEATURES.map((f) => (
            <button
              key={f.id}
              type="button"
              className={feature === f.id ? 'seg__btn seg__btn--on' : 'seg__btn'}
              aria-pressed={feature === f.id}
              onClick={() => choose(f.id)}
            >
              {t(f.label)}
            </button>
          ))}
        </div>
      </div>

      {!camera.offline && boxes.length === 0 && (
        <p className="note">{t('phone.camera.noBoxes')}</p>
      )}
      {feature === 'counting' && <p className="note">{t('phone.camera.inViewNote')}</p>}

      {feature === 'attendance' && boxes.length > 0 && (
        <section className="stack" aria-labelledby="in-view">
          <div className="sechead">
            <h2 className="sechead__title" id="in-view" style={{ margin: 0 }}>
              {t('phone.camera.inViewNow')} · {formatCount(boxes.length, language)}
            </h2>
          </div>
          {followError && <div className="notice notice--amber" role="alert">{followError}</div>}
          <div className="list">
            {boxes.map((box, i) => {
              const named = box.color === 'green' && !!box.label;
              return (
                <div key={box.trackId ?? `${box.x}:${box.y}:${i}`} className="li">
                  <span
                    className="avatar"
                    aria-hidden="true"
                    style={named ? undefined : { background: 'var(--am-bg)', color: 'var(--am)' }}
                  >
                    {named ? initials(box.label!) : '?'}
                  </span>
                  <span className="li__main">
                    <span className="li__title">{named ? box.label : t('phone.camera.notIdentified')}</span>
                    <span>
                      <span
                        className="badge"
                        style={named
                          ? { background: 'var(--chip)', color: 'var(--ac2)' }
                          : { background: 'var(--am-bg)', color: 'var(--am)' }}
                      >
                        {named ? t('phone.camera.face') : t('phone.camera.notIdentified')}
                      </span>
                    </span>
                  </span>
                  <button
                    type="button"
                    className="btn btn--soft btn--sm"
                    disabled={following}
                    onClick={() => void follow(box)}
                  >
                    {t('phone.camera.follow')}
                  </button>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <div className="card stack" style={{ gap: 10 }}>
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

      {others.length > 0 && (
        <section className="stack" aria-labelledby="other-cameras">
          <div className="sechead">
            <h2 className="sechead__title" id="other-cameras" style={{ margin: 0 }}>{t('phone.camera.other')}</h2>
          </div>
          <div className="hscroll">
            {others.map((cam) => (
              <button
                key={cam.id}
                type="button"
                className="camtile"
                style={{ width: 160, flexShrink: 0 }}
                onClick={() => navigate(
                  `/cameras/${encodeURIComponent(cam.id)}${feature === 'attendance' ? '' : `?feature=${feature}`}`,
                  { replace: true },
                )}
              >
                <CameraFrame camera={cam} detections={false} refreshMs={tileRefreshMs(others.length)} />
                <span className="camtile__name" style={{ display: 'block', paddingTop: 6 }}>{cam.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function initials(name: string): string {
  // The label may end in the engine's score ("87%"); initials come from the words.
  return name.split(/\s+/).filter((w) => w && !/\d/.test(w)).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('');
}
