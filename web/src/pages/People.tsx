import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Card, DataNotice, PageHeader } from '@/components/ui';
import { getGroups, getPeople } from '@/services/api';
import type { DirectoryPerson, GroupSummary, PersonType } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

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
  const capability = useCapability('people');
  const navigate = useNavigate();
  const [people, setPeople] = useState<DirectoryPerson[]>([]);
  const [groups, setGroups] = useState<GroupSummary[]>([]);
  const [tab, setTab] = useState<PersonType | 'All'>('All');
  const [query, setQuery] = useState('');

  useEffect(() => {
    void getPeople().then(setPeople);
    void getGroups().then(setGroups);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people.filter(
      (p) => (tab === 'All' || p.type === tab) && (!q || p.name.toLowerCase().includes(q)),
    );
  }, [people, tab, query]);

  const heading = COUNTS[tab] + (query.trim() ? ` · matching “${query.trim()}”` : '');

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="People"
        lead="Everyone in your school — students, staff and registered visitors. Records come from the school database; this console reads them."
      />

      <Card tight>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name…"
            style={{ flex: 1, minWidth: 200, height: 44, borderRadius: 11, fontSize: 14.5 }}
          />
          <div style={{ display: 'flex', gap: 6 }}>
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                className={`chip-btn ${tab === t.key ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="chip-btn chip-btn--on"
            onClick={() => navigate('/people/enrol')}
          >
            Enrol a face
          </button>
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>{heading}</div>
        <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 10px' }}>
          A photo on file is what lets face recognition find someone at the gates.
        </div>

        {filtered.map((p) => (
          <div key={p.name} className="row" style={{ gridTemplateColumns: '1.3fr .7fr 1.2fr 1.6fr 1.3fr' }}>
            <span>
              <span className="row__name">{p.name}</span>
              <br />
              <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>{p.sub}</span>
            </span>
            <span>
              <Badge tone={p.type === 'Student' ? 'good' : p.type === 'Staff' ? 'neutral' : 'warn'}>
                {p.type}
              </Badge>
            </span>
            <span>
              <Badge tone={p.photoOnFile ? 'good' : 'warn'}>
                {p.photoOnFile ? 'Photo on file' : 'No photo yet'}
              </Badge>
            </span>
            <span style={{ color: 'var(--tx2)', fontSize: 13, lineHeight: 1.35 }}>{p.guardian}</span>
            <span style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {p.type === 'Student' && (
                <>
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() => navigate(`/people/history/${encodeURIComponent(p.name)}`, { state: { from: 'people' } })}
                  >
                    Attendance history
                  </button>
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() =>
                      navigate('/track', { state: { autoRun: true, presetPerson: p.name } })
                    }
                  >
                    Track today
                  </button>
                </>
              )}
            </span>
          </div>
        ))}

        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', padding: '30px 10px', color: 'var(--tx3)', fontSize: 13.5 }}>
            Nobody matches that name.
          </div>
        )}
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Groups &amp; grades</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          Open one to see who is in it. Attendance and counting can answer for any of these.
        </div>
        {groups.map((g) => (
          <button
            key={g.name}
            type="button"
            className="list-row"
            onClick={() => navigate(`/people/groups/${encodeURIComponent(g.name)}`)}
          >
            <span className="row__name">{g.name}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <span style={{ color: 'var(--tx2)', fontSize: 13 }}>{g.count}</span>
              <span style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13 }}>See who’s in it →</span>
            </span>
          </button>
        ))}
      </Card>
    </>
  );
}
