import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAutoRun } from '@/app/useAutoRun';
import { CamGrid } from '@/components/CamGrid';
import { Card, CardHeader, DataNotice, Empty, Field, PageHeader, Select, Stats } from '@/components/ui';
import { getCount } from '@/services/api';
import { useChoice, usePlaces } from '@/app/useOptions';
import type { CountArea, CountResult, CountWindow, Tone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

const WINDOWS: CountWindow[] = ['Right now', 'Today by hour', 'This week by day'];

/* `CountWindow` is still an English label because `/count?when=` takes one —
   the same disease the intrusion and weapons windows were cured of on
   28 Aug 2026, in the one place that also needs `MockStore` to change. Until
   then the value stays English on the wire and only the wording is looked up,
   so an Arabic reader sees Arabic and the engine still understands. */
const WINDOW_KEY: Record<CountWindow, MessageKey> = {
  'Right now': 'counting.window.now',
  'Today by hour': 'counting.window.todayByHour',
  'This week by day': 'counting.window.weekByDay',
};

/** Colours for the per-area segments of a stacked bar. Distinct hues, not a
 *  gradient of one — these identify places, they do not rank them. */
const SEGMENT = ['#33705b', '#5b9bd8', '#8a6a14', '#a5372c', '#6b5b95', '#3e8c8c'];

export function Counting() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('count');
  const places = usePlaces();
  // `?place=Main entrance` from Ask. See Attendance for why.
  const [params] = useSearchParams();
  const [place, setPlace] = useState(params.get('place') ?? '');
  // Hold a valid choice while the options are still arriving.
  const selectedPlace = useChoice(places, place);
  const askedWhen = params.get('when');
  const [when, setWhen] = useState<CountWindow>(
    askedWhen === 'Today by hour' || askedWhen === 'This week by day'
      ? askedWhen
      : 'Right now');
  const [result, setResult] = useState<CountResult | null>(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setResult(await getCount({ place: selectedPlace, when }, language));
    } finally {
      setLoading(false);
    }
  }, [selectedPlace, when, language]);

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
      void getCount({ place: selectedPlace, when }, language)
        .then((next) => { if (alive) setResult(next); })
        .catch(() => { /* a dropped poll should not blank the page */ });
    };
    const id = window.setInterval(tick, 1000);
    return () => { alive = false; window.clearInterval(id); };
  }, [selectedPlace, when, language]);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title={t('counting.title')}
        lead={t('counting.lead')}
      />

      <Card tight>
        <div className="filters">
          <Field label={t('counting.place')}>
            <Select value={selectedPlace} onChange={setPlace} options={places} />
          </Field>
          <Field label={t('counting.when')}>
            <Select
              value={when}
              onChange={(v) => setWhen(v as CountWindow)}
              options={WINDOWS}
              label={(o) => t(WINDOW_KEY[o as CountWindow])}
            />
          </Field>
          <button type="button" className="btn" onClick={() => void run()} disabled={loading}>
            {t(loading ? 'counting.counting' : 'counting.show')}
          </button>
        </div>
      </Card>

      {!result && !loading && <Empty>{t('counting.pickPlace')}</Empty>}

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
                        <span style={{ width: 44, textAlign: 'end', fontSize: 13, fontWeight: 600, flexShrink: 0 }}>
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

          {/* Tiles you can open, not a wall of streams.
           *
           *  This page used to hold an MJPEG stream open for every camera at
           *  once, each with its own ten-per-second detection poll. With the
           *  default place — "All places", which is every enabled camera —
           *  those held connections used up the handful the browser allows per
           *  origin, and the cameras that lost the race never painted a frame.
           *  `CamGrid` polls snapshots for the tiles and keeps the stream for
           *  the one camera you open, which is also what makes a tile here
           *  clickable at all.
           *
           *  `feature` follows it into the enlarged view. Counting asks how
           *  many bodies are in shot; without it the opened camera would answer
           *  a different question and draw faces with names on a headcount.
           *
           *  Only the cameras that actually count this area: the heading makes
           *  that claim, so `only` keeps the full roster from sneaking in. */}
          {result.cameras.length === 0 ? (
            <Card>
              <CardHeader
                title={t('counting.camerasHere')}
                sub={t('counting.camerasHereNote')}
              />
              <Empty>{t('counting.noCameraHere')}</Empty>
            </Card>
          ) : (
            <CamGrid
              title={t('counting.camerasHere')}
              note={t('counting.camerasHereNoteClick')}
              cameras={result.cameras}
              only
              feature="counting"
            />
          )}
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
  const t = useT();
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
          <PlanKey tone="good" label={t('counting.quiet')} />
          <PlanKey tone="warn" label={t('counting.busy')} />
          <PlanKey tone="bad" label={t('counting.overCapacity')} />
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, border: '1.5px dashed var(--tx3)' }} />
            {t('counting.demoFigure')}
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
                <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--am)', marginInlineStart: 8 }}>
                  demo figure
                </span>
              )}
            </span>
            <div className="bar-track" style={{ flex: 'none', width: 96, height: 8 }}>
              <div className="bar-fill" style={{ width: `${a.pct}%`, background: TONE_BORDER[a.tone] }} />
            </div>
            <span style={{ width: 36, textAlign: 'end', fontSize: 13.5, fontWeight: 700, flexShrink: 0 }}>
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
