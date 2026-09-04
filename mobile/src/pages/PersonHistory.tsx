import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Badge, Card, DataNotice, Empty, LoadError, PageHeader, Stats } from '@/components/ui';
import { useLanguage, useT } from '@/app/LanguageContext';
import { getHistory } from '@/services/api';
import type { PersonHistory as PersonHistoryData } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

export function PersonHistory() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('attendance');
  const { name = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const state = location.state as { from?: 'people' | 'group'; groupName?: string } | null;
  const person = decodeURIComponent(name);

  const { data: history, error, loading, reload } = useAsync<PersonHistoryData | null>(
    () => getHistory(person, language),
    [person, language],
    null,
  );

  const backLabel = state?.from === 'group' ? `‹ ${state.groupName}` : '‹ People';
  const backTo =
    state?.from === 'group' && state.groupName
      ? `/people/groups/${encodeURIComponent(state.groupName)}`
      : '/people';

  // Previously `if (!history) return null`, which meant a failed request drew
  // an empty page with no way to tell whether this person has no history or
  // the engine simply could not be reached. The back link matters most in
  // exactly that case, so it is now always rendered.
  if (!history) {
    return (
      <>
        <div style={{ marginBottom: 4 }}>
          <button type="button" className="linkbtn" onClick={() => navigate(backTo)}>
            {backLabel}
          </button>
        </div>
        <DataNotice capability={capability} />
        <LoadError error={error} onRetry={reload} what="load.personHistory" whatArgs={{ person }} />
        <PageHeader title={person} lead={t('people.attendanceThisTerm')} />
        <Card>
          {loading ? (
            <Empty>{t('people.loadingHistory')}</Empty>
          ) : error ? (
            <Empty>{t('people.noHistory')}</Empty>
          ) : (
            <Empty>{t('people.noHistoryFor', { person })}</Empty>
          )}
        </Card>
      </>
    );
  }

  return (
    <>
      <div style={{ marginBottom: 4 }}>
        <button type="button" className="linkbtn" onClick={() => navigate(backTo)}>
          {backLabel}
        </button>
      </div>
      <DataNotice capability={capability} />
      <LoadError error={error} onRetry={reload} what="load.personHistory" whatArgs={{ person }} />
      <PageHeader title={history.name} lead={`${history.sub} · attendance this term`} />

      <Card>
        <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>{history.heading}</div>
        <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 18px' }}>{history.lead}</div>
        <Stats items={history.stats} columns={4} />

        <div className="section-title" style={{ marginTop: 8 }}>
          Day by day
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {history.bars.map((bar) => (
            <div key={bar.date} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ width: 56, fontSize: 13, color: 'var(--tx2)', flexShrink: 0 }}>{bar.day}</span>
              <div className="bar-track">
                <div
                  className="bar-fill"
                  style={{
                    width: `${bar.pct}%`,
                    background: bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac)',
                  }}
                />
              </div>
              <span
                style={{
                  width: 64,
                  textAlign: 'end',
                  fontSize: 13,
                  fontWeight: 600,
                  flexShrink: 0,
                  color:
                    bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac)',
                }}
              >
                {bar.label}
              </span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 14 }}>
          One row per day the cameras were recording. Green is on time, amber is after the cut-off,
          red is not seen at all. Days nothing was recording are not counted either way.
        </div>
      </Card>

      <Card>
        <div className="section-title" style={{ marginBottom: 4 }}>
          Days that needed follow-up
        </div>
        {history.flags.length === 0 && (
          <div className="row__muted" style={{ padding: '6px 0' }}>
            Nothing to follow up.
          </div>
        )}
        {history.flags.map((flag) => (
          <div key={`${flag.date}-${flag.badge}`} className="row" style={{ gridTemplateColumns: '1.2fr 1.6fr .7fr' }}>
            <span className="row__name">{flag.date}</span>
            <span className="row__muted">{flag.detail}</span>
            <span>
              <Badge tone={flag.tone}>{flag.badge}</Badge>
            </span>
          </div>
        ))}
      </Card>
    </>
  );
}
