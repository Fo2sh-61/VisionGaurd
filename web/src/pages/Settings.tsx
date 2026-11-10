import { useEffect, useState } from 'react';
import { useAccount } from '@/app/AuthContext';
import { useLanguage } from '@/app/LanguageContext';
import { useTheme } from '@/app/ThemeContext';
import { useToast } from '@/app/ToastContext';
import { AlertSettingsCards } from '@/components/AlertSettings';
import { Card, LoadError, PageHeader, Toggle } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { getSchoolProfile, updateSiteSettings } from '@/services/api';
import { formatDayMonthYear } from '@/services/format';
import type { SchoolProfile, SiteSettingsUpdate } from '@/services/wire';

/** Python weekday numbers (Monday is 0), in the order this site reads a week:
 *  Saturday first. */
const WEEK = [5, 6, 0, 1, 2, 3, 4] as const;
const DAY_KEY = {
  0: 'settings.day.0', 1: 'settings.day.1', 2: 'settings.day.2', 3: 'settings.day.3',
  4: 'settings.day.4', 5: 'settings.day.5', 6: 'settings.day.6',
} as const;

type ProfileKey = 'name' | 'hours' | 'calendar' | 'cutoff';

export function Settings() {
  const { dark, toggle } = useTheme();
  const { language, setLanguage, t } = useLanguage();
  const toast = useToast();
  // A hint for what to draw. The engine refuses a non-administrator's write
  // whatever this page shows.
  const admin = useAccount().role === 'admin';

  const [profile, setProfile] = useState<SchoolProfile | null>(null);
  const [editKey, setEditKey] = useState<ProfileKey | null>(null);
  // What the open row is being changed to. Sent when the person presses Done.
  const [draft, setDraft] = useState<SiteSettingsUpdate>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [loadError, setLoadError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    setLoadError(null);
    void getSchoolProfile()
      .then(setProfile)
      .catch((error: unknown) =>
        setLoadError(
          t('settings.loadFailed', {
            error: error instanceof Error ? error.message : t('settings.engineSilent'),
          }),
        ),
      );
    // `t` changes with the language only; the profile does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tick]);

  /** Send a change; the engine answers with the profile as saved, or says why
   *  not. Nothing is shown as saved until it has answered. */
  async function save(change: SiteSettingsUpdate): Promise<boolean> {
    setSaving(true);
    setSaveError(null);
    try {
      setProfile(await updateSiteSettings(change));
      toast.show(t('settings.saved'));
      return true;
    } catch (error) {
      setSaveError(
        t('settings.saveFailed', {
          reason: error instanceof Error ? error.message : t('common.engineRefused'),
        }),
      );
      return false;
    } finally {
      setSaving(false);
    }
  }

  function open(key: ProfileKey) {
    setSaveError(null);
    setDraft({});
    setEditKey(key);
  }

  function cancel() {
    setEditKey(null);
    setDraft({});
    setSaveError(null);
  }

  async function done() {
    // Nothing changed: close without a request.
    if (Object.keys(draft).length === 0) return cancel();
    if (await save(draft)) cancel();
  }

  async function toggleDay(day: number) {
    if (!profile) return;
    const next = profile.workingDays.includes(day)
      ? profile.workingDays.filter((d) => d !== day)
      : [...profile.workingDays, day];
    await save({ workingDays: next });
  }

  const time = (hhmm: string) => {
    const [h, m] = hhmm.split(':').map(Number);
    if (Number.isNaN(h) || Number.isNaN(m)) return hhmm;
    return new Date(2000, 0, 1, h, m).toLocaleTimeString(language, {
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  const rows: { key: ProfileKey; label: string; display: string }[] = profile
    ? [
        { key: 'name', label: t('settings.field.name'), display: profile.name },
        {
          key: 'hours',
          label: t('settings.field.hours'),
          display: t('settings.hoursRange', { from: time(profile.hoursFrom), to: time(profile.hoursTo) }),
        },
        {
          key: 'calendar',
          label: t('settings.field.calendar'),
          // Through the message catalogue rather than joined here, so the two
          // dates are isolated from the Arabic around them.
          display: profile.termFrom && profile.termTo
            ? t('settings.termRange', {
                from: formatDayMonthYear(profile.termFrom, language),
                to: formatDayMonthYear(profile.termTo, language),
              })
            : t('settings.calendarNotSet'),
        },
        {
          key: 'cutoff',
          label: t('settings.field.cutoff'),
          display: t('settings.cutoffDisplay', { time: time(profile.lateCutoff) }),
        },
      ]
    : [];

  const timeInput = (
    value: string,
    field: 'hoursFrom' | 'hoursTo' | 'lateCutoff',
    autoFocus = false,
  ) => (
    <input
      className="edit-input"
      type="time"
      autoFocus={autoFocus}
      defaultValue={value}
      onChange={(e) => e.target.value && setDraft((d) => ({ ...d, [field]: e.target.value }))}
    />
  );

  const dateInput = (
    value: string,
    field: 'termFrom' | 'termTo',
    autoFocus = false,
  ) => (
    <input
      className="edit-input"
      type="date"
      autoFocus={autoFocus}
      defaultValue={value}
      onChange={(e) => e.target.value && setDraft((d) => ({ ...d, [field]: e.target.value }))}
    />
  );

  return (
    <>
      <LoadError error={loadError} onRetry={() => setTick((n) => n + 1)} />
      <PageHeader title={t('settings.title')} lead={t('settings.lead')} />

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{t('settings.profile.title')}</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 4px' }}>
          {t(admin ? 'settings.profile.lead' : 'settings.profile.adminOnly')}
        </div>
        {saveError && (
          <div
            role="alert"
            style={{ fontSize: 13.5, color: 'var(--rd)', background: 'var(--rd-bg)', padding: '8px 14px', borderRadius: 10, margin: '8px 0' }}
          >
            {saveError}
          </div>
        )}

        {rows.map((row) => (
          <div key={row.key} className="edit-row">
            <span style={{ color: 'var(--tx2)' }}>{row.label}</span>

            {editKey === row.key && profile ? (
              <div
                style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void done();
                  if (e.key === 'Escape') cancel();
                }}
              >
                {row.key === 'name' && (
                  <input
                    className="edit-input"
                    autoFocus
                    defaultValue={profile.name}
                    onChange={(e) => setDraft({ name: e.target.value })}
                  />
                )}
                {row.key === 'hours' && (
                  <>
                    {timeInput(profile.hoursFrom, 'hoursFrom', true)}
                    <span style={{ color: 'var(--tx3)', fontSize: 13 }}>{t('settings.to')}</span>
                    {timeInput(profile.hoursTo, 'hoursTo')}
                  </>
                )}
                {row.key === 'calendar' && (
                  <>
                    {dateInput(profile.termFrom, 'termFrom', true)}
                    <span style={{ color: 'var(--tx3)', fontSize: 13 }}>{t('settings.to')}</span>
                    {dateInput(profile.termTo, 'termTo')}
                  </>
                )}
                {row.key === 'cutoff' && timeInput(profile.lateCutoff, 'lateCutoff', true)}
              </div>
            ) : (
              <span
                style={{ fontWeight: 600, cursor: admin ? 'pointer' : 'default' }}
                onClick={admin ? () => open(row.key) : undefined}
              >
                {row.display}
              </span>
            )}

            {admin && (
              <button
                type="button"
                className="linkbtn"
                style={{ textAlign: 'end' }}
                disabled={saving}
                onClick={() => (editKey === row.key ? void done() : open(row.key))}
              >
                {t(editKey === row.key ? 'settings.done' : 'settings.edit')}
              </button>
            )}
          </div>
        ))}

        {profile && (
          <div className="edit-row">
            <span style={{ color: 'var(--tx2)' }}>{t('settings.field.days')}</span>
            <div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {WEEK.map((day) => {
                  const on = profile.workingDays.includes(day);
                  return (
                    <button
                      key={day}
                      type="button"
                      className={`chip-btn ${on ? 'chip-btn--on' : 'chip-btn--off'}`}
                      aria-pressed={on}
                      disabled={!admin || saving}
                      onClick={() => void toggleDay(day)}
                    >
                      {t(DAY_KEY[day])}
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 6 }}>
                {t('settings.daysHint')}
              </div>
            </div>
            <span />
          </div>
        )}
      </Card>

      <AlertSettingsCards />

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>{t('settings.appearance.title')}</div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: '13px 0',
            borderBottom: '1px solid var(--line)',
          }}
        >
          <div>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{t('settings.dark')}</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{t('settings.dark.lead')}</div>
          </div>
          <Toggle on={dark} onToggle={toggle} label={t('settings.dark')} />
        </div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            padding: '13px 0',
            flexWrap: 'wrap',
          }}
        >
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>{t('settings.language')}</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              {t('settings.language.lead')}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {LANGUAGES.map((k) => (
              <button
                key={k}
                type="button"
                className={`chip-btn ${language === k ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setLanguage(k)}
              >
                {t(`settings.language.${k}`)}
              </button>
            ))}
          </div>
        </div>
      </Card>
    </>
  );
}
