import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertSettingsCards } from '@/components/AlertSettings';
import { PhoneNotifications } from '@/components/PhoneNotifications';
import { Card, LoadError, PageHeader } from '@/components/ui';
import { useLanguage } from '@/app/LanguageContext';
import { getSchoolProfile, getZones } from '@/services/api';
import { formatDayMonthYear } from '@/services/format';
import type { SchoolProfile, Zone } from '@/types';

/*  Settings, laid out for a phone (spec 015, P13-FR-049).
 *
 *  Built from `web/src/pages/Settings.tsx`: the same reads (school profile,
 *  zone summary), the same independent-failure handling, and the same
 *  wording. Two things differ on purpose:
 *
 *  - The console's "click a value to edit" school profile saves nothing -
 *    `setProfile` only ever changes local state, and no call writes it back
 *    (research R10, R15/G15). Copying that editor onto the phone would be a
 *    second dead control instead of one, so the phone shows the same values
 *    read-only with `phone.settings.readOnly` in view instead.
 *  - Appearance and language moved to More (contract: phone-screens.md).
 *    They are not repeated here, so the lead ("Your school, your alerts...")
 *    drops the console's "how the console looks" clause — this screen no
 *    longer delivers that.
 *
 *  AlertSettings - rules, recipients, the delivery log - stays the console's
 *  own component, unchanged, inside `.legacy`. */

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

export function Settings() {
  const navigate = useNavigate();
  const { language, t } = useLanguage();

  const [profile, setProfile] = useState<SchoolProfile>(EMPTY_PROFILE);
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

  const zonesPaused = zones.filter((z) => !z.enabled).length;
  // "0 protected areas · all active" is a reassuring sentence to print when
  // the request simply failed, so it is only printed when zones arrived.
  const zoneSummary = zones.length === 0 && loadError
    ? 'Zone summary unavailable — managed on the Intrusion page'
    : `${zones.length} protected areas · ${
        zonesPaused ? `${zonesPaused} paused` : 'all active'
      } — managed on the Intrusion page, so there is one source of truth`;

  const profileRows: { key: string; label: string; display: string }[] = [
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
      <PageHeader title="Settings" lead={t('phone.settings.lead')} />

      {/* This person's phone first: anyone may switch it on; an administrator
          decides whether it receives anything (spec 020). */}
      <PhoneNotifications />

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>School profile</div>
        <div className="li__sub" style={{ margin: '2px 0 10px' }}>
          {t('phone.settings.readOnly')}
        </div>

        <div className="list">
          {profileRows.map((row) => (
            <div key={row.key} className="li" style={{ minHeight: 56, alignItems: 'flex-start', flexDirection: 'column', justifyContent: 'center', gap: 2 }}>
              <span className="li__sub">{row.label}</span>
              <span className="li__title" style={{ fontSize: 14.5 }}>{row.display || '—'}</span>
            </div>
          ))}
        </div>
      </Card>

      <div className="legacy">
        <AlertSettingsCards />
      </div>

      <Card tight>
        <div className="spread" style={{ alignItems: 'flex-start' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Detection zones</div>
            <div className="li__sub" style={{ marginTop: 2 }}>{zoneSummary}</div>
          </div>
          <button type="button" className="linkbtn" style={{ whiteSpace: 'nowrap' }} onClick={() => navigate('/intrusion')}>
            {t('settings.manageOnRestricted')}{' '}
            <span className="mirror-rtl" aria-hidden="true">→</span>
          </button>
        </div>
      </Card>
    </>
  );
}
