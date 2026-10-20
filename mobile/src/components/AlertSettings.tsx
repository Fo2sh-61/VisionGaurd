/** Settings > Alerts: who is told about what, and what was sent (spec 013).
 *
 *  Three cards, and every control saves through the engine the moment it
 *  changes. Nothing here is local state pretending to be saved - the Alerts
 *  section used to be exactly that, with "edits save on their own" printed
 *  above switches that saved nothing. A change is sent, the page re-reads what
 *  the engine now holds, and a failed save says so where it happened.
 *
 *  Every sentence comes from the i18n catalogue and every fact from the
 *  engine. The engine never sends a value of a secret, only which variable is
 *  missing, so nothing on this page can leak a key.
 *
 *  Its own file so the Settings page changes by a few lines: the School
 *  profile card on the same page is being rebuilt by other work, and a small
 *  diff is what lets both land. The phone holds a byte copy, like the other
 *  feature components here. */

import { useState, type ReactNode } from 'react';
import { useAccount } from '@/app/AuthContext';
import { useLanguage } from '@/app/LanguageContext';
import { useAsync } from '@/app/useAsync';
import { Badge, Card, Empty, Field, Select, Toggle } from '@/components/ui';
import {
  addRecipient,
  getAlertSettings,
  getDeliveries,
  removeRecipient,
  sendTestAlert,
  updateAlertRule,
  updateRecipient,
} from '@/services/api';
import { formatDayMonthYear, formatEventTime } from '@/services/format';
import type { Tone } from '@/types';
import type {
  AlertChannel,
  AlertKind,
  AlertLanguage,
  AlertRule,
  AlertRuleUpdate,
  AlertSettings,
  DeliveryLog,
  DeliveryRow,
  Recipient,
  ReportStatus,
} from '@/services/wire';

/** The channels that leave the building: email, and since spec 020 a
 *  notification on a registered phone. WhatsApp and SMS were removed on
 *  11 Sep 2026. A list so the rows below stay generic. */
const CHANNELS: readonly AlertChannel[] = ['email', 'push'];
const LANGS: readonly AlertLanguage[] = ['en', 'ar'];
const GATE_REASONS = ['blacklist', 'unknown', 'expired'] as const;
const GATE_FLAG = {
  blacklist: 'vehicleBlacklist',
  unknown: 'vehicleUnknown',
  expired: 'vehicleExpired',
} as const;

/** How an outcome reads at a glance. Sent is only "the courier accepted it". */
const OUTCOME_TONE: Record<DeliveryRow['outcome'], Tone> = {
  sent: 'good',
  failed: 'bad',
  skipped: 'warn',
  queued: 'neutral',
};

const title = { fontWeight: 700, fontSize: 15 } as const;
const lead = { fontSize: 13, color: 'var(--tx2)', margin: '2px 0 4px' } as const;
const small = { fontSize: 12.5, color: 'var(--tx2)' } as const;

