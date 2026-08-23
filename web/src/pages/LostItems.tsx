/** Lost bag — tick the cameras, pick a colour, watch.
 *
 *  There is no Search button and no result, because there is no search. The
 *  cameras you tick appear below, live, and a box is drawn round any bag of the
 *  colour you picked for as long as you are looking at them. Leaving the page
 *  stops the work; nothing has to be switched off.
 *
 *  It answers one question — *is my bag on any of these cameras right now* —
 *  and the answer is the picture, not a list beside it.
 *
 *  **Nothing is recorded.** No clip, no still, no history. A bag that was taken
 *  before you opened this page cannot be found here, and the page must never
 *  imply otherwise.
 *
 *  **A box is a possible bag, never a found one.** Measured on footage with no
 *  bag in it (research D10), this model draws a `suitcase` box on a black
 *  office chair at up to 0.88 and holds it there. That is why the box is amber,
 *  labelled with what the model thinks it is, and drawn over a live picture the
 *  operator can judge for themselves.
 */

import { useMemo, useState } from 'react';
import { useCameras } from '@/app/CameraContext';
import { useCapability } from '@/app/CapabilityContext';
import { CamGrid } from '@/components/CamGrid';
import { Card, DataNotice, Empty, PageHeader } from '@/components/ui';

const UNASSIGNED = 'Unassigned';

/** The colour palette, and the only names the engine accepts.
 *
 *  Grey and white are one chip on purpose. They differ only in lightness, and
 *  lightness is exactly what lighting changes — a white bag in shadow is grey
 *  to the camera, and no measurement fixes that without knowing the light
 *  (research D3). A distinction the camera cannot make must not be offered as
 *  a choice. `Any` is a gradient because it is not a colour: it is the absence
 *  of a filter, and a flat grey chip would read as "grey".
 */
const COLOURS: { name: string; value?: string; dot: string }[] = [
  { name: 'Any', dot: 'linear-gradient(135deg,#d7ded9,#8d9a95)' },
  { name: 'Black', value: 'black', dot: '#2b2f2c' },
  { name: 'Grey or white', value: 'light', dot: 'linear-gradient(135deg,#f2f4f3,#9aa3a0)' },
  { name: 'Red', value: 'red', dot: '#c0483f' },
  { name: 'Blue', value: 'blue', dot: '#3f6fb5' },
  { name: 'Green', value: 'green', dot: '#3e8c5c' },
  { name: 'Yellow', value: 'yellow', dot: '#d8b038' },
];

function chipStyle(on: boolean) {
  return {
    padding: '9px 16px',
    borderRadius: 10,
    fontSize: 13.5,
    fontWeight: 600,
    cursor: 'pointer',
    background: on ? 'var(--ac)' : 'var(--bg)',
    color: on ? '#fff' : 'var(--tx2)',
    border: `1px solid ${on ? 'var(--ac)' : 'var(--line)'}`,
  } as const;
}

const labelStyle = {
  fontSize: 12.5,
  fontWeight: 600,
  color: 'var(--tx2)',
  marginBottom: 9,
} as const;

