import { useState, type KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useCameras } from '@/app/CameraContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import { homeTools, pathFor } from '@/app/navigation';
import { usePlaces } from '@/app/useOptions';
import { useToday } from '@/app/SiteContext';
import { useToast } from '@/app/ToastContext';
import { useAsync } from '@/app/useAsync';
import { CameraFrame } from '@/components/CameraFrame';
import { Plate } from '@/components/Plate';
import { Badge } from '@/components/ui';
import { ask } from '@/services/ask';
import { getCount, getVehiclePasses } from '@/services/api';
import { SUGGESTED_QUESTIONS } from '@/services/content';
import { formatCount, formatEventTime } from '@/services/format';
import { getNotArrivedCount } from '@/services/navBadges';
import { useAttention } from '@/app/useAttention';
import type { ToolId } from '@/types';

/** The strip shows four cameras. More than that is the Cameras page's job. */
const STRIP = 4;

export function Home() {
  const t = useT();
  const account = useAccount();
  const navigate = useNavigate();
  const [question, setQuestion] = useState('');
  const [note, setNote] = useState('');

  const firstName = account.name.split(' ')[0];
  const { items: attention, acknowledge } = useAttention();
  const toast = useToast();
  // IT has no Attendance, so it has no Attendance card either.
  const tools = homeTools().filter((tool) => tool.id !== 'attendance' || account.role === 'admin');

  function open(tool: ToolId, autoRun = true) {
    navigate(pathFor(tool), { state: { autoRun } });
  }

  async function submit(text: string) {
    // An empty box is the commonest way to press this button by accident.
    // Saying so beats routing nowhere and looking broken.
    if (!text.trim()) {
      setNote(t('home.typeSomething'));
      return;
    }
    setNote(t('ask.asking'));
    const outcome = await ask(text, account.role);
    if (outcome.kind === 'route') {
      setNote('');
      // The whole path, parameters included — not just the tool. Opening
      // Track a Person empty and leaving you to retype the name you had just
      // typed is what this bar used to do, and it is why it felt like it had
      // not understood.
      navigate(outcome.to, { state: { autoRun: true } });
    } else if (outcome.kind === 'note') {
      setNote(t(outcome.message, outcome.args));
    } else {
      setNote('');
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') void submit(question);
  }

  return (
    <>
      <h1 style={{ fontWeight: 700, fontSize: 29, letterSpacing: '-.02em', margin: 0 }}>
        {t('home.greeting', { name: firstName })}
      </h1>
      <p style={{ fontSize: 15, color: 'var(--tx2)', marginTop: 5 }}>
        {t('home.lead')}
      </p>

      <div style={{ display: 'flex', gap: 10, margin: '24px 0 12px', maxWidth: 700 }}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={t('home.askPlaceholder')}
          aria-label={t('home.askLabel')}
          style={{
            flex: 1,
            height: 56,
            border: 'none',
            borderRadius: 14,
            padding: '0 20px',
            fontSize: 15.5,
            background: 'var(--card)',
            color: 'var(--tx)',
            outline: 'none',
            boxShadow: 'var(--sh)',
          }}
        />
        <button
          type="button"
          className="btn"
          style={{ height: 56, borderRadius: 14, padding: '0 26px', fontSize: 15 }}
          onClick={() => void submit(question)}
        >
          {t('home.ask')}
        </button>
      </div>

      {note && (
        <div
          style={{
            fontSize: 13.5,
            color: 'var(--am)',
            background: 'var(--am-bg)',
            display: 'inline-block',
            padding: '8px 14px',
            borderRadius: 10,
            marginBottom: 12,
          }}
        >
          {note}
        </div>
      )}

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 42 }}>
        {SUGGESTED_QUESTIONS.filter((q) => q !== 'ask.q.absent' || account.role === 'admin').map((q) => (
          <button
            type="button"
            key={q}
            onClick={() => {
              // The list holds keys; the ask bar takes words.
              setQuestion(t(q));
              void submit(t(q));
            }}
            style={{
              padding: '7px 14px',
              borderRadius: 10,
              fontSize: 13,
              color: 'var(--ac2)',
              background: 'var(--chip)',
              fontWeight: 500,
              border: 'none',
              cursor: 'pointer',
            }}
          >
            {t(q)}
          </button>
        ))}
      </div>

      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>
        {t('home.needsAttention')}{' '}
        <span style={{ fontWeight: 500, color: 'var(--tx3)', fontSize: 13.5 }}>
          {attention.length === 1
            ? t('home.attentionCountOne')
            : t('home.attentionCount', { count: attention.length })}
        </span>
      </div>
      <div className="grid-2" style={{ marginBottom: 42 }}>
        {attention.map((item) => (
          <div
            key={item.id}
            style={{
              background: 'var(--card)',
              borderRadius: 14,
              padding: 18,
              boxShadow: 'var(--sh)',
            }}
          >
            <div style={{ marginBottom: 10 }}>
              <Badge tone={item.tone} icon={item.icon}>
                {item.kind}
              </Badge>
            </div>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>{item.title}</div>
            <div style={{ fontSize: 13, color: 'var(--tx3)', margin: '3px 0 12px' }}>
              {item.sub}
            </div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              {/* The item itself, not just its page: the same link the alert
                  bell opens. */}
              <button
                type="button"
                className="linkbtn"
                onClick={() => navigate(item.link, { state: { autoRun: true } })}
              >
                {item.action}{' '}
                <span className="mirror-rtl" aria-hidden="true">→</span>
              </button>
              {/* Takes the item off Home under the signed-in name. It changes
                  nothing else: a knife still waits for its verdict. */}
              <button
                type="button"
                className="linkbtn"
                onClick={() => void acknowledge(item.id).then((done) => {
                  if (done) toast.show(t('home.acknowledged'));
                })}
              >
                {t('attention.acknowledge')}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 12 }}>{t('home.tools')}</div>
      <div className="grid-4" style={{ marginBottom: 42 }}>
        {tools.map((tool) => (
          <button
            type="button"
            key={tool.id}
            onClick={() => open(tool.id, false)}
            style={{
              background: 'var(--card)',
              borderRadius: 12,
              padding: 15,
              boxShadow: 'var(--sh)',
              border: 'none',
              cursor: 'pointer',
              textAlign: 'start',
              color: 'var(--tx)',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 13.5 }}>{t(`nav.${tool.id}.label`)}</div>
            <FeatureValue tool={tool.id} />
          </button>
        ))}
      </div>

      <CameraStrip />
    </>
  );
}

