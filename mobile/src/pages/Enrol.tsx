/** Enrolment Studio — putting a face in the gallery from the browser.
 *
 *  You cannot enrol 400 students from a command line, so this replaces
 *  `engine/tools/enroll.py` for everything except developer use.
 *
 *  Two rules the page exists to enforce, both of which come from how
 *  recognition actually fails:
 *
 *  1. **Five varied photos minimum.** One photo is one angle under one light.
 *     Recognition then fails the moment someone turns their head — and it does
 *     not fail cleanly, it produces an unreliable match, which on a register
 *     looks exactly like a working system. Save stays disabled until the engine
 *     says the set is good enough.
 *
 *  2. **Nothing is saved until Save.** Photos are staged on the engine and only
 *     written to the gallery on commit, so an abandoned enrolment leaves no
 *     half-enrolled person behind.
 *
 *  The thumbnails live here in the browser and are never uploaded for storage.
 *  The engine embeds each photo, returns an assessment, and drops the pixels —
 *  the gallery holds 128-number vectors and no images. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CameraFrame } from '@/components/CameraFrame';
import { Badge, Card, CardHeader, Field, PageHeader, Select, toneColors } from '@/components/ui';
import {
  addEnrolmentPhoto,
  cancelEnrolment,
  captureEnrolmentPhoto,
  commitEnrolment,
  getCameras,
  getEnrolmentPreview,
  removeEnrolmentPhoto,
  startEnrolment,
} from '@/services/api';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';
import { ApiError } from '@/services/http';
import type * as W from '@/services/wire';
import type { Camera, PersonType, Tone } from '@/types';

const TYPES: PersonType[] = ['Student', 'Staff', 'Visitor'];

/** How often the live view re-asks where the face is.
 *
 *  Fast enough that the outline follows somebody moving rather than stepping
 *  after them, and it only runs while a session is open — nothing is detected
 *  on the engine when nobody is on this page. */
const PREVIEW_REFRESH_MS = 300;

/** Amber: a face the system can see but cannot name.
 *
 *  Green is reserved for a person recognised by face, and this outline is the
 *  opposite of that — it is drawn precisely because the system does not know
 *  who this is yet. Colouring it green would have the enrolment page claiming
 *  the very thing it exists to establish. */
const FACE_OUTLINE = 'var(--det-amber)';

/** Thumbnails the browser holds for display, keyed by the engine's photo id.
 *  Deliberately not part of the session state on the server. */
type Thumbs = Record<string, string>;

function scoreTone(score: number): Tone {
  if (score >= 70) return 'good';
  if (score >= 45) return 'warn';
  return 'bad';
}

function ScoreBar({ score }: { score: number }) {
  const t = useT();
  return (
    <div
      style={{
        height: 6,
        borderRadius: 3,
        background: 'var(--bg3, rgba(128,128,128,.2))',
        overflow: 'hidden',
        minWidth: 90,
      }}
      role="img"
      aria-label={t('enrol.qualityAria', { score: Math.round(score) })}
    >
      <div
        style={{
          width: `${Math.max(2, Math.min(100, score))}%`,
          height: '100%',
          background: toneColors[scoreTone(score)].fg,
        }}
      />
    </div>
  );
}

