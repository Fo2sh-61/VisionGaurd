import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useCameras } from '@/app/CameraContext';
import { useT } from '@/app/LanguageContext';
import { useSite } from '@/app/SiteContext';
import { useAlertFeed } from '@/app/useAlertFeed';
import { useAttention } from '@/app/useAttention';
import { useTodayFigures } from '@/app/useTodayFigures';
import { CameraFrame } from '@/components/CameraFrame';
import { Badge } from '@/components/ui';
import { ask } from '@/services/ask';
import { SUGGESTED_QUESTIONS } from '@/services/content';
import type { MessageKey } from '@/i18n';

/** Home: what needs you now, how today is going, and one live camera.
 *
 *  Spec 015 (P13-FR-046). The console's Home is the starting point - its
 *  greeting, Ask, suggested questions and attention list, with the same
 *  wording and the same links - rearranged so the thing a guard has to act on
 *  is at the top of the first screen.
 *
 *  Honesty rules this screen keeps:
 *  - "Nothing needs attention" appears only when the attention feed actually
 *    answered and is empty. Checking, off, failed and engine-down each say so.
 *  - Every figure is its tool's own figure (`useTodayFigures`), never a zero
 *    standing in for "not running".
 *  - An attention item opens the exact item (`item.link`), as the console's
 *    bell does - the old phone Home opened only the tool. */

const FIGURE_LABEL: Record<string, MessageKey> = {
  arrived: 'phone.home.arrived',
  inView: 'phone.home.inView',
  carsIn: 'phone.home.carsIn',
  restricted: 'phone.home.restricted',
};

export function Home() {
  const t = useT();
  const account = useAccount();
  const navigate = useNavigate();
  const { todayLabel } = useSite();
  const [question, setQuestion] = useState('');
  const [note, setNote] = useState('');

  const firstName = account.name.split(' ')[0];
  const { items: attention, acknowledge } = useAttention();
  const { feed, line } = useAlertFeed(false);
  const figures = useTodayFigures();
  const { cameras } = useCameras();
  const live = cameras.find((c) => !c.offline);

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
      // The whole path, parameters included — not just the tool.
      navigate(outcome.to, { state: { autoRun: true } });
    } else if (outcome.kind === 'note') {
      setNote(t(outcome.message, outcome.args));
    } else {
      setNote('');
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    void submit(question);
  }

  const quiet = feed === 'ready' && attention.length === 0;

  return (
    <>
      <div>
        <h1 className="h1">{t('home.greeting', { name: firstName })}</h1>
        {todayLabel && <p className="lead">{todayLabel}</p>}
      </div>

      {/* ---- Ask ---- */}
      <form className="card stack" style={{ padding: 12, gap: 10 }} onSubmit={onSubmit}>
        <div className="hstack" style={{ gap: 8 }}>
          <input
            className="input"
            style={{ flex: 1 }}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t('home.askPlaceholder')}
            aria-label={t('home.askLabel')}
            enterKeyHint="search"
          />
          <button type="submit" className="btn" style={{ flexShrink: 0 }}>
            {t('home.ask')}
          </button>
        </div>
        {note && (
          <div className="notice notice--amber" role="status" style={{ padding: '9px 12px' }}>
            {note}
          </div>
        )}
        <div className="chips" style={{ margin: '0 -12px', padding: '2px 12px' }}>
          {SUGGESTED_QUESTIONS.map((q) => (
            <button
              type="button"
              key={q}
              className="chip chip--on"
              onClick={() => {
                // The list holds keys; the ask bar takes words.
                setQuestion(t(q));
                void submit(t(q));
              }}
            >
              <span>{t(q)}</span>
            </button>
          ))}
        </div>
      </form>

      {/* ---- Needs your attention ---- */}
      <section className="stack" aria-labelledby="home-attention">
        <div className="sechead">
          <h2 className="sechead__title" id="home-attention" style={{ margin: 0 }}>
            {t('home.needsAttention')}
            {feed === 'ready' && ` · ${attention.length}`}
          </h2>
          <button type="button" className="sechead__link" onClick={() => navigate('/alerts')}>
            {t('phone.seeAll')}
          </button>
        </div>

        {feed !== 'ready' || quiet ? (
          // Checking, off, failed, engine down - or genuinely nothing. The
          // sentence and colour are the bell's, so the two never disagree.
          <div className="card hstack" role="status">
            <span className="glyph" style={{ background: line.color }}>{line.glyph ?? '·'}</span>
            <span style={{ color: line.color, fontWeight: 600 }}>{line.title}</span>
          </div>
        ) : (
          attention.map((item) => (
            <article key={item.id} className="card stack" style={{ gap: 10 }}>
              <div>
                <Badge tone={item.tone} icon={item.icon}>{item.kind}</Badge>
              </div>
              <div>
                <div className="li__title">{item.title}</div>
                <div className="li__sub">{item.sub}</div>
              </div>
              <div className="btnrow">
                <button
                  type="button"
                  className={item.tone === 'bad' ? 'btn btn--danger' : 'btn btn--soft'}
                  onClick={() => navigate(item.link, { state: { autoRun: true } })}
                >
                  {item.action}
                </button>
                {/* Takes the item off Home under the signed-in name. It changes
                    nothing else: a knife still waits for its verdict. */}
                <button type="button" className="btn btn--ghost" onClick={() => void acknowledge(item.id)}>
                  {t('attention.acknowledge')}
                </button>
              </div>
            </article>
          ))
        )}
      </section>

      {/* ---- Today so far ---- */}
      <section className="stack" aria-labelledby="home-today">
        <div className="sechead">
          <h2 className="sechead__title" id="home-today" style={{ margin: 0 }}>{t('phone.home.today')}</h2>
        </div>
        <div className="statgrid">
          {figures.map((f) => (
            <button
              type="button"
              key={f.id}
              className="stat"
              onClick={() => navigate(f.to, { state: { autoRun: true } })}
            >
              <span className="stat__label">{t(FIGURE_LABEL[f.id])}</span>
              {f.value !== null ? (
                <span className="stat__value" style={{ fontSize: f.value.length > 10 ? 18 : 24 }}>
                  {f.value}
                </span>
              ) : (
                <span className="stat__value" style={{ color: 'var(--tx2)' }} aria-hidden="true">—</span>
              )}
              <span className="stat__detail" style={f.warn ? { color: 'var(--am)' } : undefined}>
                {f.detail}
              </span>
            </button>
          ))}
        </div>
      </section>

      {/* ---- Live now ---- */}
      <section className="stack" aria-labelledby="home-live">
        <div className="sechead">
          <h2 className="sechead__title" id="home-live" style={{ margin: 0 }}>{t('phone.home.liveNow')}</h2>
          <button type="button" className="sechead__link" onClick={() => navigate('/cameras')}>
            {t('phone.home.allCameras')}
          </button>
        </div>
        {live ? (
          <button type="button" className="camtile" onClick={() => navigate(`/cameras/${encodeURIComponent(live.id)}`)}>
            {/* A plain picture: no overlay on Home, so no name is drawn here. */}
            <CameraFrame camera={live} detections={false} />
            <span className="camtile__caption">
              <span className="camtile__name">{live.name}</span>
              <span className="camtile__meta">{live.area || live.status}</span>
            </span>
          </button>
        ) : (
          <div className="card note">{t('phone.home.noLiveCamera')}</div>
        )}
      </section>

    </>
  );
}
