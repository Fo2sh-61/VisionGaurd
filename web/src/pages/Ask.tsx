import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Card, Empty, LoadError, PageHeader, Stats } from '@/components/ui';
import { ask } from '@/services/api';
import { formatEventTime, formatMetrics, formatPercent } from '@/services/format';
import type * as W from '@/services/wire';
import { useAccount } from '@/app/AuthContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/** Ask — type a question, get the answer the matching page would give.
 *
 *  **Every sentence on this page is built here, from a code.** The engine
 *  sends an outcome, a note code with facts, and rows of evidence; it never
 *  sends prose, and the language model never sends anything at all. That is
 *  the whole feature: the model chooses which query to run, and the console
 *  says what happened, in the operator's own language.
 *
 *  Deliberately no `CameraFrame`. With `live` it also polls recognition boxes,
 *  which carry names — the trap AGENTS.md names explicitly. Ask shows the clip
 *  a query already has, never a live tile. */
export function Ask() {
  const { language } = useLanguage();
  const t = useT();
  const account = useAccount();

  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<W.AskAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || asking) return;
    setAsking(true);
    setFailed(null);
    try {
      setAnswer(await ask(text));
    } catch (err) {
      // The endpoint answers 200 for every degradation, so reaching here means
      // the engine itself could not be reached — a different thing from "Ask
      // is unavailable", and it must not be dressed up as one.
      setFailed(err instanceof Error ? err.message : String(err));
      setAnswer(null);
    } finally {
      setAsking(false);
    }
  }

  return (
    <>
      <PageHeader title={t('ask.title')} lead={t('ask.blurb')} />

      <Card>
        <form onSubmit={submit} className="row" style={{ gridTemplateColumns: '1fr auto', gap: 8 }}>
          <input
            className="input"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t('ask.placeholder')}
            aria-label={t('ask.title')}
            maxLength={500}
          />
          <button className="chip-btn chip-btn--on" type="submit" disabled={asking || !question.trim()}>
            {asking ? t('ask.thinking') : t('ask.submit')}
          </button>
        </form>
      </Card>

      {failed && <LoadError error={failed} onRetry={() => setQuestion(question)} />}

      {answer && <Answer answer={answer} language={language} t={t} isAdmin={account?.role === 'admin'} />}
    </>
  );
}

function Answer({
  answer, language, t, isAdmin,
}: {
  answer: W.AskAnswer;
  language: Parameters<typeof formatEventTime>[1];
  t: (key: MessageKey, args?: Record<string, string | number>) => string;
  isAdmin: boolean;
}) {
  const note = answer.note;
  return (
    <Card>
      {/* The "understood as" line. It is mandatory and it is never collapsed.
          Ask answers straight away rather than asking for confirmation, so a
          confidently wrong route produces a true answer to a question nobody
          asked — and this line is the operator's only chance to notice. */}
      {answer.understood && (
        <p className="page__lead" style={{ marginTop: 0 }}>
          <strong>{t('ask.understoodAs')}:</strong>{' '}
          {t(`ask.query.${answer.understood.query}` as MessageKey)}
          {Object.entries(answer.understood.params)
            .filter(([, v]) => v)
            .map(([k, v]) => ` · ${k}: ${v}`)
            .join('')}
          {answer.understood.assumed.length > 0 && (
            <>
              {' · '}
              <Badge tone="warn">
                {t('ask.assumed', { fields: answer.understood.assumed.join(', ') })}
              </Badge>
            </>
          )}
        </p>
      )}

      {/* The honest states. Four outcomes, four different things to say, and
          none of them is an empty list of results. */}
      {note && (
        <p className="page__lead">
          {t(`note.${note.code}` as MessageKey, note.args)}
        </p>
      )}

      {answer.outcome === 'answered' && (
        <>
          {answer.headline.length > 0 && (
            <Stats items={formatMetrics(answer.headline, language)} />
          )}

          {answer.rows.length > 0 ? (
            <>
              <p className="page__lead">{t('ask.results', { count: answer.rows.length })}</p>
              <div className="list">
                {answer.rows.map((row, i) => (
                  <div
                    className="row"
                    key={`${row.label}-${i}`}
                    style={{ gridTemplateColumns: '2fr 1fr 1fr auto' }}
                  >
                    <span>{row.label}</span>
                    <span>{row.at ? formatEventTime(row.at, language) : '—'}</span>
                    <span>{row.camera ?? '—'}</span>
                    {/* Confidence travels with the evidence, at the strength
                        the query gave it. Ask never rounds an appearance
                        match up into a named certainty. */}
                    <span>
                      {row.confidence === null
                        ? '—'
                        : formatPercent(row.confidence, language)}
                    </span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <Empty>{t('ask.noResults')}</Empty>
          )}
        </>
      )}

      {/* Always additional, never the answer. */}
      {answer.deepLink && (
        <p style={{ marginTop: 12 }}>
          <Link className="linkbtn" to={answer.deepLink}>
            {t('ask.openPage')}
          </Link>
        </p>
      )}

      {/* P12-FR-012: what actually left the site, for anybody who can be
          asked to account for it. Unrecognised words are sent as typed, so
          this record is the only way to know what went. */}
      {isAdmin && (
        <p className="page__lead" style={{ fontSize: 12, opacity: 0.8 }}>
          {answer.sentOffSite
            ? t('ask.sentOffSite', { text: answer.sentOffSite })
            : t('ask.sentNothing')}
        </p>
      )}
    </Card>
  );
}
