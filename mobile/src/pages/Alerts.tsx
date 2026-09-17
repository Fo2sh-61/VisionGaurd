import { useNavigate } from 'react-router-dom';
import { useLanguage } from '@/app/LanguageContext';
import { useAlertFeed } from '@/app/useAlertFeed';
import { useAsync } from '@/app/useAsync';
import { Icon } from '@/components/Icon';
import { toneColors } from '@/components/ui';
import { formatEventTime } from '@/services/format';
import { getDeliveries } from '@/services/api';
import type { DeliveryRow } from '@/services/wire';
import type { AttentionItem, Tone } from '@/types';

/** The delivery log's outcome colours, as Settings shows them. */
const OUTCOME_TONE: Record<DeliveryRow['outcome'], Tone> = {
  sent: 'good',
  failed: 'bad',
  skipped: 'warn',
  queued: 'neutral',
};

/** The console's bell, as a screen of its own (spec 015, P13-FR-045).
 *
 *  Being on this screen is what "opening the bell" means on the phone: while
 *  it is mounted, every open item counts as seen, and anything that arrives is
 *  seen as it arrives - the same rule, from the same hook, as the console's
 *  dropdown. So the number on either app's bell clears the same way.
 *
 *  Each item opens the exact thing it is about. Acknowledging stays on Home
 *  and on the pages, where it is audited - as on the console, this list only
 *  lists and opens.
 *
 *  "Messages sent" is the delivery log Settings already shows (anyone may read
 *  it; `/settings` is admin-only to write). It appears only when the engine
 *  answers: a refusal or a missing sender hides it rather than showing an
 *  empty list that would read as "nothing was sent". */
export function Alerts() {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const { feed, line, capability, items, newGroup, seenGroup } = useAlertFeed(true);
  const log = useAsync(() => getDeliveries(5), [], null, 30_000);

  function go(item: AttentionItem) {
    navigate(item.link, { state: { autoRun: true } });
  }

  return (
    <>
      <div className="card stack" role="status" style={{ gap: 6 }}>
        <div className="hstack" style={{ color: line.color, fontWeight: 700 }}>
          {line.glyph && <span className="glyph" style={{ background: line.color }}>{line.glyph}</span>}
          {line.title}
        </div>
        {feed === 'off' && (
          <>
            <div className="note">{t('bell.offLead')}</div>
            {/* The engine's own reason, in full: a list that is not running
                must say why. */}
            {capability?.reason && <div className="note">{capability.reason}</div>}
          </>
        )}
        {feed === 'ready' && capability?.state === 'demo' && (
          <div className="note" style={{ color: 'var(--am)' }}>{t('state.demoData')}</div>
        )}
      </div>

      {items.length > 0 && newGroup.length > 0 && (
        <Group label={t('bell.groupNew')} items={newGroup} onOpen={go} />
      )}
      {items.length > 0 && seenGroup.length > 0 && (
        <Group label={t('bell.groupSeen')} items={seenGroup} onOpen={go} />
      )}

      {log.data?.available && log.data.rows.length > 0 && (
        <section className="stack" aria-labelledby="alerts-sent">
          <div className="sechead">
            <h2 className="sechead__title" id="alerts-sent" style={{ margin: 0 }}>{t('phone.alerts.sent')}</h2>
            <button type="button" className="sechead__link" onClick={() => navigate('/settings')}>
              {t('phone.seeAll')}
            </button>
          </div>
          <p className="note" style={{ margin: '0 2px' }}>{t('phone.alerts.sentLead')}</p>
          <div className="list">
            {log.data.rows.map((row) => (
              <div key={row.id} className="li">
                <span className="icontile"><Icon name="bell" /></span>
                <span className="li__main">
                  <span className="li__title">{t(`settings.alerts.kind.${row.kind}` as const)}</span>
                  <span className="li__sub">
                    {formatEventTime(row.at, language)}
                    {' · '}
                    {row.channel ? t(`settings.alerts.channel.${row.channel}` as const) : '—'}
                    {row.recipientName ? ` · ${row.recipientName}` : ''}
                  </span>
                </span>
                <span
                  className="badge"
                  style={{ background: toneColors[OUTCOME_TONE[row.outcome]].bg, color: toneColors[OUTCOME_TONE[row.outcome]].fg }}
                >
                  {t(`settings.alerts.outcome.${row.outcome}` as const)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function Group({ label, items, onOpen }: {
  label: string;
  items: AttentionItem[];
  onOpen: (item: AttentionItem) => void;
}) {
  return (
    <section className="stack" role="group" aria-label={label}>
      <div className="sechead">
        <span className="sechead__title" aria-hidden="true">{label}</span>
      </div>
      <div className="list">
        {items.map((item) => (
          <button key={item.id} type="button" className="li" onClick={() => onOpen(item)}>
            <span
              className="icontile"
              style={{ background: toneColors[item.tone].bg, color: toneColors[item.tone].fg }}
              aria-hidden="true"
            >
              <Icon tool={item.to} />
            </span>
            <span className="li__main">
              <span className="li__title">{item.title}</span>
              <span className="li__sub">{item.sub}</span>
              {/* The words beside the colour carry the difference, so it never
                  rests on colour alone. */}
              <span className="li__sub" style={{ color: toneColors[item.tone].fg, fontWeight: 600 }}>
                {item.kind} · {item.action}
              </span>
            </span>
            <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
          </button>
        ))}
      </div>
    </section>
  );
}
