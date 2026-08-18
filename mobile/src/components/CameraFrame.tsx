import type { BoxColor, Camera } from '@/types';

const BOX_COLOR: Record<BoxColor, string> = {
  green: 'var(--det-green)',
  red: 'var(--det-red)',
  blue: 'var(--det-blue)',
  amber: 'var(--det-amber)',
};

/** The synthetic camera view — same visual language as the web console: a
 *  dark room plus whatever the AI drew on it, no video, and offline cameras
 *  say so instead of freezing on a fake "live" frame. */
export function CameraFrame({ camera, height = 120 }: { camera: Camera; height?: number }) {
  const zone = camera.zone;
  const zoneLabelInside = zone ? zone.y < 24 : false;

  return (
    <div className="camframe" style={{ height }}>
      <div className="camframe__grid" style={{ backgroundSize: '24px 24px' }} />
      <div className="camframe__floor" />

      {zone && (
        <div
          className="camframe__zone"
          style={{ left: `${zone.x}%`, top: `${zone.y}%`, width: `${zone.w}%`, height: `${zone.h}%` }}
        >
          <span
            className="camframe__zonelabel"
            style={{
              top: zoneLabelInside ? 3 : -18,
              left: zoneLabelInside ? 3 : -2,
              fontSize: 9.5,
              padding: '1px 6px',
            }}
          >
            {zone.label}
          </span>
        </div>
      )}

      {camera.countLine !== undefined && (
        <div className="camframe__countline" style={{ top: `${camera.countLine}%` }} />
      )}

      {(camera.boxes ?? []).map((b, i) => (
        <div
          key={i}
          className="camframe__box"
          style={{
            left: `${b.x}%`,
            top: `${b.y}%`,
            width: `${b.w}%`,
            height: `${b.h}%`,
            border: `2px solid ${BOX_COLOR[b.color]}`,
          }}
        >
          {b.label && (
            <span className="camframe__label" style={{ top: -17, fontSize: 9.5, padding: '1px 6px', background: BOX_COLOR[b.color] }}>
              {b.label}
            </span>
          )}
        </div>
      ))}

      {!camera.offline && (
        <div className="camframe__live" style={{ top: 8, left: 9, fontSize: 10 }}>
          <span className="dot" style={{ width: 6, height: 6 }} />
          LIVE
        </div>
      )}

      {camera.offline && (
        <div className="camframe__nosignal">
          <span style={{ color: '#aab5ac', fontSize: 11, fontWeight: 700, letterSpacing: '.05em' }}>NO SIGNAL</span>
          <span style={{ color: '#77827a', fontSize: 10 }}>showing last received frame</span>
        </div>
      )}

      <div className="camframe__time" style={{ top: 8, right: 9, fontSize: 10 }}>
        {camera.time ?? '14:32:07'}
      </div>
    </div>
  );
}
