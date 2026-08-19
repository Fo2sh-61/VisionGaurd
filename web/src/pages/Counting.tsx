import { useCallback, useEffect, useState } from 'react';
import { useAutoRun } from '@/app/useAutoRun';
import { CameraFrame } from '@/components/CameraFrame';
import { Card, CardHeader, DataNotice, Empty, Field, PageHeader, Select, Stats } from '@/components/ui';
import { getCount } from '@/services/api';
import { useChoice, usePlaces } from '@/app/useOptions';
import type { CountArea, CountResult, CountWindow, Tone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

const WINDOWS: CountWindow[] = ['Right now', 'Today by hour', 'This week by day'];

/** Colours for the per-area segments of a stacked bar. Distinct hues, not a
 *  gradient of one — these identify places, they do not rank them. */
const SEGMENT = ['#33705b', '#5b9bd8', '#8a6a14', '#a5372c', '#6b5b95', '#3e8c8c'];

export function Counting() {
  const capability = useCapability('count');
  const places = usePlaces();
  const [place, setPlace] = useState('');
  // Hold a valid choice while the options are still arriving.
  const selectedPlace = useChoice(places, place);
  const [when, setWhen] = useState<CountWindow>('Right now');
  const [result, setResult] = useState<CountResult | null>(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setResult(await getCount({ place: selectedPlace, when }));
    } finally {
      setLoading(false);
    }
  }, [selectedPlace, when]);

  useAutoRun(run);

  /* Keep the number moving.
   *
   *  "Right now" is a live measurement, so a figure that froze the moment you
   *  pressed Show is stale the second after. The camera tile beside it already
   *  updates every second, and a headline that disagrees with the picture
   *  under it is worse than no headline. The historical windows are a query,
   *  not a measurement, so they are left alone. */
  useEffect(() => {
    if (when !== 'Right now') return;
    let alive = true;
    const tick = () => {
      void getCount({ place: selectedPlace, when })
        .then((next) => { if (alive) setResult(next); })
        .catch(() => { /* a dropped poll should not blank the page */ });
    };
    const id = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(id); };
  }, [selectedPlace, when]);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="People counting"
        lead="How many people are in a place, now or at any past time."
      />

      <Card tight>
        <div className="filters">
          <Field label="Place">
            <Select value={selectedPlace} onChange={setPlace} options={places} />
          </Field>
          <Field label="When">
            <Select value={when} onChange={(v) => setWhen(v as CountWindow)} options={WINDOWS} />
          </Field>
          <button type="button" className="btn" onClick={() => void run()} disabled={loading}>
            {loading ? 'Counting…' : 'Show'}
          </button>
        </div>
      </Card>

      {!result && !loading && <Empty>Pick a place and a time range.</Empty>}

      {result && (
        <>
          <Card>
            <CardHeader title={result.heading} sub={result.sub} />
            <Stats items={result.stats} />

            <div className="section-title" style={{ marginTop: 22, marginBottom: 12 }}>
              Where those people are right now
            </div>
            <CampusPlan areas={result.areas} />

            {result.bars && (
              <>
                <div className="section-title" style={{ marginTop: 22, marginBottom: 4 }}>
                  {result.barsTitle}
                </div>
                {/* Every bar is split by area, because "320 at 9:00" says
                    nothing on a site with six places. Demo areas are hatched
                    so a measured segment is never confused with an invented
                    one sitting next to it in the same bar. */}
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 12 }}>
                  Each bar is split by area. Hover a segment for its number.
                </div>
                {result.bars.length === 0 ? (
                  <Empty>
                    Nothing recorded yet — headcount history starts from the moment the engine
                    began running, so this fills in as the day goes on.
                  </Empty>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {result.bars.map((bar) => (
                      <div key={bar.label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span style={{ width: 62, fontSize: 13, color: 'var(--tx2)', flexShrink: 0 }}>
                          {bar.label}
                        </span>
                        <div className="bar-track" style={{ display: 'flex', overflow: 'hidden' }}>
                          {bar.parts.length === 0 ? (
                            <div className="bar-fill" style={{ width: `${bar.pct}%` }} />
                          ) : (
                            bar.parts.map((part, i) => (
                              <div
                                key={part.name}
                                title={`${part.name}: ${part.value}${part.live ? '' : ' (demo figure)'}`}
                                style={{
                                  width: `${(part.pct * bar.pct) / 100}%`,
                                  height: '100%',
                                  background: SEGMENT[i % SEGMENT.length],
                                  opacity: part.live ? 1 : 0.45,
                                }}
                              />
                            ))
                          )}
                        </div>
                        <span style={{ width: 44, textAlign: 'right', fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
                          {bar.value}
                        </span>
                      </div>
                    ))}

                    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 6, fontSize: 11.5, color: 'var(--tx2)' }}>
                      {(result.bars[0]?.parts ?? []).map((part, i) => (
                        <span key={part.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 11, height: 11, borderRadius: 3, background: SEGMENT[i % SEGMENT.length], opacity: part.live ? 1 : 0.45 }} />
                          {part.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </Card>

          {/* The live stream, not a polled thumbnail.
           *
           *  Counting shows one area at a time — a handful of cameras, not a
           *  wall of them — so each can afford the MJPEG stream and its own
           *  detection poll. That is what puts a box round every person as
           *  they move, which a static tile deliberately never does.
           *
           *  Only the cameras that actually count this area: the heading makes
           *  that claim, so the roster must not sneak in cameras from
           *  elsewhere. */}
          <Card>
            <CardHeader
              title="Cameras counting this area"
              sub="A box round every person the counter can see. This is how many are in view, not how many have passed through."
            />
            {result.cameras.length === 0 ? (
              <Empty>No camera watches this area yet, so its number is a demo figure.</Empty>
            ) : (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))',
                  gap: 12,
                }}
              >
                {result.cameras.map((c) => (
                  <div key={c.id}>
                    <CameraFrame camera={c} size="lg" live feature="counting" />
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
                      <span style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</span>
                      <span style={{ fontSize: 13, color: 'var(--tx2)' }}>{c.status}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}

const TONE_BORDER: Record<Tone, string> = {
  good: 'var(--ac)',
  warn: 'var(--am)',
  bad: 'var(--rd)',
  neutral: 'var(--tx3)',
};
const TONE_FILL: Record<Tone, string> = {
  good: 'var(--chip)',
  warn: 'var(--am-bg)',
  bad: 'var(--rd-bg)',
  neutral: 'var(--bg)',
};
const TONE_TEXT: Record<Tone, string> = {
  good: 'var(--ac2)',
  warn: 'var(--am)',
  bad: 'var(--rd)',
  neutral: 'var(--tx2)',
};

/** The campus floor-plan plus the same numbers as a list — the plan gives you
 *  "where", the list gives you "how full", and they never disagree because
 *  both read the same areas. */
function CampusPlan({ areas }: { areas: CountArea[] }) {
  return (
    <div className="plan">
      <div style={{ background: 'var(--bg)', borderRadius: 12, padding: 14 }}>
        <div style={{ position: 'relative', width: '100%', paddingTop: '66%' }}>
          <div style={{ position: 'absolute', inset: 0 }}>
            {areas.map((a) => (
              <div
                key={a.name}
                style={{
                  position: 'absolute',
                  left: `${a.x}%`,
                  top: `${a.y}%`,
                  width: `${a.w}%`,
                  height: `${a.h}%`,
                  borderRadius: 8,
                  // A demo figure is drawn dashed and faded. Real and invented
                  // numbers side by side with nothing to tell them apart is
                  // exactly what made this console untrustworthy before.
                  border: `1.5px ${a.live ? 'solid' : 'dashed'} ${TONE_BORDER[a.tone]}`,
                  background: TONE_FILL[a.tone],
                  opacity: a.live ? 1 : 0.55,
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1,
                  padding: 4,
                  boxSizing: 'border-box',
                }}
              >
                <span style={{ fontSize: 16, fontWeight: 700, color: TONE_TEXT[a.tone], lineHeight: 1 }}>
                  {a.value}
                </span>
                <span
                  style={{
                    fontSize: 9.5,
                    fontWeight: 600,
                    color: TONE_TEXT[a.tone],
                    textAlign: 'center',
                    lineHeight: 1.15,
                  }}
                >
                  {a.name}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: 14,
            flexWrap: 'wrap',
            marginTop: 12,
            fontSize: 11.5,
            color: 'var(--tx2)',
          }}
        >
          <PlanKey tone="good" label="Quiet" />
          <PlanKey tone="warn" label="Busy" />
          <PlanKey tone="bad" label="Over comfortable capacity" />
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, border: '1.5px dashed var(--tx3)' }} />
            Demo figure — no camera watches this area yet
          </span>
        </div>
      </div>

      <div>
        {areas.map((a) => (
          <div
            key={a.name}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              padding: '9px 0',
              borderBottom: '1px solid var(--line)',
            }}
          >
            <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 600 }}>
              {a.name}
              {!a.live && (
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--am)', marginLeft: 8 }}>
                  demo figure
                </span>
              )}
            </span>
            <div className="bar-track" style={{ flex: 'none', width: 96, height: 8 }}>
              <div className="bar-fill" style={{ width: `${a.pct}%`, background: TONE_BORDER[a.tone] }} />
            </div>
            <span style={{ width: 36, textAlign: 'right', fontSize: 13.5, fontWeight: 700, flexShrink: 0 }}>
              {a.value}
            </span>
          </div>
        ))}
        <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 12, lineHeight: 1.45 }}>
          Counts are how many people the cameras covering each area can see right now. Areas with
          more than one camera are added together — a person standing where two cameras overlap is
          counted twice, so treat those areas as an upper bound.
        </div>
      </div>
    </div>
  );
}

function PlanKey({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span
        style={{
          width: 11,
          height: 11,
          borderRadius: 3,
          border: `1.5px solid ${TONE_BORDER[tone]}`,
          background: TONE_FILL[tone],
        }}
      />
      {label}
    </span>
  );
}
