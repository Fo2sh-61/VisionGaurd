import { useState } from 'react';
import { CameraFrame } from '@/components/CameraFrame';
import type { PictureRect } from '@/services/frame';
import type { AreaPoint, Camera, Tone } from '@/types';

/** How each tone draws a shape. Through the same tokens as the status chips,
 *  so a polygon and the chip beside it can never disagree. */
const STROKE: Record<Tone, string> = {
  good: 'var(--ac2)',
  warn: 'var(--am)',
  bad: 'var(--rd)',
  neutral: 'var(--tx3)',
};

/** A camera's picture with one drawn area laid over it. Read-only.
 *
 *  **It never shows a name or an identity.** `detections={false}` keeps the
 *  recognition boxes - which carry names - off the picture, and the shape is
 *  coloured by the area's own state (a zone's status, a station's state), never
 *  by who is standing in it. Rule 3: each page draws its own overlay.
 *
 *  The shape is in fractions of the frame (`viewBox="0 0 1 1"`) and is laid
 *  inside the PICTURE rectangle `CameraFrame` reports, not inside the tile:
 *  the two are rarely the same shape and reading one as the other is what once
 *  put boxes beside people. */
export function AreaPicture({
  camera,
  polygon,
  tone,
  size = 'sm',
}: {
  camera: Camera;
  polygon: AreaPoint[];
  tone: Tone;
  size?: 'sm' | 'lg';
}) {
  const [rect, setRect] = useState<PictureRect | null>(null);
  const points = polygon.map((p) => `${p.x},${p.y}`).join(' ');
  return (
    <div style={{ position: 'relative' }} dir="ltr">
      <CameraFrame
        camera={camera}
        size={size}
        detections={false}
        badge={null}
        onPicture={setRect}
      />
      {rect && polygon.length >= 3 && (
        <svg
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: rect.left,
            top: rect.top,
            width: rect.width,
            height: rect.height,
            pointerEvents: 'none',
          }}
        >
          <polygon
            points={points}
            fill={STROKE[tone]}
            fillOpacity={0.18}
            stroke={STROKE[tone]}
            strokeWidth={2}
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      )}
    </div>
  );
}
