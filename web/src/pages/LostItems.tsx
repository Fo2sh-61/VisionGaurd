/** Lost bag — searching recorded footage for something left behind.
 *
 *  Rebuilt from design/18-8 design/VisionGuard.dc.html, which narrowed this
 *  from "lost items" to bags specifically and replaced the dropdown row with
 *  chip pickers.
 *
 *  Two things the redesign is doing, both worth keeping:
 *
 *  1. **The query is readable before it runs.** A summary line spells the
 *     search back in words — "a black backpack · cafeteria · today" — so the
 *     operator sees what they are about to ask for rather than reading four
 *     separate dropdowns and assembling it themselves.
 *
 *  2. **Results are ranked, and one can be marked as the answer.** A found bag
 *     ends the search; the clip is kept with it so the owner can be told where
 *     to collect it.
 */

import { useCallback, useState } from 'react';
import { useAutoRun } from '@/app/useAutoRun';
import { CamGrid } from '@/components/CamGrid';
import { Card, DataNotice, Empty, Field, LoadError, PageHeader, Select } from '@/components/ui';
import { searchLostItem } from '@/services/api';
import { LOST_SINCE } from '@/services/content';
import { useSite } from '@/app/SiteContext';
import type { LostResult } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

type Phase = 'idle' | 'searching' | 'done' | 'failed';

const BAGS = ['Backpack', 'Sports bag', 'Handbag', 'Laptop bag'];

/** Colour swatches. `Any` is a gradient because it is not a colour — it is the
 *  absence of a colour filter, and a flat grey chip reads as "grey". */
