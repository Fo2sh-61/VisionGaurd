import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '@/app/LanguageContext';
import { useTheme } from '@/app/ThemeContext';
import { AlertSettingsCards } from '@/components/AlertSettings';
import { Card, LoadError, PageHeader, Toggle } from '@/components/ui';
import { LANGUAGES } from '@/i18n';
import { getSchoolProfile, getZones } from '@/services/api';
import { formatDayMonthYear } from '@/services/format';
import type { SchoolProfile, Zone } from '@/types';

const EMPTY_PROFILE: SchoolProfile = {
  name: '',
  hoursFrom: '',
  hoursTo: '',
  termFrom: '',
  termTo: '',
  cutoff: '',
};

function fmtTime(t: string) {
  if (!t) return '';
  const [h, m] = t.split(':');
  const hour = Number(h);
  const ap = hour >= 12 ? 'pm' : 'am';
  const h12 = hour % 12 || 12;
  return `${h12}:${m}${ap}`;
}

// Dates go through `format.ts` like every other rendered value. This was
// `toLocaleDateString('en-US', …)`, which showed an Arabic reader an American
// date - and an English one a format the rest of the console does not use.

type ProfileKey = 'name' | 'hours' | 'term' | 'cutoff';

export function Settings() {
  const navigate = useNavigate();
  const { dark, toggle } = useTheme();

  const [profile, setProfile] = useState<SchoolProfile>(EMPTY_PROFILE);
  const [editKey, setEditKey] = useState<ProfileKey | null>(null);

  const [zones, setZones] = useState<Zone[]>([]);

  // Independent reads. One failing must not blank the other, so each keeps
  // its own reason and the page renders whatever did arrive. The alert cards
  // load and save on their own (`AlertSettingsCards`).
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const note = (what: string) => (error: unknown) =>
    setLoadError(
      `${what} could not be loaded: ${error instanceof Error ? error.message : 'the engine did not answer'}`,
    );

  useEffect(() => {
    setLoadError(null);
    void getSchoolProfile().then((p) =>
      setProfile({
        name: p.name,
        hoursFrom: p.hoursFrom,
        hoursTo: p.hoursTo,
        termFrom: p.termFrom,
        termTo: p.termTo,
        cutoff: p.lateCutoff,
      }),
    ).catch(note('The school profile'));

    // Zones are managed on the Intrusion page; this is a read-only summary, so
    // both pages agree on the count.
    void getZones().then(setZones).catch(note('The zone summary'));
  }, [tick]);

  const { language, setLanguage, t } = useLanguage();

  const zonesPaused = zones.filter((z) => !z.enabled).length;
  // "0 protected areas · all active" is a reassuring sentence to print when
  // the request simply failed, so it is only printed when zones arrived.
  const zoneSummary = zones.length === 0 && loadError
    ? 'Zone summary unavailable — managed on the Intrusion page'
    : `${zones.length} protected areas · ${
        zonesPaused ? `${zonesPaused} paused` : 'all active'
      } — managed on the Intrusion page, so there is one source of truth`;

  const profileRows: { key: ProfileKey; label: string; display: string }[] = [
    { key: 'name', label: 'School name', display: profile.name },
    {
      key: 'hours',
      label: 'School hours',
      display: `${fmtTime(profile.hoursFrom)} – ${fmtTime(profile.hoursTo)}`,
    },
    {
      key: 'term',
      label: 'Term',
      // Through the message catalogue rather than joined here, so the two
      // dates are isolated from the Arabic around them. A range built with a
      // bare dash reorders in right-to-left text and reads back to front -
      // a term that appears to end before it starts.
      display: t('settings.termRange', {
        from: formatDayMonthYear(profile.termFrom, language),
        to: formatDayMonthYear(profile.termTo, language),
      }),
    },
    {
      key: 'cutoff',
      label: 'Attendance cut-off',
      display: `${fmtTime(profile.cutoff)} — later arrivals count as late`,
    },
  ];

  return (
    <>
      <LoadError error={loadError} onRetry={() => setTick((n) => n + 1)} />
      <PageHeader title="Settings" lead="Your school, your alerts, and how the console looks." />

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>School profile</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 4px' }}>
          Click a value to change it — edits save on their own.
        </div>

        {profileRows.map((row) => (
          <div key={row.key} className="edit-row">
            <span style={{ color: 'var(--tx2)' }}>{row.label}</span>

            {editKey === row.key ? (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {row.key === 'name' && (
                  <input
                    className="edit-input"
                    autoFocus
                    defaultValue={profile.name}
                    onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))}
                    onKeyDown={(e) => (e.key === 'Enter' || e.key === 'Escape') && setEditKey(null)}
                  />
                )}
                {row.key === 'hours' && (
                  <>
                    <input
                      className="edit-input"
                      type="time"
                      autoFocus
                      defaultValue={profile.hoursFrom}
                      onChange={(e) => e.target.value && setProfile((p) => ({ ...p, hoursFrom: e.target.value }))}
                    />
                    <span style={{ color: 'var(--tx3)', fontSize: 13 }}>to</span>
                    <input
                      className="edit-input"
                      type="time"
                      defaultValue={profile.hoursTo}
                      onChange={(e) => e.target.value && setProfile((p) => ({ ...p, hoursTo: e.target.value }))}
                    />
                  </>
                )}
                {row.key === 'term' && (
                  <>
                    <input
                      className="edit-input"
                      type="date"
                      autoFocus
                      defaultValue={profile.termFrom}
                      onChange={(e) => e.target.value && setProfile((p) => ({ ...p, termFrom: e.target.value }))}
                    />
                    <span style={{ color: 'var(--tx3)', fontSize: 13 }}>to</span>
                    <input
                      className="edit-input"
                      type="date"
                      defaultValue={profile.termTo}
                      onChange={(e) => e.target.value && setProfile((p) => ({ ...p, termTo: e.target.value }))}
                    />
                  </>
                )}
                {row.key === 'cutoff' && (
                  <input
                    className="edit-input"
                    type="time"
                    autoFocus
                    defaultValue={profile.cutoff}
                    onChange={(e) => e.target.value && setProfile((p) => ({ ...p, cutoff: e.target.value }))}
                  />
                )}
              </div>
            ) : (
              <span style={{ fontWeight: 600, cursor: 'pointer' }} onClick={() => setEditKey(row.key)}>
                {row.display}
              </span>
            )}

            <span
              style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13, cursor: 'pointer', textAlign: 'end' }}
              onClick={() => setEditKey(editKey === row.key ? null : row.key)}
            >
              {editKey === row.key ? 'Done' : 'Edit'}
            </span>
          </div>
        ))}
      </Card>

      <AlertSettingsCards />

      <Card tight>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Detection zones</div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 2 }}>{zoneSummary}</div>
          </div>
          <button type="button" className="linkbtn" style={{ whiteSpace: 'nowrap' }} onClick={() => navigate('/intrusion')}>
            {t('settings.manageOnRestricted')}{' '}
            <span className="mirror-rtl" aria-hidden="true">→</span>
          </button>
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>Appearance &amp; language</div>
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
            <div style={{ fontWeight: 600, fontSize: 14 }}>Dark mode</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              Easier on the eyes when the console is open all day.
            </div>
          </div>
          <Toggle on={dark} onToggle={toggle} label="Dark mode" />
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
