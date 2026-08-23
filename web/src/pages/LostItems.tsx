/** Lost bag — looking at the cameras you tick, right now, for up to a minute.
 *
 *  **This does not search footage.** Nothing is recorded, so there is nothing
 *  to search: the engine looks at the live pictures from the cameras chosen
 *  here and stops after sixty seconds. The page it replaced offered a bag type,
 *  a "missing since" period and a ranked list with *Watch clip* buttons — every
 *  one of which promised a recording that does not exist.
 *
 *  Three things carried over from the redesign, and they are the reason the
 *  form still looks like a form:
 *
 *  1. **The query is readable before it runs.** A summary line spells the
 *     search back in words, so the operator sees what they are about to ask
 *     rather than assembling it from four controls in their head.
 *
 *  2. **Any change to the query invalidates the answer on screen.** Old hits
 *     under a changed search is how somebody collects the wrong bag.
 *
 *  3. **A camera that saw a bag comes to the front of the grid, marked.** The
 *     answer is *which camera to walk to*, so the grid is the result — not a
 *     list beside it.
 *
 *  What the page must never say is that a bag *has been found*. The model is
 *  measurably wrong on ordinary furniture (research D10), so every hit is a
 *  possible bag for a person to look at, and the wording here is the only
 *  place that distinction is made.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useCameras } from '@/app/CameraContext';
import { useCapability } from '@/app/CapabilityContext';
import { CamGrid } from '@/components/CamGrid';
import { Card, DataNotice, Empty, PageHeader } from '@/components/ui';
import { getLostSearch, searchLostItem, stopLostSearch } from '@/services/api';
import type { LostResult } from '@/types';

type Phase = 'idle' | 'running' | 'done' | 'stopped' | 'failed';

const UNASSIGNED = 'Unassigned';

/** How often the page asks how the search is getting on. */
const POLL_MS = 1_000;