export function Enrol() {
  const t = useT();
  const { language } = useLanguage();
  const navigate = useNavigate();

  // -- the form, before a session exists --------------------------------
  const [name, setName] = useState('');
  const [type, setType] = useState<PersonType>('Student');
  const [group, setGroup] = useState('');
  const [detail, setDetail] = useState('');

  // -- the session, once it does ----------------------------------------
  const [session, setSession] = useState<W.EnrolmentSession | null>(null);
  const [thumbs, setThumbs] = useState<Thumbs>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  // -- capturing from a live camera --------------------------------------
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<string>('');
  const [preview, setPreview] = useState<W.EnrolmentPreview | null>(null);

  // -- leaving mid-enrolment ---------------------------------------------
  const [confirmLeave, setConfirmLeave] = useState(false);

  const fileInput = useRef<HTMLInputElement>(null);
  // Object URLs have to be revoked or the tab leaks a blob per photo.
  const objectUrls = useRef<string[]>([]);

  useEffect(() => {
    void getCameras(language)
      .then((list) => {
        setCameras(list);
        if (list.length) setCameraId((current) => current || list[0].id);
      })
      .catch(() => setCameras([]));
  }, []);

  useEffect(
    () => () => {
      objectUrls.current.forEach((url) => URL.revokeObjectURL(url));
    },
    [],
  );

  const live = useMemo(
    () => cameras.find((c) => c.id === cameraId) ?? null,
    [cameras, cameraId],
  );

  // Keyed on the id, not the session object: the engine returns a fresh
  // session after every staged photo, and depending on the object would tear
  // the poll down and build it again each time somebody pressed Capture.
  const sessionId = session?.id ?? null;

  useEffect(() => {
    if (!sessionId || !cameraId) {
      setPreview(null);
      return;
    }

    let cancelled = false;
    const poll = () => {
      void getEnrolmentPreview(cameraId)
        .then((result) => {
          if (!cancelled) setPreview(result);
        })
        .catch(() => {
          // A dropped poll is not worth a message on screen; the next one
          // lands in 300ms and the outline stays where it was meanwhile.
        });
    };

    poll();
    const timer = setInterval(poll, PREVIEW_REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId, cameraId]);

  /** What the operator needs to hear right now, in plain words.
   *
   *  The engine's own advice is about the SET of photos — how many are usable,
   *  what angle is missing. It is the right thing to say only once the person
   *  is actually in shot, so what the camera can see comes first. */
  const guidance = (() => {
    if (!session) return '';
    if (!live) return session.advice;
    if (preview === null) return t('enrol.looking');
    if (preview.offline) {
      return t('enrol.cameraNoPicture');
    }
    if (preview.faces.length === 0) {
      return t('enrol.nobodyDetected');
    }
    if (preview.faces.length > 1) {
      return t('enrol.tooManyFaces', { count: preview.faces.length });
    }
    return session.advice;
  })();

  const say = useCallback((err: unknown) => {
    setError(
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : t('enrol.somethingWentWrong'),
    );
  }, []);

  async function begin() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setSession(await startEnrolment({ name: name.trim(), type, group, detail }));
    } catch (err) {
      say(err);
    } finally {
      setBusy(false);
    }
  }

  /** Stage a photo and remember its thumbnail against whichever id came back.
   *
   *  The engine returns the whole session, so the new photo is the one at the
   *  end that we have no thumbnail for yet. */
  async function stage(
    call: () => Promise<W.EnrolmentSession>,
    thumbUrl: string | null,
  ) {
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      if (thumbUrl) {
        const fresh = next.photos.find((p) => !(p.id in thumbs));
        if (fresh) {
          objectUrls.current.push(thumbUrl);
          setThumbs((t) => ({ ...t, [fresh.id]: thumbUrl }));
        } else {
          URL.revokeObjectURL(thumbUrl);
        }
      }
      setSession(next);
    } catch (err) {
      if (thumbUrl) URL.revokeObjectURL(thumbUrl);
      say(err);
    } finally {
      setBusy(false);
    }
  }

  async function onFiles(files: FileList | null) {
    if (!files?.length || !session) return;
    // One at a time: each upload runs the detector and embedder, and the
    // similarity check has to see the previous photo to reject a duplicate.
    for (const file of Array.from(files)) {
      await stage(
        () => addEnrolmentPhoto(session.id, file, file.name),
        URL.createObjectURL(file),
      );
    }
    if (fileInput.current) fileInput.current.value = '';
  }

  async function captureFromCamera() {
    if (!session || !cameraId) return;
    // The engine reads its own current frame, so there is no browser-side
    // image to thumbnail. The snapshot below is what the operator just saw.
    await stage(() => captureEnrolmentPhoto(session.id, cameraId), null);
  }

  async function drop(photoId: string) {
    if (!session) return;
    setBusy(true);
    try {
      setSession(await removeEnrolmentPhoto(session.id, photoId));
      setThumbs((t) => {
        const { [photoId]: gone, ...rest } = t;
        if (gone) URL.revokeObjectURL(gone);
        return rest;
      });
    } catch (err) {
      say(err);
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      const person = await commitEnrolment(session.id, language);
      setSaved(person.name);
      setSession(null);
      setThumbs({});
      setName('');
      setGroup('');
      setDetail('');
    } catch (err) {
      say(err);
    } finally {
      setBusy(false);
    }
  }

  async function discard() {
    if (session) {
      try {
        await cancelEnrolment(session.id);
      } catch {
        /* the session expires by itself; nothing was committed either way */
      }
    }
    setSession(null);
    setThumbs({});
    setError(null);
    setPreview(null);
  }

  /** Back to People, from any step.
   *
   *  With photos staged it asks once and then discards them — the session is
   *  cancelled server-side, so nothing half-saved is left behind. With no
   *  session there is nothing to lose and it simply navigates. */
  async function leave() {
    if (!session) {
      navigate('/people');
      return;
    }
    if (!confirmLeave) {
      setConfirmLeave(true);
      return;
    }
    await discard();
    navigate('/people');
  }

  return (
    <>
      {/* Visible at every step, including before a session exists. The page
          had no way out at all, which on a flow this long is a trap. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <button
          type="button"
          className="linkbtn"
          onClick={() => void leave()}
        >
          <span className="mirror-rtl" aria-hidden="true">←</span>{' '}
          {t('enrol.backToPeople')}
        </button>
        {confirmLeave && session && (
          <>
            <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
              {t(session.photos.length === 1
                ? 'enrol.leaveWarningOne' : 'enrol.leaveWarning')}
            </span>
            <button type="button" className="chip-btn chip-btn--on" onClick={() => void leave()}>
              {t('enrol.discardAndLeave')}
            </button>
            <button
              type="button"
              className="chip-btn chip-btn--off"
              onClick={() => setConfirmLeave(false)}
            >
              {t('enrol.stay')}
            </button>
          </>
        )}
      </div>

      <PageHeader
        title={t('enrol.title')}
        lead={t('enrol.lead')}
      />

      {saved && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Badge tone="good">{t('enrol.saved')}</Badge>
            <div style={{ flex: 1, minWidth: 200 }}>
              {t('enrol.savedLead', { name: saved })}
            </div>
            <button type="button" className="chip-btn chip-btn--off" onClick={() => navigate('/people')}>
              {t('enrol.viewInPeople')}
            </button>
            <button type="button" className="chip-btn chip-btn--off" onClick={() => setSaved(null)}>
              {t('enrol.enrolAnother')}
            </button>
          </div>
        </Card>
      )}

      {error && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Badge tone="bad">{t('enrol.problem')}</Badge>
            <div style={{ flex: 1 }}>{error}</div>
          </div>
        </Card>
      )}

      {!session ? (
        <Card>
          <CardHeader title={t('enrol.whoAreYouEnrolling')} sub={t('enrol.photosNextStep')} />
          <div
            style={{
              display: 'grid',
              gap: 12,
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            }}
          >
            <Field label={t('enrol.fullName')}>
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t('enrol.namePlaceholder')}
                autoFocus
              />
            </Field>
            <Field label={t('enrol.type')}>
              <Select
                value={type}
                onChange={(v) => setType(v as PersonType)}
                options={TYPES}
                label={(o) => t(`person.type.${o}` as MessageKey)}
              />
            </Field>
            <Field label={t('enrol.group')}>
              <input
                className="input"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
                placeholder={t('enrol.groupPlaceholder')}
              />
            </Field>
            <Field label={t('enrol.detail')}>
              <input
                className="input"
                value={detail}
                onChange={(e) => setDetail(e.target.value)}
                placeholder={t('enrol.detailPlaceholder')}
              />
            </Field>
          </div>
          <div style={{ marginTop: 14 }}>
            <button
              type="button"
              className="chip-btn chip-btn--on"
              disabled={!name.trim() || busy}
              onClick={() => void begin()}
            >
              {t(busy ? 'enrol.starting' : 'enrol.start')}
            </button>
          </div>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader
              title={`Enrol: ${session.name}`}
              sub={[session.type, session.group, session.detail].filter(Boolean).join(' · ')}
            />

            {live && (
              <div style={{ marginBottom: 12, maxWidth: 520 }}>
                {/* The real stream, and our own outline over it.
                    `detections={false}` because the engine's recognition boxes
                    carry names, and the page deciding who somebody IS must not
                    show the system's guess at who they are. */}
                <div style={{ position: 'relative' }}>
                  <CameraFrame camera={live} size="lg" live detections={false} />
                  <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                    {(preview?.offline ? [] : preview?.faces ?? []).map((face, i) => (
                      <div key={`box-${i}`}>
                        <div
                          style={{
                            position: 'absolute',
                            left: `${face.x * 100}%`,
                            top: `${face.y * 100}%`,
                            width: `${face.w * 100}%`,
                            height: `${face.h * 100}%`,
                            border: `2.5px solid ${FACE_OUTLINE}`,
                            borderRadius: 8,
                          }}
                        />
                        {face.points.map((point, j) => (
                          <span
                            key={`pt-${i}-${j}`}
                            style={{
                              position: 'absolute',
                              left: `${point.x * 100}%`,
                              top: `${point.y * 100}%`,
                              width: 7,
                              height: 7,
                              marginInlineStart: -3.5,
                              marginTop: -3.5,
                              borderRadius: '50%',
                              background: FACE_OUTLINE,
                              boxShadow: '0 0 0 1.5px rgba(0,0,0,.45)',
                            }}
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
                {guidance && (
                  <div
                    style={{
                      fontSize: 14,
                      fontWeight: 600,
                      color: 'var(--tx)',
                      marginTop: 8,
                    }}
                  >
                    {guidance}
                  </div>
                )}
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 4 }}>
                  {t('enrol.cameraTip')}
                </div>
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              {cameras.length > 0 && (
                <>
                  <select
                    className="input"
                    value={cameraId}
                    onChange={(e) => setCameraId(e.target.value)}
                    style={{ maxWidth: 220 }}
                    aria-label={t('enrol.cameraToCaptureFrom')}
                  >
                    {cameras.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="chip-btn chip-btn--on"
                    disabled={busy || !cameraId}
                    onClick={() => void captureFromCamera()}
                  >
                    {t(busy ? 'enrol.working' : 'enrol.capture')}
                  </button>
                </>
              )}

              <button
                type="button"
                className="chip-btn chip-btn--off"
                disabled={busy}
                onClick={() => fileInput.current?.click()}
              >
                Upload photos
              </button>
              <input
                ref={fileInput}
                type="file"
                accept="image/jpeg,image/png"
                multiple
                hidden
                onChange={(e) => void onFiles(e.target.files)}
              />
            </div>
          </Card>

          <Card>
            <CardHeader
              title={`${session.usableCount} of ${session.requiredCount} usable`}
              sub={session.advice}
            />

            {session.photos.length === 0 ? (
              <div className="empty">
                No photos yet. Capture from a camera, or upload a few taken from
                different angles.
              </div>
            ) : (
              session.photos.map((photo, index) => (
                <div
                  key={photo.id}
                  className="row"
                  style={{ gridTemplateColumns: '56px 1fr 110px 1.4fr 40px', alignItems: 'center' }}
                >
                  <div>
                    {thumbs[photo.id] ? (
                      <img
                        src={thumbs[photo.id]}
                        alt=""
                        style={{ width: 48, height: 48, objectFit: 'cover', borderRadius: 8 }}
                      />
                    ) : (
                      <div
                        style={{
                          width: 48,
                          height: 48,
                          borderRadius: 8,
                          background: 'var(--bg3, rgba(128,128,128,.15))',
                          display: 'grid',
                          placeItems: 'center',
                          fontSize: 11,
                          color: 'var(--tx2)',
                        }}
                      >
                        {photo.source.startsWith('camera:') ? 'cam' : '—'}
                      </div>
                    )}
                  </div>

                  <div style={{ fontWeight: 600 }}>{t('enrol.photoN', { n: index + 1 })}</div>

                  <div>
                    {photo.usable ? (
                      <>
                        <ScoreBar score={photo.score} />
                        <div style={{ fontSize: 12, color: 'var(--tx2)', marginTop: 3 }}>
                          {Math.round(photo.score)}%
                        </div>
                      </>
                    ) : (
                      <Badge tone="bad">{t('enrol.unusable')}</Badge>
                    )}
                  </div>

                  <div style={{ fontSize: 13.5, color: photo.usable ? 'var(--tx2)' : 'var(--tx)' }}>
                    {photo.note}
                  </div>

                  <button
                    type="button"
                    className="chip-btn chip-btn--off"
                    aria-label={`Remove photo ${index + 1}`}
                    disabled={busy}
                    onClick={() => void drop(photo.id)}
                  >
                    ×
                  </button>
                </div>
              ))
            )}

            <div
              style={{
                display: 'flex',
                gap: 10,
                marginTop: 14,
                alignItems: 'center',
                flexWrap: 'wrap',
              }}
            >
              <button
                type="button"
                className="chip-btn chip-btn--on"
                disabled={!session.ready || busy}
                onClick={() => void save()}
                title={
                  session.ready
                    ? undefined
                    : `Needs ${session.requiredCount} usable photos from different angles`
                }
              >
                {busy ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                className="chip-btn chip-btn--off"
                disabled={busy}
                onClick={() => void discard()}
              >
                Discard
              </button>
              {/* Phone (spec 015): a touch screen has no hover, so the reason
                  Save is disabled is written out, not left in `title`. */}
              {!session.ready && (
                <div style={{ fontSize: 13, color: 'var(--am)', flexBasis: '100%' }}>
                  Needs {session.requiredCount} usable photos from different angles
                </div>
              )}
              <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                Nothing is stored until you press Save. Only the face measurements are
                kept — never the photographs.
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  );
}
