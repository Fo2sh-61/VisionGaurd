import { useState } from 'react';
import { useAccount, useAuth } from '@/app/AuthContext';
import { useTheme } from '@/app/ThemeContext';
import { Toggle } from '@/components/ui';
import { ALERT_RULES, DELIVERY_TARGETS, SCHOOL_NAME, SCHOOL_PROFILE } from '@/services/mockData';
import type { AlertChannel, AlertRule, DeliveryTarget, SchoolProfile } from '@/types';

const CHANNELS: AlertChannel[] = ['Push', 'Email', 'SMS'];

function fmtTime(t: string) {
  if (!t) return '';
  const [h, m] = t.split(':');
  const hour = Number(h);
  const ap = hour >= 12 ? 'pm' : 'am';
  return `${hour % 12 || 12}:${m}${ap}`;
}

function fmtDate(d: string) {
  if (!d) return '';
  return new Date(`${d}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

type ProfileKey = 'name' | 'hours' | 'term' | 'cutoff';

export function Account() {
  const account = useAccount();
  const { signOut } = useAuth();
  const { dark, toggle } = useTheme();

  const [profile, setProfile] = useState<SchoolProfile>(SCHOOL_PROFILE);
  const [editKey, setEditKey] = useState<ProfileKey | null>(null);

  const [alerts, setAlerts] = useState<AlertRule[]>(ALERT_RULES);
  const [deliveries, setDeliveries] = useState<DeliveryTarget[]>(DELIVERY_TARGETS);
  const [delivEdit, setDelivEdit] = useState<string | null>(null);

  const [quiet, setQuiet] = useState(true);
  const [quietFrom, setQuietFrom] = useState('15:30');
  const [quietTo, setQuietTo] = useState('07:00');
  const [quietEditing, setQuietEditing] = useState(false);

  const [lang, setLang] = useState<'en' | 'ar'>('en');

  function toggleChannel(key: string, ch: AlertChannel) {
    setAlerts((c) => c.map((rule) => (rule.key === key ? { ...rule, channels: { ...rule.channels, [ch]: !rule.channels[ch] } } : rule)));
  }

  function toggleDelivery(key: string) {
    const target = deliveries.find((d) => d.key === key);
    setDeliveries((c) => c.map((d) => (d.key === key ? { ...d, on: !d.on } : d)));
    if (target && !target.on && target.editable && !target.dest) setDelivEdit(key);
  }

  const profileRows: { key: ProfileKey; label: string; display: string }[] = [
    { key: 'name', label: 'School name', display: profile.name },
    { key: 'hours', label: 'School hours', display: `${fmtTime(profile.hoursFrom)} – ${fmtTime(profile.hoursTo)}` },
    { key: 'term', label: 'Term', display: `${fmtDate(profile.termFrom)} – ${fmtDate(profile.termTo)}` },
    { key: 'cutoff', label: 'Attendance cut-off', display: `${fmtTime(profile.cutoff)} — later is late` },
  ];

  return (
    <div className="screen">
      <div className="screen__title" style={{ marginBottom: 16 }}>
        Account
      </div>

      <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
        <div className="avatar" style={{ width: 46, height: 46, fontSize: 16 }}>
          {account.initials}
        </div>
        <div>
          <div style={{ fontWeight: 600, fontSize: 16 }}>{account.name}</div>
          <div style={{ fontSize: 13, color: 'var(--tx3)' }}>
            {account.role === 'admin' ? 'Administrator' : 'IT'}
            {SCHOOL_NAME && ` · ${SCHOOL_NAME}`}
          </div>
        </div>
      </div>

      <div className="section-title" style={{ margin: '24px 0 10px' }}>
        School profile
      </div>
      <div className="card" style={{ padding: '4px 18px' }}>
        {profileRows.map((row) => (
          <div key={row.key} style={{ padding: '13px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <span style={{ fontSize: 13, color: 'var(--tx2)' }}>{row.label}</span>
              <button type="button" className="linkbtn" onClick={() => setEditKey(editKey === row.key ? null : row.key)}>
                {editKey === row.key ? 'Done' : 'Edit'}
              </button>
            </div>
            {editKey !== row.key ? (
              <div style={{ fontSize: 14.5, fontWeight: 600, marginTop: 2 }} onClick={() => setEditKey(row.key)}>
                {row.display}
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
                {row.key === 'name' && (
                  <input className="input" style={{ height: 44 }} defaultValue={profile.name} onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))} />
                )}
                {row.key === 'hours' && (
                  <>
                    <input className="input" style={{ height: 44 }} type="time" defaultValue={profile.hoursFrom} onChange={(e) => e.target.value && setProfile((p) => ({ ...p, hoursFrom: e.target.value }))} />
                    <span style={{ fontSize: 13, color: 'var(--tx3)' }}>to</span>
                    <input className="input" style={{ height: 44 }} type="time" defaultValue={profile.hoursTo} onChange={(e) => e.target.value && setProfile((p) => ({ ...p, hoursTo: e.target.value }))} />
                  </>
                )}
                {row.key === 'term' && (
                  <>
                    <input className="input" style={{ height: 44 }} type="date" defaultValue={profile.termFrom} onChange={(e) => e.target.value && setProfile((p) => ({ ...p, termFrom: e.target.value }))} />
                    <span style={{ fontSize: 13, color: 'var(--tx3)' }}>to</span>
                    <input className="input" style={{ height: 44 }} type="date" defaultValue={profile.termTo} onChange={(e) => e.target.value && setProfile((p) => ({ ...p, termTo: e.target.value }))} />
                  </>
                )}
                {row.key === 'cutoff' && (
                  <input className="input" style={{ height: 44 }} type="time" defaultValue={profile.cutoff} onChange={(e) => e.target.value && setProfile((p) => ({ ...p, cutoff: e.target.value }))} />
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="section-title" style={{ margin: '24px 0 10px' }}>
        Alerts
      </div>
      <div className="card" style={{ padding: '4px 18px' }}>
        {alerts.map((rule) => (
          <div key={rule.key} style={{ padding: '14px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>{rule.title}</div>
            <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>{rule.sub}</div>
            <div style={{ display: 'flex', gap: 7, marginTop: 9 }}>
              {CHANNELS.map((ch) => (
                <button key={ch} type="button" className={`chip-btn ${rule.channels[ch] ? 'chip-btn--on' : 'chip-btn--off'}`} onClick={() => toggleChannel(rule.key, ch)}>
                  {ch}
                </button>
              ))}
            </div>
          </div>
        ))}

        <div style={{ padding: '14px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14.5 }}>
                Quiet hours · {fmtTime(quietFrom)} – {fmtTime(quietTo)}
              </div>
              <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>Outside these hours, only knife detections and restricted-zone alerts get through.</div>
            </div>
            <Toggle on={quiet} onToggle={() => setQuiet((v) => !v)} label="Quiet hours" />
          </div>
          {!quietEditing ? (
            <button type="button" className="linkbtn" style={{ marginTop: 8 }} onClick={() => setQuietEditing(true)}>
              Change quiet hours
            </button>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10 }}>
              <input className="input" style={{ height: 44 }} type="time" defaultValue={quietFrom} onChange={(e) => e.target.value && setQuietFrom(e.target.value)} />
              <span style={{ fontSize: 13, color: 'var(--tx3)' }}>to</span>
              <input className="input" style={{ height: 44 }} type="time" defaultValue={quietTo} onChange={(e) => e.target.value && setQuietTo(e.target.value)} />
              <button type="button" className="linkbtn" onClick={() => setQuietEditing(false)}>
                Done
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="section-title" style={{ margin: '24px 0 10px' }}>
        Where alerts reach you
      </div>
      <div className="card" style={{ padding: '4px 18px' }}>
        {deliveries.map((d) => (
          <div key={d.key} style={{ padding: '13px 0', borderBottom: '1px solid var(--line)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14.5 }}>{d.title}</div>
                {delivEdit !== d.key && (
                  <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>
                    {d.dest || `${d.key === 'email' ? 'No address yet' : 'No number yet'}${d.on ? ' — add one so this can work' : ''}`}
                  </div>
                )}
              </div>
              {d.editable && (
                <button type="button" className="linkbtn" onClick={() => setDelivEdit(delivEdit === d.key ? null : d.key)}>
                  {delivEdit === d.key ? 'Done' : d.dest ? 'Change' : 'Add'}
                </button>
              )}
              <Toggle on={d.on} onToggle={() => toggleDelivery(d.key)} label={d.title} />
            </div>
            {delivEdit === d.key && (
              <input
                className="input"
                style={{ height: 44, marginTop: 9 }}
                type={d.inputType}
                defaultValue={d.dest}
                placeholder={d.placeholder}
                onChange={(e) => setDeliveries((c) => c.map((x) => (x.key === d.key ? { ...x, dest: e.target.value } : x)))}
              />
            )}
          </div>
        ))}
      </div>

      <div className="section-title" style={{ margin: '24px 0 10px' }}>
        Appearance &amp; language
      </div>
      <div className="card" style={{ padding: '4px 18px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 0', borderBottom: '1px solid var(--line)' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: 14.5 }}>Dark mode</div>
            <div style={{ fontSize: 12, color: 'var(--tx3)' }}>Easier on the eyes over a long day.</div>
          </div>
          <Toggle on={dark} onToggle={toggle} label="Dark mode" />
        </div>
        <div style={{ padding: '14px 0' }}>
          <div style={{ fontWeight: 600, fontSize: 14.5 }}>Language</div>
          <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>
            {lang === 'ar' ? 'Arabic numbers and dates switch now — full right-to-left layout lands next build.' : 'Interface language for this account.'}
          </div>
          <div style={{ display: 'flex', gap: 7, marginTop: 9 }}>
            {(['en', 'ar'] as const).map((k) => (
              <button key={k} type="button" className={`chip-btn ${lang === k ? 'chip-btn--on' : 'chip-btn--off'}`} onClick={() => setLang(k)}>
                {k === 'en' ? 'English' : 'العربية'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <button type="button" onClick={signOut} style={{ display: 'block', width: '100%', textAlign: 'center', padding: '26px 0 10px', fontSize: 14, color: 'var(--rd)', fontWeight: 600, background: 'none', border: 'none', cursor: 'pointer' }}>
        Sign out
      </button>
    </div>
  );
}
