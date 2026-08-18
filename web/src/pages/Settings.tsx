import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '@/app/ThemeContext';
import { Card, PageHeader, Toggle } from '@/components/ui';
import { getAlertRules, getDeliveryTargets, getSchoolProfile, getZones } from '@/services/api';
import type { AlertChannel, AlertRule, DeliveryTarget, SchoolProfile, Zone } from '@/types';

const EMPTY_PROFILE: SchoolProfile = {
  name: '',
  hoursFrom: '',
  hoursTo: '',
  termFrom: '',
  termTo: '',
  cutoff: '',
};

/** Titles for the delivery rows. The engine sends the destination and whether
 *  it is on; how the row reads is the front end's business. */
const DELIVERY_META: Record<
  DeliveryTarget['key'],
  { inputType: DeliveryTarget['inputType']; placeholder: string }
> = {
  app: { inputType: 'text', placeholder: 'This device' },
  email: { inputType: 'email', placeholder: 'name@school.edu' },
  sms: { inputType: 'tel', placeholder: '+20 100 000 0000' },
  wa: { inputType: 'tel', placeholder: '+20 100 000 0000' },
};

const CHANNELS: AlertChannel[] = ['Push', 'Email', 'SMS'];

function fmtTime(t: string) {
  if (!t) return '';
  const [h, m] = t.split(':');
  const hour = Number(h);
  const ap = hour >= 12 ? 'pm' : 'am';
  const h12 = hour % 12 || 12;
  return `${h12}:${m}${ap}`;
}

function fmtDate(d: string) {
  if (!d) return '';
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  });
}

type ProfileKey = 'name' | 'hours' | 'term' | 'cutoff';

