import { useMemo, useState, type ReactNode } from 'react';
import { CameraFrame } from '@/components/CameraFrame';
import { withoutZone } from '@/components/AreaPicture';
import { Card, Field, Select } from '@/components/ui';
import { useT } from '@/app/LanguageContext';
import type { PictureRect } from '@/services/frame';
import type { AreaPoint, Camera, WatchedHours, WatchedMode } from '@/types';

/** The three rules a shape must meet. The engine checks the same three and
 *  refuses with a plain reason; this only tells the person sooner, so Save
 *  stays off until the shape can possibly be accepted. The numbers match
 *  `engine/vg/areas.py`. */
export const MIN_AREA_FRACTION = 0.002;

type Shape = 'few' | 'crossing' | 'sliver' | null;

function area(points: AreaPoint[]): number {
  let sum = 0;
  points.forEach((p, i) => {
    const q = points[(i + 1) % points.length];
    sum += p.x * q.y - q.x * p.y;
  });
  return Math.abs(sum) / 2;
}

function orient(a: AreaPoint, b: AreaPoint, c: AreaPoint): number {
  return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
}

/** Do the two segments cross properly (not merely share an end)? */
function segmentsCross(a: AreaPoint, b: AreaPoint, c: AreaPoint, d: AreaPoint): boolean {
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

function crosses(points: AreaPoint[]): boolean {
  const n = points.length;
  for (let i = 0; i < n; i += 1) {
    for (let j = i + 1; j < n; j += 1) {
      if (j === i + 1 || (i === 0 && j === n - 1)) continue;   // neighbours
      if (segmentsCross(points[i], points[(i + 1) % n], points[j], points[(j + 1) % n])) {
        return true;
      }
    }
  }
  return false;
}

/** What is wrong with the shape, or null. Order is the order a person fixes
 *  them in: enough points first. */
export function shapeProblem(points: AreaPoint[]): Shape {
  if (points.length < 3) return 'few';
  if (crosses(points)) return 'crossing';
  if (area(points) < MIN_AREA_FRACTION) return 'sliver';
  return null;
}

/** The fields every area has. The page adds its own (alert timing for a zone,
 *  assignee and limit for a station) through `children` and says whether they
 *  are complete through `extraReady`. */
export interface AreaBase {
  name: string;
  cameraId: string;
  polygon: AreaPoint[];
  watched: WatchedHours;
  notifyInApp: boolean;
  notifyEmail: boolean;
}

const ZONE_HOURS: WatchedMode[] = ['always', 'outsideWorking', 'custom'];
const STATION_HOURS: WatchedMode[] = ['working', 'custom'];

/** Draw, name and save one area on a camera.
 *
 *  Shared by Zones and Stations, so the two cannot drift. The picture is live
 *  but carries **no recognition boxes** (`detections={false}`): this page is
 *  about a place, and a name on a body here answers a question nobody asked.
 *
 *  A click becomes a point in fractions of the PICTURE (never pixels), so what
 *  is saved does not depend on the screen it was drawn on. Drawing is
 *  direction-independent: the picture is pinned left-to-right and the clicks
 *  are read in physical coordinates, so an Arabic interface draws the same
 *  shape. */
export function AreaEditor({
  kind,
  cameras,
  initial,
  hasHoursSettings = true,
  busy,
  error,
  extraReady = true,
  children,
  onSave,
  onCancel,
  onCameraChange,
}: {
  kind: 'zone' | 'station';
  cameras: Camera[];
  initial?: Partial<AreaBase>;
  /** Whether Settings has working hours; stated, never guessed. */
  hasHoursSettings?: boolean;
  busy: boolean;
  error: string | null;
  extraReady?: boolean;
  /** Page-specific fields, drawn under the common ones. */
  children?: ReactNode;
  onSave: (draft: AreaBase) => void;
  onCancel: () => void;
  onCameraChange?: (cameraId: string) => void;
}) {
  const t = useT();
  const [cameraId, setCameraId] = useState(initial?.cameraId ?? cameras[0]?.id ?? '');
  const [name, setName] = useState(initial?.name ?? '');
  const [points, setPoints] = useState<AreaPoint[]>(initial?.polygon ?? []);
  const [watched, setWatched] = useState<WatchedHours>(
    initial?.watched ?? { mode: kind === 'zone' ? 'always' : 'working' },
  );
  const [inApp, setInApp] = useState(initial?.notifyInApp ?? true);
  const [email, setEmail] = useState(initial?.notifyEmail ?? false);
  const [rect, setRect] = useState<PictureRect | null>(null);

  const camera = cameras.find((c) => c.id === cameraId);
  const problem = shapeProblem(points);
  const modes = kind === 'zone' ? ZONE_HOURS : STATION_HOURS;
  const customOk = watched.mode !== 'custom'
    || (!!watched.from && !!watched.to
      && (kind === 'zone' ? watched.from !== watched.to : watched.from < watched.to));
  const hasPicture = !!camera && !camera.offline && !!camera.snapshotUrl;
  const missing = useMemo(() => {
    if (!hasPicture) return t('area.editor.needPicture');
    if (!name.trim()) return t('area.editor.needName');
    if (problem === 'few') return t('area.editor.needPoints', { n: points.length });
    if (problem === 'crossing') return t('area.editor.crossing');
    if (problem === 'sliver') return t('area.editor.sliver');
    if (!customOk) {
      return t(kind === 'zone' ? 'area.editor.needHours' : 'area.editor.needHoursStation');
    }
    if (!extraReady) return t('area.editor.needExtra');
    return null;
  }, [hasPicture, name, problem, points.length, customOk, extraReady, kind, t]);

  function addPoint(event: React.MouseEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) return;
    const x = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
    const y = Math.min(1, Math.max(0, (event.clientY - box.top) / box.height));
    setPoints((p) => [...p, { x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) }]);
  }

  const line = points.map((p) => `${p.x},${p.y}`).join(' ');

  return (
    <Card>
      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 4 }}>
        {t(kind === 'zone' ? 'area.editor.zoneTitle' : 'area.editor.stationTitle')}
      </div>
      <div style={{ fontSize: 13, color: 'var(--tx2)', marginBottom: 10 }}>
        {t('area.editor.floorHint')}
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <Field label={t('area.editor.camera')}>
          <Select
            value={cameraId}
            onChange={(id) => {
              setCameraId(id);
              setPoints([]);
              onCameraChange?.(id);
            }}
            options={cameras.map((c) => c.id)}
            label={(id) => cameras.find((c) => c.id === id)?.name ?? id}
          />
        </Field>
        <Field label={t('area.editor.name')}>
          <input
            className="input"
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            placeholder={t(kind === 'zone' ? 'area.editor.zoneNamePlaceholder'
              : 'area.editor.stationNamePlaceholder')}
          />
        </Field>
      </div>

      {camera && hasPicture ? (
        <div style={{ position: 'relative' }} dir="ltr">
          <CameraFrame camera={withoutZone(camera)} size="lg" live detections={false} badge={null}
            onPicture={setRect} />
          {rect && (
            <div
              role="presentation"
              onClick={addPoint}
              data-testid="area-click-layer"
              style={{
                position: 'absolute',
                left: rect.left,
                top: rect.top,
                width: rect.width,
                height: rect.height,
                cursor: 'crosshair',
              }}
            >
              <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true"
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%',
                  pointerEvents: 'none' }}>
                {points.length >= 3 && (
                  <polygon points={line} fill="var(--ac2)" fillOpacity={0.18}
                    stroke={problem ? 'var(--rd)' : 'var(--ac2)'} strokeWidth={2}
                    vectorEffect="non-scaling-stroke" />
                )}
                {points.length === 2 && (
                  <polyline points={line} fill="none" stroke="var(--ac2)" strokeWidth={2}
                    vectorEffect="non-scaling-stroke" />
                )}
              </svg>
              {points.map((p, i) => (
                <span
                  key={`${p.x}-${p.y}-${i}`}
                  style={{
                    position: 'absolute',
                    left: `${p.x * 100}%`,
                    top: `${p.y * 100}%`,
                    width: 10,
                    height: 10,
                    marginLeft: -5,
                    marginTop: -5,
                    borderRadius: '50%',
                    background: 'var(--ac2)',
                    border: '2px solid #fff',
                    pointerEvents: 'none',
                  }}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="empty">{t('area.editor.needPicture')}</div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '8px 0', flexWrap: 'wrap' }}>
        <button type="button" className="chip-btn chip-btn--off" disabled={points.length === 0}
          onClick={() => setPoints((p) => p.slice(0, -1))}>
          {t('area.editor.undo')}
        </button>
        <button type="button" className="chip-btn chip-btn--off" disabled={points.length === 0}
          onClick={() => setPoints([])}>
          {t('area.editor.clear')}
        </button>
        <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
          {t('area.editor.pointCount', { n: points.length })}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <Field label={t('area.editor.hours')}>
          <Select
            value={watched.mode}
            onChange={(mode) => setWatched({ mode: mode as WatchedMode,
              from: watched.from, to: watched.to })}
            options={modes}
            label={(m) => t(`area.hours.${m}` as 'area.hours.always')}
          />
        </Field>
        {watched.mode === 'custom' && (
          <>
            <Field label={t('area.editor.from')}>
              <input className="input" type="time" value={watched.from ?? ''}
                onChange={(e) => setWatched({ ...watched, from: e.target.value })} />
            </Field>
            <Field label={t('area.editor.to')}>
              <input className="input" type="time" value={watched.to ?? ''}
                onChange={(e) => setWatched({ ...watched, to: e.target.value })} />
            </Field>
          </>
        )}
      </div>
      {!hasHoursSettings && watched.mode !== 'custom' && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', marginBottom: 8 }}>
          {t('area.editor.noWorkingHours')}
        </div>
      )}

      {children}

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>
          {t('area.editor.notify')}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" aria-pressed={inApp}
            className={`chip-btn ${inApp ? 'chip-btn--on' : 'chip-btn--off'}`}
            onClick={() => setInApp(!inApp)}>
            {t('area.editor.notifyInApp')}
          </button>
          <button type="button" aria-pressed={email}
            className={`chip-btn ${email ? 'chip-btn--on' : 'chip-btn--off'}`}
            onClick={() => setEmail(!email)}>
            {t('area.editor.notifyEmail')}
          </button>
        </div>
        <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 4 }}>
          {t('area.editor.recipientsNote')}
        </div>
      </div>

      {error && <div role="alert" style={{ color: 'var(--rd)', fontSize: 13, marginBottom: 8 }}>{error}</div>}
      {missing && <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 8 }}>{missing}</div>}

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="button"
          className="chip-btn chip-btn--on"
          disabled={busy || missing !== null}
          onClick={() => onSave({
            name: name.trim(), cameraId, polygon: points, watched,
            notifyInApp: inApp, notifyEmail: email,
          })}
        >
          {t('area.editor.save')}
        </button>
        <button type="button" className="chip-btn chip-btn--off" disabled={busy} onClick={onCancel}>
          {t('area.editor.cancel')}
        </button>
      </div>
    </Card>
  );
}