/** What one feature card says right now, from the engine's own answer.
 *
 *  Each card asks for itself and fails alone: one call failing prints
 *  "Unavailable right now" on that card, never a 0 or an empty value. */
function FeatureValue({ tool }: { tool: ToolId }) {
  const t = useT();
  const { language } = useLanguage();
  const today = useToday();
  // The site's first place is the whole site ("All"); the engine owns the name.
  const allPlaces = usePlaces()[0];

  const notArrived = useAsync<number | null>(
    () => (tool === 'attendance' ? getNotArrivedCount(today) : Promise.resolve(null)),
    [tool, today], null, 15_000);
  const people = useAsync<number | null>(
    async () => {
      if (tool !== 'counting' || !allPlaces) return null;
      const result = await getCount({ place: allPlaces, when: 'Right now' }, language);
      // Only places a camera actually measured. A demo figure added into the
      // total would put an invented number on Home.
      const live = result.areas.filter((a) => a.live);
      return live.length ? live.reduce((sum, a) => sum + a.value, 0) : null;
    },
    [tool, language, allPlaces], null, 15_000);
  const lastPass = useAsync(
    async () => (tool === 'vehicles' ? (await getVehiclePasses({ limit: 1 }))[0] ?? null : null),
    [tool], null, 15_000);

  const sub = { fontSize: 12, color: 'var(--tx3)', marginTop: 2 } as const;
  const big = { fontSize: 20, fontWeight: 700, marginTop: 8 } as const;
  const unavailable = <div style={sub}>{t('home.card.unavailable')}</div>;

  if (tool === 'attendance') {
    if (notArrived.loading && notArrived.data === null) return null;
    if (notArrived.error || notArrived.data === null) return unavailable;
    return <div style={big}>{t('home.card.notArrived', { count: formatCount(notArrived.data, language) })}</div>;
  }
  if (tool === 'counting') {
    if (people.loading && people.data === null) return null;
    if (people.error || people.data === null) return unavailable;
    return (
      <>
        <div style={big}>{t('home.card.population', { count: formatCount(people.data, language) })}</div>
        <div style={sub}>{t('home.card.populationSub')}</div>
      </>
    );
  }
  if (tool === 'vehicles') {
    if (lastPass.error) return unavailable;
    if (lastPass.loading && !lastPass.data) return null;
    if (!lastPass.data) return <div style={sub}>{t('home.card.noPlate')}</div>;
    return (
      <>
        <div style={{ marginTop: 8 }}><Plate display={lastPass.data.plateDisplay} compact /></div>
        <div style={sub}>
          {t('home.card.lastPlate')} · {formatEventTime(lastPass.data.at, language)}
        </div>
      </>
    );
  }
  return null;
}

/** Up to four cameras that are up, as pictures. `detections={false}`: Home
 *  shows a view, not who is in it, so no recognition box carrying a name is
 *  fetched here. Snapshots, not a stream: four held-open streams would use
 *  up the connections the browser allows this site. */
function CameraStrip() {
  const t = useT();
  const navigate = useNavigate();
  const { cameras, error, loading } = useCameras();
  const up = cameras.filter((c) => !c.offline).slice(0, STRIP);

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 16 }}>{t('home.cameras.title')}</div>
        {/* Spec 027 adds a Cameras page; until then, System health lists them. */}
        <button type="button" className="linkbtn" onClick={() => navigate(pathFor('system'))}>
          {t('home.cameras.all')} <span className="mirror-rtl" aria-hidden="true">→</span>
        </button>
      </div>
      {up.length === 0 ? (
        <div style={{ fontSize: 13.5, color: 'var(--tx3)' }}>
          {t(error && !loading ? 'home.cameras.unavailable' : 'home.cameras.none')}
        </div>
      ) : (
        <div className="grid-4">
          {up.map((camera) => (
            <div key={camera.id}>
              <CameraFrame camera={camera} detections={false} badge={null} />
              <div style={{ fontSize: 12.5, fontWeight: 600, marginTop: 6 }}>{camera.name}</div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
