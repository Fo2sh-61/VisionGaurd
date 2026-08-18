import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getGroups, getPeople } from '@/services/api';
import type { DirectoryPerson, GroupSummary, PersonType } from '@/types';

const TABS: { key: PersonType | 'All'; label: string }[] = [
  { key: 'All', label: 'All' },
  { key: 'Student', label: 'Students' },
  { key: 'Staff', label: 'Staff' },
  { key: 'Visitor', label: 'Visitors' },
];

const COUNTS: Record<PersonType | 'All', string> = {
  All: '2,118 people',
  Student: '1,742 students',
  Staff: '168 staff',
  Visitor: '12 visitors this week',
};

export function People() {
  const navigate = useNavigate();
  const [people, setPeople] = useState<DirectoryPerson[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [tab, setTab] = useState<PersonType | 'All'>('All');
  const [query, setQuery] = useState('');
  const [openName, setOpenName] = useState<string | null>(null);

  useEffect(() => {
    void getPeople().then(setPeople);
    void getGroups().then(setGroups);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people.filter((p) => (tab === 'All' || p.type === tab) && (!q || p.name.toLowerCase().includes(q)));
  }, [people, tab, query]);

  return (
    <div className="screen">
      <div className="screen__title">People</div>
      <p className="screen__lead">Students, staff and registered visitors. Records come from the school database — read-only here.</p>

      <input
        className="input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by name…"
        style={{ boxShadow: 'var(--sh)', border: 'none', marginBottom: 12 }}
      />

      <div className="chip-row" style={{ marginBottom: 8 }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`chip-btn ${tab === t.key ? 'chip-btn--on' : 'chip-btn--off'}`}
            onClick={() => {
              setTab(t.key);
              setOpenName(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginBottom: 8 }}>{COUNTS[tab]}</div>

      <div className="card" style={{ padding: '4px 16px' }}>
        {filtered.map((p) => {
          const open = openName === p.name;
          const typeTone =
            p.type === 'Student' ? { bg: 'var(--chip)', fg: 'var(--ac2)' } : p.type === 'Staff' ? { bg: 'var(--bg)', fg: 'var(--tx2)' } : { bg: 'var(--am-bg)', fg: 'var(--am)' };
          const photoTone = p.photoOnFile ? { bg: 'var(--chip)', fg: 'var(--ac2)' } : { bg: 'var(--am-bg)', fg: 'var(--am)' };

          return (
            <div key={p.name} style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
              <button
                type="button"
                className="row row--pressable"
                style={{ padding: 0, border: 'none', minHeight: 44 }}
                onClick={() => setOpenName(open ? null : p.name)}
              >
                <div className="avatar" style={{ background: typeTone.bg, color: typeTone.fg }}>
                  {p.name
                    .split(' ')
                    .map((w) => w[0])
                    .slice(0, 2)
                    .join('')}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="row__name">{p.name}</div>
                  <div className="row__sub">
                    {p.sub} · {p.attendanceToday}
                  </div>
                </div>
                <span className="row__chevron">{open ? '⌃' : '›'}</span>
              </button>

              {open && (
                <div style={{ marginTop: 12, background: 'var(--bg)', borderRadius: 13, padding: 14 }}>
                  <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: 10 }}>
                    <span className="badge" style={{ background: typeTone.bg, color: typeTone.fg }}>
                      {p.type}
                    </span>
                    <span className="badge" style={{ background: photoTone.bg, color: photoTone.fg }}>
                      {p.photoOnFile ? 'Photo on file' : 'No photo yet'}
                    </span>
                  </div>
                  {p.guardian && (
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, marginBottom: 12 }}>{p.guardian}</div>
                  )}
                  {p.type === 'Student' && (
                    <div className="stack" style={{ gap: 8 }}>
                      <button
                        type="button"
                        className="card row row--pressable"
                        style={{ padding: '12px 14px', boxShadow: 'none' }}
                        onClick={() => navigate(`/people/history/${encodeURIComponent(p.name)}`, { state: { from: 'people' } })}
                      >
                        <span style={{ fontSize: 13.5, fontWeight: 600, flex: 1 }}>Attendance history</span>
                        <span className="row__chevron">›</span>
                      </button>
                      <button
                        type="button"
                        className="card row row--pressable"
                        style={{ padding: '12px 14px', boxShadow: 'none' }}
                        onClick={() => navigate(`/tool/track`, { state: { autoRun: true } })}
                      >
                        <span style={{ fontSize: 13.5, fontWeight: 600, flex: 1 }}>
                          Track today <span style={{ fontWeight: 500, color: 'var(--tx3)' }}>· logged</span>
                        </span>
                        <span className="row__chevron">›</span>
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
        {filtered.length === 0 && <div style={{ padding: '30px 10px', textAlign: 'center', fontSize: 13.5, color: 'var(--tx3)' }}>Nobody matches that name.</div>}
      </div>

      <div className="card" style={{ padding: '4px 16px', marginTop: 12 }}>
        <div style={{ padding: '13px 0 4px', fontWeight: 700, fontSize: 14.5 }}>Groups &amp; grades</div>
        {groups.map((g) => (
          <button
            key={g.name}
            type="button"
            className="row row--pressable"
            style={{ borderTop: '1px solid var(--line)', borderBottom: 'none' }}
            onClick={() => navigate(`/people/groups/${encodeURIComponent(g.name)}`)}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row__name">{g.name}</div>
              <div className="row__sub">{g.count}</div>
            </div>
            <span className="row__chevron">›</span>
          </button>
        ))}
      </div>
    </div>
  );
}
