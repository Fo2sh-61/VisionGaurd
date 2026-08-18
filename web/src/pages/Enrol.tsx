/** Enrolment Studio — putting a face in the gallery from the browser.
 *
 *  You cannot enrol 400 students from a command line, so this replaces
 *  `engine/tools/enroll.py` for everything except developer use.
 *
 *  Two rules the page exists to enforce, both of which come from how
 *  recognition actually fails:
 *
 *  1. **Three varied photos minimum.** One photo is one angle under one light.
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
import { Badge, Card, CardHeader, Field, PageHeader, Select, toneColors } from '@/components/ui';
import {
  addEnrolmentPhoto,
  cancelEnrolment,
  captureEnrolmentPhoto,
  commitEnrolment,
  getCameras,
  removeEnrolmentPhoto,
  startEnrolment,
} from '@/services/api';
import { ApiError } from '@/services/http';
import type * as W from '@/services/wire';
import type { Camera, PersonType, Tone } from '@/types';

const TYPES: PersonType[] = ['Student', 'Staff', 'Visitor'];

/** Thumbnails the browser holds for display, keyed by the engine's photo id.
 *  Deliberately not part of the session state on the server. */
type Thumbs = Record<string, string>;

function scoreTone(score: number): Tone {
  if (score >= 70) return 'good';
  if (score >= 45) return 'warn';
  return 'bad';
}

function ScoreBar({ score }: { score: number }) {
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
      aria-label={`quality ${Math.round(score)} out of 100`}
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

  const fileInput = useRef<HTMLInputElement>(null);
  // Object URLs have to be revoked or the tab leaks a blob per photo.
  const objectUrls = useRef<string[]>([]);

  useEffect(() => {
    void getCameras()
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

  const say = useCallback((err: unknown) => {
    setError(
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : 'Something went wrong.',
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
      const person = await commitEnrolment(session.id);
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
  }

  return (
    <>
      <PageHeader
        title="Enrol a face"
        lead="Add someone the cameras should recognise. Three photos from different angles — one photo is one angle under one light, and recognition fails the moment they turn their head."
      />

      {saved && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Badge tone="good">Saved</Badge>
            <div style={{ flex: 1, minWidth: 200 }}>
              <strong>{saved}</strong> is enrolled and can now be recognised.
            </div>
            <button type="button" className="chip-btn chip-btn--off" onClick={() => navigate('/people')}>
              View in People
            </button>
            <button type="button" className="chip-btn chip-btn--off" onClick={() => setSaved(null)}>
              Enrol someone else
            </button>
          </div>
        </Card>
      )}

      {error && (
        <Card tight>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Badge tone="bad">Problem</Badge>
            <div style={{ flex: 1 }}>{error}</div>
          </div>
        </Card>
      )}

      {!session ? (
        <Card>
          <CardHeader title="Who are you enrolling?" sub="You can add photos on the next step." />
          <div
            style={{
              display: 'grid',
              gap: 12,
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            }}
          >
            <Field label="Full name">
              <input
                className="input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Ahmed Hassan"
                autoFocus
              />
            </Field>
            <Field label="Type">
              <Select value={type} onChange={(v) => setType(v as PersonType)} options={TYPES} />
            </Field>
            <Field label="Group (optional)">
              <input
                className="input"
                value={group}
                onChange={(e) => setGroup(e.target.value)}
                placeholder="e.g. Grade 8"
              />
            </Field>
            <Field label="Detail (optional)">
              <input
                className="input"
                value={detail}
                onChange={(e) => setDetail(e.target.value)}
                placeholder="e.g. Grade 8 — B"
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
              {busy ? 'Starting…' : 'Start enrolment'}
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
              <div style={{ marginBottom: 12 }}>
                <img
                  src={live.snapshotUrl}
                  alt={`Live view from ${live.name}`}
                  style={{
                    width: '100%',
                    maxWidth: 520,
                    borderRadius: 12,
                    display: 'block',
                    background: 'var(--bg3, #111)',
                  }}
                />
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 6 }}>
                  Enrolling from the camera people will actually walk past — at its real
                  angle and lighting — recognises them far more reliably than a laptop webcam.
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
                    aria-label="Camera to capture from"
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
                    {busy ? 'Working…' : 'Capture'}
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

                  <div style={{ fontWeight: 600 }}>Photo {index + 1}</div>

                  <div>
                    {photo.usable ? (
                      <>
                        <ScoreBar score={photo.score} />
                        <div style={{ fontSize: 12, color: 'var(--tx2)', marginTop: 3 }}>
                          {Math.round(photo.score)}%
                        </div>
                      </>
                    ) : (
                      <Badge tone="bad">Unusable</Badge>
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
              <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
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