/** The colour palette, and the only names the engine accepts.
 *
 *  Grey and white are one chip on purpose. They differ only in lightness, and
 *  lightness is exactly what lighting changes — a white bag in shadow is grey
 *  to the camera and no measurement fixes that without knowing the light
 *  (research D3). Offering them separately would be offering a distinction the
 *  camera cannot make. `Any` is a gradient because it is not a colour: it is
 *  the absence of a filter, and a flat grey chip would read as "grey".
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

  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<LostResult | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  /** Any change to the query invalidates the answer on screen. */
  const invalidate = useCallback(() => {
    setPhase('idle');
    setResult(null);
    setError(null);
  }, []);

  const toggleCamera = (id: string) => {
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    invalidate();
  };

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
    invalidate();
  };

  const run = useCallback(async () => {
    setPhase('running');
    setResult(null);
    setError(null);
    try {
      const started = await searchLostItem({ cameras: [...ticked], colour });
      setResult(started);
      // The engine can refuse before any thread starts — no camera chosen, or
      // none of the chosen ones reachable. That is payload, not an exception,
      // and the page has to notice it rather than poll forever.
      if (started.state !== 'running') setPhase(started.state as Phase);
    } catch (caught) {
      // Without this the throw escaped and the page sat on "Searching…"
      // indefinitely. "We could not search" and "we searched and found
      // nothing" are different answers, and only one of them should stop
      // somebody looking for a child's missing bag.
      setError(caught instanceof Error ? caught.message : 'The search could not be run.');
      setPhase('failed');
    }
  }, [ticked, colour]);

  const stop = useCallback(async () => {
    try {
      await stopLostSearch();
      const last = await getLostSearch();
      if (last) setResult(last);
      setPhase('stopped');
    } catch {
      /* the poll below will notice soon enough */
    }
  }, []);

  // Poll while it runs, and only while it runs.
  useEffect(() => {
    if (phase !== 'running') return;
    let cancelled = false;
    const timer = setInterval(() => {
      void getLostSearch()
        .then((next) => {
          if (cancelled || !next) return;
          setResult(next);
          if (next.state !== 'running') setPhase(next.state as Phase);
        })
        .catch(() => {
          /* a dropped poll leaves the previous numbers up */
        });
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [phase]);

  const chosenColour = COLOURS.find((c) => c.value === colour) ?? COLOURS[0];
  const summary =
    `${ticked.size === 0 ? 'no cameras' : `${ticked.size} camera${ticked.size === 1 ? '' : 's'}`}` +
    ` · ${colour ? chosenColour.name.toLowerCase() : 'any colour'}`;

  const hits = result?.hits ?? [];
  const status = describeSearch(phase, result, error);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Lost bag"
        lead="Tick the areas to check and press Search. The cameras are looked at live for up to a minute; nothing is recorded."
      />

      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <div style={labelStyle}>Where to look</div>
            {areas.length === 0 ? (
              <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
                There are no cameras on this engine, so there is nothing to search.
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
                          aria-label={`Search all cameras in ${area.name}`}
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
                          {on > 0 ? `${on} of ${ids.length}` : `${ids.length} camera${ids.length === 1 ? '' : 's'}`}
                        </span>
                      </div>
                      {open && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, paddingLeft: 26 }}>
                          {area.cameras.map((cam) => (
                            <label
                              key={cam.id}
                              style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '4px 0', fontSize: 13, cursor: 'pointer' }}
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
                  style={{ ...chipStyle(colour === c.value), display: 'flex', alignItems: 'center', gap: 8, padding: '8px 15px' }}
                  onClick={() => {
                    setColour(c.value);
                    invalidate();
                  }}
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
              Pick Any if the bag is not found.
            </div>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 16, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid var(--line)',
          }}>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
              Looking at <b style={{ color: 'var(--tx)', fontWeight: 600 }}>{summary}</b>
            </div>
            <button
              type="button"
              onClick={() => void (phase === 'running' ? stop() : run())}
              disabled={phase !== 'running' && ticked.size === 0}
              style={{
                height: 44, padding: '0 26px', border: 'none', borderRadius: 11,
                background: phase === 'running' ? 'var(--danger)' : 'var(--ac)',
                color: '#fff', fontWeight: 600, fontSize: 14.5,
                cursor: phase !== 'running' && ticked.size === 0 ? 'not-allowed' : 'pointer',
                opacity: phase !== 'running' && ticked.size === 0 ? 0.55 : 1,
              }}
            >
              {phase === 'running' ? 'Stop' : 'Search'}
            </button>
          </div>
        </div>
      </Card>

      {phase === 'idle' && (
        <Card>
          <Empty>
            Nothing searched yet. Tick the areas to check and press Search — the
            cameras are looked at live, so a bag has to still be there to be found.
          </Empty>
        </Card>
      )}

      {status && (
        <Card>
          <div style={{ fontSize: 13.5, color: 'var(--tx)' }}>{status}</div>
          {result && result.unavailable.length > 0 && (
            <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 8 }}>
              {result.unavailable.map((u) => (
                <div key={u.camera}>
                  {u.camera} — {u.reason}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      <CamGrid
        title="Cameras searched"
        note="Amber boxes mark a possible bag. Cameras that saw one are first."
        cameras={result?.cameras ?? []}
        only
        feature="lost"
        tileOverlay
        pinned={hits.map((h) => h.cameraId)}
      />
    </>
  );
}

/** One sentence about the search, built from the counts the engine sent.
 *
 *  Never a bare empty grid: "nothing found" and "nothing searched" look
 *  identical on screen and mean opposite things.
 */
function describeSearch(
  phase: Phase,
  result: LostResult | null,
  error: string | null,
): string | null {
  if (phase === 'failed') return error ?? result?.error ?? 'The search could not be run.';
  if (phase === 'idle' || !result) return null;

  const secs = Math.round(result.secondsElapsed);
  const limit = Math.round(result.secondsLimit);
  const checked = `${result.camerasChecked} camera${result.camerasChecked === 1 ? '' : 's'}`;
  const hidden = result.hiddenByColour
    ? ` ${result.hiddenByColour} possible bag${result.hiddenByColour === 1 ? '' : 's'} hidden by the colour filter.`
    : '';

  if (phase === 'running') {
    return `Looking at ${checked} · ${secs}s of ${limit}.${hidden}`;
  }

  const seen = result.hits.length;
  const ending = phase === 'stopped' ? `Stopped after ${secs}s.` : `Checked for ${secs} seconds.`;

  if (seen === 0) {
    return `${ending} ${checked} looked at, ${result.framesChecked} frames. No bag seen.${hidden}`;
  }
  return (
    `${ending} ${checked} looked at — a possible bag on ` +
    `${seen} of them. Open the camera to see whether it is the right one.${hidden}`
  );
}
