import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAutoRun } from '@/app/useAutoRun';
import { CamGrid } from '@/components/CamGrid';
import { Card, CardHeader, DataNotice, Empty, Field, PageHeader, Select, Stats } from '@/components/ui';
import { getCount } from '@/services/api';
import { useChoice, usePlaces } from '@/app/useOptions';
import type { CountArea, CountBar, CountResult, CountWindow, Tone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/*  People counting, laid out for a phone (spec 015, contract "People counting").
 *
 *  Built from `web/src/pages/Counting.tsx`: same call, same 1-second poll
 *  while the window is "Right now", same place/window state (including the
 *  `?place=`/`?when=` read from Ask), same empty states.
 *
 *  What changed is the arrangement. The console's `CampusPlan` is a floor-plan
 *  box per area, positioned in percentages of a drawing of the campus this
 *  phone has no room for. Here each area is a row in a list instead: same
 *  name, same value, the same bar (`area.pct`), the same tone colour, and the
 *  same dashed/amber "demo figure" marking for `live:false` — every fact the
 *  plan showed, none of the pixels it needed to show them in. */

const WINDOWS: CountWindow[] = ['Right now', 'Today by hour', 'This week by day'];

/* `CountWindow` is still an English label because `/count?when=` takes one —
   see the console's Counting.tsx for why. The value stays English on the
   wire; only the wording shown here is looked up. */
const WINDOW_KEY: Record<CountWindow, MessageKey> = {
  'Right now': 'counting.window.now',
  'Today by hour': 'counting.window.todayByHour',
  'This week by day': 'counting.window.weekByDay',
};

/** Colours for the per-area segments of a stacked bar. Distinct hues, not a
 *  gradient of one — these identify places, they do not rank them. Copied
 *  from the console so the same area reads as the same colour on both apps. */
const SEGMENT = ['#33705b', '#5b9bd8', '#8a6a14', '#a5372c', '#6b5b95', '#3e8c8c'];

const TONE_BORDER: Record<Tone, string> = {
  good: 'var(--ac)',
  warn: 'var(--am)',
  bad: 'var(--rd)',
  neutral: 'var(--tx3)',
};

export function Counting() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('count');
  const places = usePlaces();
  // `?place=Main entrance` from Ask. See the console's Attendance for why.
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
   *  pressed Show is stale the second after. The historical windows are a
   *  query, not a measurement, so they are left alone. */
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
      <PageHeader title={t('counting.title')} lead={t('counting.lead')} />

      <Card tight>
        <div className="stack">
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
          <button type="button" className="btn btn--block" onClick={() => void run()} disabled={loading}>
            {t(loading ? 'counting.counting' : 'counting.show')}
          </button>
        </div>
      </Card>

      {!result && !loading && <Empty>{t('counting.pickPlace')}</Empty>}

      {result && (
        <>
          <Card>
            {/* Heading and sub verbatim from the engine — any percentage on
                screen comes from `result.sub`, never computed here. */}
            <CardHeader title={result.heading} sub={result.sub} />
            <Stats items={result.stats} />
          </Card>

          <div className="sechead">
            <span className="sechead__title">Where those people are right now</span>
          </div>
          <AreaList areas={result.areas} />

          {result.bars && (
            <>
              <div className="sechead">
                <span className="sechead__title">{result.barsTitle}</span>
              </div>
              {/* The console says "Hover a segment for its number" — a phone
                  has no hover, so each segment's name and value are printed
                  under its bar instead of waiting for a pointer that will
                  never arrive. */}
              <p className="note" style={{ margin: '0 2px' }}>
                Each bar is split by area — its segments are listed under it.
              </p>
              {result.bars.length === 0 ? (
                <Card>
                  <Empty>
                    Nothing recorded yet — headcount history starts from the moment the engine
                    began running, so this fills in as the day goes on.
                  </Empty>
                </Card>
              ) : (
                <div className="stack">
                  {result.bars.map((bar) => (
                    <BarRow key={bar.label} bar={bar} />
                  ))}
                </div>
              )}
            </>
          )}

          {/* Tiles you can open, not a wall of streams.
           *
           *  `feature` follows a tap into the enlarged view. Counting asks how
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

/** Every area on campus, as a list row instead of a floor-plan box: name,
 *  value, a bar in the area's tone colour, and — when the figure is not
 *  measured by a camera — a dashed bar and an amber "demo figure" mark. Same
 *  facts as the console's `CampusPlan`, one column instead of a drawing. */
function AreaList({ areas }: { areas: CountArea[] }) {
  const t = useT();
  return (
    <>
      <div className="card card--flush">
        {areas.map((a, i) => (
          <div
            key={a.name}
            style={{
              padding: '12px 14px',
              borderTop: i === 0 ? undefined : '1px solid var(--line)',
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <div className="spread">
              <span style={{ fontSize: 14.5, fontWeight: 600, minWidth: 0 }}>
                {a.name}
                {!a.live && (
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--am)', marginInlineStart: 8 }}>
                    demo figure
                  </span>
                )}
              </span>
              <span style={{ fontSize: 19, fontWeight: 800, flexShrink: 0 }}>{a.value}</span>
            </div>
            <div
              className="bar-track"
              style={{
                height: 10,
                border: `1.5px ${a.live ? 'solid' : 'dashed'} ${TONE_BORDER[a.tone]}`,
                background: 'transparent',
                opacity: a.live ? 1 : 0.7,
              }}
            >
              <div className="bar-fill" style={{ width: `${a.pct}%`, background: TONE_BORDER[a.tone] }} />
            </div>
          </div>
        ))}
      </div>

      {/* The plan's legend, as text: what each tone and the dashed border
          mean. Colour alone never carries the meaning on this page. */}
      <div className="legend">
        <PlanKey tone="good" label={t('counting.quiet')} />
        <PlanKey tone="warn" label={t('counting.busy')} />
        <PlanKey tone="bad" label={t('counting.overCapacity')} />
        <span>
          <span
            className="legend__swatch"
            style={{ border: '1.5px dashed var(--tx3)', background: 'transparent' }}
          />
          {t('counting.demoFigure')}
        </span>
      </div>

      <p className="note" style={{ margin: '0 2px' }}>
        Counts are how many people the cameras covering each area can see right now. Areas with
        more than one camera are added together — a person standing where two cameras overlap is
        counted twice, so treat those areas as an upper bound.
      </p>
    </>
  );
}

function PlanKey({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span>
      <span className="legend__swatch" style={{ border: `1.5px solid ${TONE_BORDER[tone]}` }} />
      {label}
    </span>
  );
}

/** One bar: label, the same stacked-segment track as the console, its total,
 *  then every segment's name and value printed below — the console left that
 *  to a hover tooltip, which a phone cannot offer. */
function BarRow({ bar }: { bar: CountBar }) {
  return (
    <div className="card card--tight" style={{ padding: 12 }}>
      <div className="spread" style={{ marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--tx2)', fontWeight: 600 }}>{bar.label}</span>
        <span style={{ fontSize: 15, fontWeight: 700 }}>{bar.value}</span>
      </div>
      <div className="bar-track" style={{ display: 'flex', overflow: 'hidden' }}>
        {bar.parts.length === 0 ? (
          <div className="bar-fill" style={{ width: `${bar.pct}%` }} />
        ) : (
          bar.parts.map((part, i) => (
            <div
              key={part.name}
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
      {bar.parts.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8 }}>
          {bar.parts.map((part, i) => (
            <span key={part.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--tx2)' }}>
              <span style={{
                width: 10, height: 10, borderRadius: 3, flexShrink: 0,
                background: SEGMENT[i % SEGMENT.length], opacity: part.live ? 1 : 0.45,
              }} />
              {part.name}: {part.value}{!part.live && ' (demo figure)'}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