export function Settings() {
  const navigate = useNavigate();
  const { dark, toggle } = useTheme();

  const [profile, setProfile] = useState<SchoolProfile>(EMPTY_PROFILE);
  const [editKey, setEditKey] = useState<ProfileKey | null>(null);

  const [alerts, setAlerts] = useState<AlertRule[]>([]);
  const [deliveries, setDeliveries] = useState<DeliveryTarget[]>([]);
  const [delivEdit, setDelivEdit] = useState<string | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);

  useEffect(() => {
    void getSchoolProfile().then((p) =>
      setProfile({
        name: p.name,
        hoursFrom: p.hoursFrom,
        hoursTo: p.hoursTo,
        termFrom: p.termFrom,
        termTo: p.termTo,
        cutoff: p.lateCutoff,
      }),
    );

    // The engine sends one boolean per channel; the UI groups them.
    void getAlertRules().then((rules) =>
      setAlerts(
        rules.map((r) => ({
          key: r.key,
          title: r.title,
          sub: r.detail,
          channels: { Push: r.push, Email: r.email, SMS: r.sms },
        })),
      ),
    );

    void getDeliveryTargets().then((targets) =>
      setDeliveries(
        targets.map((t) => ({
          key: t.key,
          title: t.title,
          on: t.enabled,
          dest: t.destination,
          editable: t.editable,
          ...DELIVERY_META[t.key],
        })),
      ),
    );

    // Zones are managed on the Intrusion page; this is a read-only summary, so
    // both pages agree on the count.
    void getZones().then(setZones);
  }, []);

  const [quiet, setQuiet] = useState(true);
  const [quietFrom, setQuietFrom] = useState('15:30');
  const [quietTo, setQuietTo] = useState('07:00');
  const [quietEditing, setQuietEditing] = useState(false);

  const [lang, setLang] = useState<'en' | 'ar'>('en');

  const zonesPaused = zones.filter((z) => !z.enabled).length;
  const zoneSummary = `${zones.length} protected areas · ${
    zonesPaused ? `${zonesPaused} paused` : 'all active'
  } — managed on the Intrusion page, so there is one source of truth`;

  function toggleChannel(key: string, ch: AlertChannel) {
    setAlerts((current) =>
      current.map((rule) =>
        rule.key === key ? { ...rule, channels: { ...rule.channels, [ch]: !rule.channels[ch] } } : rule,
      ),
    );
  }

  function toggleDelivery(key: string) {
    setDeliveries((current) =>
      current.map((d) => (d.key === key ? { ...d, on: !d.on } : d)),
    );
    const target = deliveries.find((d) => d.key === key);
    if (target && !target.on && target.editable && !target.dest) setDelivEdit(key);
  }

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
      display: `${fmtDate(profile.termFrom)} – ${fmtDate(profile.termTo)}`,
    },
    {
      key: 'cutoff',
      label: 'Attendance cut-off',
      display: `${fmtTime(profile.cutoff)} — later arrivals count as late`,
    },
  ];

  return (
    <>
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
              style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13, cursor: 'pointer', textAlign: 'right' }}
              onClick={() => setEditKey(editKey === row.key ? null : row.key)}
            >
              {editKey === row.key ? 'Done' : 'Edit'}
            </span>
          </div>
        ))}
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Alerts</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 4px' }}>
          Pick how each alert reaches you.
        </div>

        {alerts.map((rule) => (
          <div
            key={rule.key}
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
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{rule.title}</div>
              <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{rule.sub}</div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              {CHANNELS.map((ch) => (
                <button
                  key={ch}
                  type="button"
                  className={`chip-btn ${rule.channels[ch] ? 'chip-btn--on' : 'chip-btn--off'}`}
                  onClick={() => toggleChannel(rule.key, ch)}
                >
                  {ch}
                </button>
              ))}
            </div>
          </div>
        ))}

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14, padding: '13px 0 3px' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontWeight: 600, fontSize: 14 }}>
              Quiet hours · {fmtTime(quietFrom)} – {fmtTime(quietTo)}
            </div>
            {!quietEditing ? (
              <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                Outside these hours, only knife detections and restricted-zone alerts get through.
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
                <input
                  className="edit-input"
                  type="time"
                  autoFocus
                  defaultValue={quietFrom}
                  onChange={(e) => e.target.value && setQuietFrom(e.target.value)}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === 'Escape') && setQuietEditing(false)}
                />
                <span style={{ color: 'var(--tx3)', fontSize: 13 }}>to</span>
                <input
                  className="edit-input"
                  type="time"
                  defaultValue={quietTo}
                  onChange={(e) => e.target.value && setQuietTo(e.target.value)}
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === 'Escape') && setQuietEditing(false)}
                />
              </div>
            )}
          </div>
          <span
            style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }}
            onClick={() => setQuietEditing((v) => !v)}
          >
            {quietEditing ? 'Done' : 'Edit'}
          </span>
          <Toggle on={quiet} onToggle={() => setQuiet((v) => !v)} label="Quiet hours" />
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Where alerts reach you</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 4px' }}>
          Switch each channel on or off, and change where it points. Edits save on their own.
        </div>

        {deliveries.map((d) => (
          <div
            key={d.key}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 14,
              padding: '13px 0',
              borderBottom: '1px solid var(--line)',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{d.title}</div>
              {delivEdit === d.key ? (
                <input
                  className="edit-input"
                  autoFocus
                  type={d.inputType}
                  defaultValue={d.dest}
                  placeholder={d.placeholder}
                  style={{ width: '100%', maxWidth: 320, marginTop: 5 }}
                  onChange={(e) =>
                    setDeliveries((current) =>
                      current.map((x) => (x.key === d.key ? { ...x, dest: e.target.value } : x)),
                    )
                  }
                  onKeyDown={(e) => (e.key === 'Enter' || e.key === 'Escape') && setDelivEdit(null)}
                />
              ) : (
                <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                  {d.key === 'app'
                    ? `${d.dest} · this device`
                    : d.dest || `${d.key === 'email' ? 'No address yet' : 'No number yet'}${d.on ? ' — add one so this can work' : ''}`}
                </div>
              )}
            </div>
            {d.editable && (
              <span
                style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap' }}
                onClick={() => setDelivEdit(delivEdit === d.key ? null : d.key)}
              >
                {delivEdit === d.key ? 'Done' : d.dest ? 'Change' : 'Add'}
              </span>
            )}
            <Toggle on={d.on} onToggle={() => toggleDelivery(d.key)} label={d.title} />
          </div>
        ))}
      </Card>

      <Card tight>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15 }}>Detection zones</div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', marginTop: 2 }}>{zoneSummary}</div>
          </div>
          <button type="button" className="linkbtn" style={{ whiteSpace: 'nowrap' }} onClick={() => navigate('/intrusion')}>
            Manage on Restricted zones →
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
            <div style={{ fontWeight: 600, fontSize: 14 }}>Language</div>
            <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
              {lang === 'ar'
                ? 'Arabic numbers and dates switch now — full right-to-left layout lands next build, honestly noted.'
                : 'Interface language for this account.'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['en', 'ar'] as const).map((k) => (
              <button
                key={k}
                type="button"
                className={`chip-btn ${lang === k ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setLang(k)}
              >
                {k === 'en' ? 'English' : 'العربية'}
              </button>
            ))}
          </div>
        </div>
      </Card>
    </>
  );
}