function why(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** A stated fact in the design's amber, for what cannot be done and why. */
function Notice({ children }: { children: ReactNode }) {
  return (
    <div
      role="status"
      style={{
        padding: '9px 12px',
        borderRadius: 10,
        margin: '8px 0',
        background: 'var(--am-bg)',
        color: 'var(--am)',
        fontSize: 13,
        lineHeight: 1.45,
      }}
    >
      {children}
    </div>
  );
}

function Chip({
  on,
  label,
  disabled,
  onClick,
}: {
  on: boolean;
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={`chip-btn ${on ? 'chip-btn--on' : 'chip-btn--off'}`}
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

export function AlertSettingsCards() {
  const { language, t } = useLanguage();
  // A hint for what to show. The engine refuses a non-administrator's write
  // whatever this page draws.
  const admin = useAccount().role === 'admin';

  const settings = useAsync<AlertSettings | null>(getAlertSettings, [], null);
  const log = useAsync<DeliveryLog | null>(() => getDeliveries(20), [], null, 10_000);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [testNote, setTestNote] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState({
    channel: 'email' as AlertChannel,
    destination: '',
    name: '',
    language: 'en' as AlertLanguage,
  });

  const s = settings.data;
  const channelName = (c: AlertChannel) => t(`settings.alerts.channel.${c}` as const);
  const kindName = (k: AlertKind | 'test') => t(`settings.alerts.kind.${k}` as const);

  /** Send one change; whatever happens, re-read what the engine now holds. */
  async function save(action: () => Promise<unknown>) {
    setSaveError(null);
    try {
      await action();
    } catch (error) {
      setSaveError(t('settings.alerts.saveFailed', { error: why(error) }));
    }
    settings.reload();
    log.reload();
  }

  function flip(rule: AlertRule, change: AlertRuleUpdate) {
    void save(() => updateAlertRule(rule.kind, change));
  }

  function flipChannel(rule: AlertRule, channel: AlertChannel) {
    const change: AlertRuleUpdate = {};
    change[channel] = !rule[channel];
    flip(rule, change);
  }

  async function test(person: Recipient) {
    setSaveError(null);
    try {
      const row = await sendTestAlert(person.id);
      setTestNote((notes) => ({
        ...notes,
        [person.id]:
          row.outcome === 'skipped' && row.reason
            ? t('settings.alerts.testSkipped', {
                reason: t(`settings.alerts.reason.${row.reason}` as const),
              })
            : t('settings.alerts.testQueued'),
      }));
    } catch (error) {
      setSaveError(t('settings.alerts.saveFailed', { error: why(error) }));
    }
    log.reload();
  }

  function reportLine(report: ReportStatus): string {
    const day = report.state === 'before_term' ? report.termFrom : report.termTo;
    return t(`settings.alerts.report.${report.state}` as const, {
      time: report.time,
      date: day ? formatDayMonthYear(day, language) : '',
    });
  }

  const l = log.data;

  return (
    <>
      <Card>
        <div style={title}>{t('settings.alerts.title')}</div>
        <div style={lead}>{t('settings.alerts.lead')}</div>
        {!admin && <div style={small}>{t('settings.alerts.adminOnly')}</div>}
        {settings.error && (
          <Notice>{t('settings.alerts.unavailable', { reason: settings.error })}</Notice>
        )}
        {s?.sending === 'off' && <Notice>{t('settings.alerts.sendingOff')}</Notice>}
        {s?.sending === 'failed' && (
          <Notice>{t('settings.alerts.sendingFailed', { error: s.sendingError ?? '' })}</Notice>
        )}
        {saveError && <Notice>{saveError}</Notice>}

        {s?.rules.map((rule) => (
          <div key={rule.kind} style={{ padding: '13px 0', borderBottom: '1px solid var(--line)' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 14,
                flexWrap: 'wrap',
              }}
            >
              <div style={{ flex: 1, minWidth: 220 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{kindName(rule.kind)}</div>
                <div style={small}>
                  {t(`settings.alerts.kind.${rule.kind}.sub` as const, {
                    minutes: s.cameraOfflineMinutes,
                  })}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {rule.inApp !== null && (
                  <Chip
                    on={rule.inApp}
                    label={t('settings.alerts.channel.inApp')}
                    disabled={!admin}
                    onClick={() => flip(rule, { inApp: !rule.inApp })}
                  />
                )}
                {CHANNELS.map((channel) => (
                  <Chip
                    key={channel}
                    on={rule[channel]}
                    label={channelName(channel)}
                    disabled={!admin}
                    onClick={() => flipChannel(rule, channel)}
                  />
                ))}
              </div>
            </div>

            {rule.kind === 'vehicles' && (
              <div
                style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}
              >
                <span style={small}>{t('settings.alerts.gate.lead')}</span>
                {GATE_REASONS.map((reason) => {
                  const flag = GATE_FLAG[reason];
                  const on = rule[flag] === true;
                  return (
                    <Chip
                      key={reason}
                      on={on}
                      label={t(`settings.alerts.gate.${reason}` as const)}
                      disabled={!admin}
                      onClick={() => {
                        const change: AlertRuleUpdate = {};
                        change[flag] = !on;
                        flip(rule, change);
                      }}
                    />
                  );
                })}
              </div>
            )}

            {rule.kind === 'attendance' && (
              <div style={{ ...small, marginTop: 6 }}>{reportLine(s.report)}</div>
            )}

            {s.unreached
              .filter((u) => u.kind === rule.kind)
              .map((u) => (
                <Notice key={u.channel}>
                  {t('settings.alerts.nobodyOnChannel', {
                    channel: channelName(u.channel),
                    kind: kindName(u.kind),
                  })}
                </Notice>
              ))}
          </div>
        ))}
      </Card>

      <Card>
        <div style={title}>{t('settings.alerts.recipientsTitle')}</div>
        <div style={lead}>{t('settings.alerts.recipientsLead')}</div>

        {s?.channels.map((status) =>
          status.configured ? (
            <div key={status.channel} style={small}>
              {t('settings.alerts.providerReady', { channel: channelName(status.channel) })}
            </div>
          ) : (
            <Notice key={status.channel}>
              {t('settings.alerts.providerMissing', {
                variables: status.missing.join(', '),
                channel: channelName(status.channel),
              })}
            </Notice>
          ),
        )}
        {s && !s.consoleUrlSet && <div style={{ ...small, marginTop: 6 }}>{t('settings.alerts.noConsoleUrl')}</div>}

        {s && s.recipients.length === 0 && <Empty>{t('settings.alerts.none')}</Empty>}
        {s?.recipients.map((person) => (
          <div
            key={person.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 14,
              padding: '13px 0',
              borderBottom: '1px solid var(--line)',
              flexWrap: 'wrap',
            }}
          >
            <div style={{ flex: 1, minWidth: 200 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{person.name}</div>
              <div style={small}>
                {channelName(person.channel)} ·{' '}
                {/* A phone's destination is its registration id: noise to a
                    reader. The name already says whose phone it is. */}
                {person.channel === 'push'
                  ? t('settings.alerts.phoneRecipient')
                  : <bdi>{person.destination}</bdi>} ·{' '}
                {t(`settings.language.${person.language}` as const)}
              </div>
              {person.language === 'ar' && !s.arabicReviewed && (
                <div style={{ ...small, color: 'var(--am)' }}>{t('settings.alerts.arabicUnreviewed')}</div>
              )}
              {testNote[person.id] && <div style={small}>{testNote[person.id]}</div>}
            </div>
            {admin && (
              <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <button type="button" className="linkbtn" onClick={() => void test(person)}>
                  {t('settings.alerts.sendTest')}
                </button>
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => void save(() => removeRecipient(person.id))}
                >
                  {t('settings.alerts.remove')}
                </button>
                <Toggle
                  on={person.enabled}
                  label={person.name}
                  onToggle={() => void save(() => updateRecipient(person.id, { enabled: !person.enabled }))}
                />
              </div>
            )}
          </div>
        ))}

        {admin && s && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save(async () => {
                await addRecipient(draft);
                setDraft((d) => ({ ...d, destination: '', name: '' }));
              });
            }}
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
              gap: 10,
              marginTop: 14,
              alignItems: 'end',
            }}
          >
            <Field label={t('settings.alerts.field.destination')}>
              {/* An address reads left to right in every language. */}
              <input
                className="input"
                dir="ltr"
                type="email"
                value={draft.destination}
                placeholder={t('settings.alerts.placeholder.email')}
                onChange={(e) => setDraft((d) => ({ ...d, destination: e.target.value }))}
              />
            </Field>
            <Field label={t('settings.alerts.field.name')}>
              <input
                className="input"
                value={draft.name}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              />
            </Field>
            <Field label={t('settings.alerts.field.language')}>
              <Select
                value={draft.language}
                options={LANGS}
                label={(code) => t(`settings.language.${code as AlertLanguage}` as const)}
                onChange={(code) => setDraft((d) => ({ ...d, language: code as AlertLanguage }))}
              />
            </Field>
            <button
              type="submit"
              className="chip-btn chip-btn--on"
              disabled={!draft.destination.trim() || !draft.name.trim()}
            >
              {t('settings.alerts.add')}
            </button>
          </form>
        )}
      </Card>

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
          <div>
            <div style={title}>{t('settings.alerts.logTitle')}</div>
            <div style={lead}>{t('settings.alerts.logLead')}</div>
          </div>
          <button type="button" className="linkbtn" onClick={log.reload}>
            {t('settings.alerts.refresh')}
          </button>
        </div>

        {log.error && <Notice>{t('settings.alerts.logUnavailable', { reason: log.error })}</Notice>}
        {l && !l.available && (
          <Notice>{t('settings.alerts.logUnavailable', { reason: l.reason ?? '' })}</Notice>
        )}
        {l?.available && l.rows.length === 0 && <Empty>{t('settings.alerts.logEmpty')}</Empty>}
        {l?.available &&
          l.rows.map((row) => (
            <div
              key={row.id}
              className="row"
              style={{
                gridTemplateColumns: 'minmax(110px, auto) 1fr auto',
                gap: 12,
                padding: '10px 0',
                borderBottom: '1px solid var(--line)',
                alignItems: 'start',
              }}
            >
              <span style={small}>{formatEventTime(row.at, language)}</span>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13.5 }}>
                  {kindName(row.kind)} · {row.channel ? channelName(row.channel) : '—'}
                  {row.recipientName ? ` · ${row.recipientName}` : ''}
                </div>
                {row.reason && (
                  <div style={small}>{t(`settings.alerts.reason.${row.reason}` as const)}</div>
                )}
                {row.providerReason && (
                  <div style={small}>{t('settings.alerts.courierSaid', { words: row.providerReason })}</div>
                )}
                {row.attempts > 1 && (
                  <div style={{ fontSize: 12, color: 'var(--tx3)' }}>
                    {t('settings.alerts.attempts', { count: row.attempts })}
                  </div>
                )}
              </div>
              <Badge tone={OUTCOME_TONE[row.outcome]}>
                {t(`settings.alerts.outcome.${row.outcome}` as const)}
              </Badge>
            </div>
          ))}
      </Card>
    </>
  );
}