const COLOURS: { name: string; dot: string }[] = [
  { name: 'Black', dot: '#2b2f2c' },
  { name: 'Blue', dot: '#3f6fb5' },
  { name: 'Grey', dot: '#9aa3a0' },
  { name: 'Red', dot: '#c0483f' },
  { name: 'Green', dot: '#3e8c5c' },
  { name: 'Any', dot: 'linear-gradient(135deg,#d7ded9,#8d9a95)' },
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

export function LostItems() {
  const capability = useCapability('search_lost');
  // Areas come from the engine — they are the real camera groupings, not copy.
  const areas = useSite().site?.areas ?? [];
  const [bag, setBag] = useState(BAGS[0]);
  const [colour, setColour] = useState('Black');
  const [area, setArea] = useState('');
  const selectedArea = area || areas[0] || '';
  const [since, setSince] = useState(LOST_SINCE[0]);

  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<LostResult | null>(null);
  const [found, setFound] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** Any change to the query invalidates the answer on screen.
   *
   *  Leaving old hits under a changed search is how someone collects the wrong
   *  bag from the wrong corridor. */
  function change<T>(set: (v: T) => void) {
    return (value: T) => {
      set(value);
      setPhase('idle');
      setResult(null);
      setFound(null);
      setError(null);
    };
  }

  const run = useCallback(async () => {
    setPhase('searching');
    setResult(null);
    setFound(null);
    setError(null);
    try {
      const hits = await searchLostItem({ item: bag, colour, area: selectedArea, since });
      setResult(hits);
      setPhase('done');
    } catch (caught) {
      // Without this the throw escaped, `setPhase('done')` never ran, and the
      // page sat on "Searching…" indefinitely. Somebody looking for a child's
      // missing bag would have waited at a spinner that was never going to
      // finish. "We could not search" and "we searched and found nothing" are
      // different answers and only one of them should stop them looking.
      setError(caught instanceof Error ? caught.message : 'The search could not be run.');
      setPhase('failed');
    }
  }, [bag, colour, selectedArea, since]);

  useAutoRun(run);

  const summary =
    (colour === 'Any' ? `a ${bag.toLowerCase()}, any colour` : `a ${colour.toLowerCase()} ${bag.toLowerCase()}`) +
    ` · ${selectedArea.toLowerCase() || 'anywhere'} · ${since.toLowerCase()}`;

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Lost bag"
        lead="Say what the bag looks like and where it went missing. The system searches the recorded footage for it."
      />

      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)', marginBottom: 9 }}>
              Type of bag
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {BAGS.map((b) => (
                <button key={b} type="button" style={chipStyle(bag === b)} onClick={() => change(setBag)(b)}>
                  {b}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)', marginBottom: 9 }}>
              Colour
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {COLOURS.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  style={{ ...chipStyle(colour === c.name), display: 'flex', alignItems: 'center', gap: 8, padding: '8px 15px' }}
                  onClick={() => change(setColour)(c.name)}
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
          </div>

          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <Field label="Last seen area">
              <Select value={selectedArea} onChange={change(setArea)} options={areas} />
            </Field>
            <Field label="Missing since">
              <Select value={since} onChange={change(setSince)} options={LOST_SINCE} />
            </Field>
          </div>

          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            gap: 16, flexWrap: 'wrap', paddingTop: 16, borderTop: '1px solid var(--line)',
          }}>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
              Looking for <b style={{ color: 'var(--tx)', fontWeight: 600 }}>{summary}</b>
            </div>
            <button
              type="button"
              onClick={() => void run()}
              disabled={phase === 'searching'}
              style={{
                height: 44, padding: '0 26px', border: 'none', borderRadius: 11,
                background: 'var(--ac)', color: '#fff', fontWeight: 600, fontSize: 14.5, cursor: 'pointer',
              }}
            >
              {phase === 'searching' ? 'Searching…' : 'Search footage'}
            </button>
          </div>
        </div>
      </Card>

      {phase === 'idle' && (
        <Card>
          <div style={{ textAlign: 'center', padding: '28px 4px' }}>
            <div style={{ fontWeight: 600, fontSize: 15.5 }}>Nothing searched yet</div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 4 }}>
              Pick the bag and press Search. Footage from the last 3 days is kept, so search soon
              after it goes missing.
            </div>
          </div>
        </Card>
      )}

      {phase === 'failed' && (
        <Card>
          <LoadError error={error} onRetry={() => void run()} what="the footage search" />
          <Empty>
            Nothing was searched, so nothing here rules anything out. The bag may still be
            findable — try again, or ask someone to check the area.
          </Empty>
        </Card>
      )}

      {phase === 'searching' && (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 17 }}>Searching footage…</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '3px 0 18px' }}>
            Checking 42 cameras across the selected area and time. This usually takes under a
            minute.
          </div>
          <div className="progress">
            <div className="progress__scanner" />
          </div>
        </Card>
      )}

      {phase === 'done' && result && (
        <>
          {found && (
            <Card tight>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div style={{
                  width: 38, height: 38, borderRadius: '50%', flexShrink: 0,
                  background: 'var(--chip)', color: 'var(--ac)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 17,
                }}>
                  ✓
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 15 }}>Marked as found — {found}</div>
                  <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                    The clip is saved with the search so the owner can be told where to collect it.
                  </div>
                </div>
                <button type="button" className="chip-btn chip-btn--off" onClick={() => { setPhase('idle'); setResult(null); setFound(null); }}>
                  Done
                </button>
              </div>
            </Card>
          )}

          <Card>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>
                  {result.hits.length} possible matches
                </div>
                <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>{result.sub}</div>
              </div>
              <button type="button" className="chip-btn chip-btn--off" onClick={() => { setPhase('idle'); setResult(null); setFound(null); }}>
                Start a new search
              </button>
            </div>

            {result.hits.length === 0 && (
              <Empty>
                {result.searched
                  ? 'Searched, and nothing matching turned up. That is a real answer: the bag was not seen on these cameras in this period.'
                  : 'The footage was never searched, so this rules nothing out.'}
              </Empty>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {result.hits.map((hit, i) => {
                const tone = hit.strong ? 'var(--ac2)' : 'var(--am)';
                const isFound = found === hit.camera;
                return (
                  <div
                    key={hit.camera}
                    style={{
                      background: 'var(--bg)',
                      border: `1px solid ${isFound ? 'var(--ac)' : 'transparent'}`,
                      borderRadius: 12, padding: '15px 18px',
                      display: 'grid', gridTemplateColumns: '30px minmax(0,1.6fr) 150px auto',
                      gap: 16, alignItems: 'center',
                    }}
                  >
                    <div style={{
                      width: 30, height: 30, borderRadius: 9,
                      background: hit.strong ? 'var(--chip)' : 'var(--am-bg)', color: tone,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontWeight: 700, fontSize: 13,
                    }}>
                      #{i + 1}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 14.5 }}>{hit.camera}</div>
                      <div style={{ fontSize: 13, color: 'var(--tx2)' }}>{hit.time} · {hit.note}</div>
                    </div>
                    <div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: 'var(--tx2)', marginBottom: 5 }}>
                        <span>Match</span>
                        <span style={{ fontWeight: 700, color: tone }}>{hit.confidence}%</span>
                      </div>
                      <div style={{ height: 6, background: 'var(--card)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ height: 6, width: `${hit.confidence}%`, background: tone, borderRadius: 4 }} />
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'flex-end' }}>
                      <span style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap' }}>
                        Watch clip
                      </span>
                      {isFound ? (
                        <span style={{ color: 'var(--ac2)', fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}>✓ This one</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setFound(hit.camera)}
                          style={{ background: 'none', border: 'none', color: 'var(--tx2)', fontWeight: 600, fontSize: 13.5, cursor: 'pointer', whiteSpace: 'nowrap' }}
                        >
                          This is it
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--line)', fontSize: 13.5, color: 'var(--tx2)' }}>
              If none of these look right, widen the area or the time and search again.
            </div>
          </Card>

          <CamGrid
            title="Where the bag was seen"
            note="Best match first. The green box is the bag the system matched; amber means it is less sure."
            cameras={result.cameras}
          />
        </>
      )}
    </>
  );
}
