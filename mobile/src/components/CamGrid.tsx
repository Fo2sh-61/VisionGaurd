import { useState } from 'react';
import type { Camera } from '@/types';
import { CameraFrame } from './CameraFrame';
import { CameraModal } from './CameraModal';

export function CamGrid({ title, note, cameras }: { title: string; note?: string; cameras: Camera[] }) {
  const [open, setOpen] = useState<Camera | null>(null);

  return (
    <div>
      {title && <div style={{ fontWeight: 700, fontSize: 14.5 }}>{title}</div>}
      {note && <div style={{ fontSize: 11.5, color: 'var(--tx3)', marginTop: 2 }}>{note}</div>}

      <div className="camgrid">
        {cameras.map((cam) => (
          <button type="button" key={cam.id} className="camcard" onClick={() => setOpen(cam)}>
            <CameraFrame camera={cam} />
            <div className="camcard__meta">
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--tx)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {cam.name}
              </div>
              <div style={{ fontSize: 11, color: 'var(--tx2)', marginTop: 1 }}>{cam.status}</div>
            </div>
          </button>
        ))}
      </div>

      {open && <CameraModal camera={open} onClose={() => setOpen(null)} />}
    </div>
  );
}