export function LostItems() {
  const capability = useCapability('search_lost');
  // The live roster, which is where areas actually live. The engine is never
  // asked what an area contains — it already sent the answer with the cameras.
  const { cameras } = useCameras();

  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [openAreas, setOpenAreas] = useState<Set<string>>(new Set());
  const [colour, setColour] = useState<string | undefined>(undefined);

  /** Areas in roster order, each with its cameras. `Unassigned` is a real
   *  group, not a leftover: today it is almost every camera, and hiding them
   *  would hide the whole school. */
  const areas = useMemo(() => {
    const groups: { name: string; cameras: typeof cameras }[] = [];
    for (const cam of cameras) {
      const name = cam.area || UNASSIGNED;
      const found = groups.find((g) => g.name === name);
      if (found) found.cameras.push(cam);
      else groups.push({ name, cameras: [cam] });
    }
    return groups;
  }, [cameras]);

  const watching = useMemo(
    () => cameras.filter((c) => ticked.has(c.id)),
    [cameras, ticked],
  );

  const toggleCamera = (id: string) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleArea = (name: string) => {
    const ids = areas.find((a) => a.name === name)?.cameras.map((c) => c.id) ?? [];
    setTicked((prev) => {
      const next = new Set(prev);
      const all = ids.every((id) => next.has(id));
      for (const id of ids) {
        if (all) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  };

  const chosen = COLOURS.find((c) => c.value === colour) ?? COLOURS[0];
  const offline = watching.filter((c) => c.offline);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Lost bag"
        lead="Tick the cameras to watch and pick a colour. Any bag of that colour is outlined as it is seen. Nothing is recorded, so the bag has to still be there."
      />

      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <div style={labelStyle}>Where to watch</div>
            {areas.length === 0 ? (
              <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
                There are no cameras on this engine, so there is nothing to watch.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {areas.map((area) => {
                  const ids = area.cameras.map((c) => c.id);
                  const on = ids.filter((id) => ticked.has(id)).length;
                  const open = openAreas.has(area.name);
                  return (
                    <div key={area.name}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
                        <input
                          type="checkbox"
                          checked={on > 0 && on === ids.length}
                          // Some but not all: the box says "partly", which is
                          // the truth and is not a state a checkbox has
                          // without being told.
                          ref={(el) => {
                            if (el) el.indeterminate = on > 0 && on < ids.length;
                          }}
                          onChange={() => toggleArea(area.name)}
                          aria-label={`Watch every camera in ${area.name}`}
                        />
                        <button
                          type="button"
                          className="linkbtn"
                          onClick={() =>
                            setOpenAreas((prev) => {
                              const next = new Set(prev);
                              if (next.has(area.name)) next.delete(area.name);
                              else next.add(area.name);
                              return next;
                            })
                          }
                          style={{ fontWeight: 600, fontSize: 13.5 }}
                        >
                          {open ? '▾' : '▸'} {area.name}
                        </button>
                        <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                          {on > 0
                            ? `${on} of ${ids.length}`
                            : `${ids.length} camera${ids.length === 1 ? '' : 's'}`}
                        </span>
                      </div>
                      {open && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingLeft: 26 }}>
                          {area.cameras.map((cam) => (
                            <label
                              key={cam.id}
                              style={{
                                display: 'flex', alignItems: 'center', gap: 10,
                                padding: '4px 0', fontSize: 13, cursor: 'pointer',
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={ticked.has(cam.id)}
                                onChange={() => toggleCamera(cam.id)}
                              />
                              <span style={{ color: 'var(--tx2)' }}>{cam.name}</span>
                              {cam.offline && (
                                <span style={{ fontSize: 11.5, color: 'var(--tx3)' }}>offline</span>
                              )}
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div>
            <div style={labelStyle}>Colour</div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {COLOURS.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  style={{
                    ...chipStyle(colour === c.value),
                    display: 'flex', alignItems: 'center', gap: 8, padding: '8px 15px',
                  }}
                  onClick={() => setColour(c.value)}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      width: 13, height: 13, borderRadius: '50%', flexShrink: 0,
                      background: c.dot, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.18)',
                    }}
                  />
                  {c.name}
                </button>
              ))}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 8 }}>
              Colour is judged from the camera picture and can be wrong in poor light.
              Pick Any if the bag is not outlined.
            </div>
          </div>
        </div>
      </Card>

      {watching.length === 0 ? (
        <Card>
          <Empty>
            Nothing ticked yet. Tick an area or a camera above and it appears
            below, live, with any {colour ? chosen.name.toLowerCase() : ''} bag
            outlined in amber.
          </Empty>
        </Card>
      ) : (
        <>
          {offline.length > 0 && (
            <Card>
              <div style={{ fontSize: 13, color: 'var(--tx3)' }}>
                {offline.map((c) => c.name).join(', ')}
                {offline.length === 1 ? ' is offline' : ' are offline'}, so nothing
                can be checked on {offline.length === 1 ? 'it' : 'them'}.
              </div>
            </Card>
          )}
          <CamGrid
            title="Watching now"
            note={
              (colour
                ? `A bag that could be ${chosen.name.toLowerCase()} is outlined in amber as it is seen.`
                : 'Any bag is outlined in amber as it is seen.') +
              ' A box means the model thinks it sees a bag, not that one is there — open a camera to look.'
            }
            cameras={watching}
            only
            searchable={watching.length > 12}
            pageSize={12}
            feature="lost"
            colour={colour}
            tileOverlay
          />
        </>
      )}
    </>
  );
}
