import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, toneGlyph } from '@/components/ui';
import { getGroup } from '@/services/api';
import type { GroupMember, GroupSummary } from '@/types';

export function PeopleGroup() {
  const { name = '' } = useParams();
  const navigate = useNavigate();
  const [summary, setSummary] = useState<GroupSummary | null>(null);
  const [roster, setRoster] = useState<GroupMember[]>([]);

  useEffect(() => {
    void getGroup(decodeURIComponent(name)).then((r) => {
      setSummary(r.summary);
      setRoster(r.roster);
    });
  }, [name]);

  if (!summary) return null;

  return (
    <div className="screen">
      <div className="tool-header" style={{ padding: 0 }}>
        <button type="button" className="tool-header__back" onClick={() => navigate('/people')}>
          ‹
        </button>
        <div className="tool-header__title">{summary.name}</div>
      </div>
      <p className="screen__lead" style={{ marginTop: 10 }}>
        {summary.count} · {summary.here} on campus today
      </p>

      <div className="card" style={{ padding: '4px 16px' }}>
        {roster.map((m) => (
          <button
            key={m.name}
            type="button"
            className="row row--pressable"
            onClick={() => navigate(`/people/history/${encodeURIComponent(m.name)}`, { state: { from: 'group', groupName: summary.name } })}
          >
            <div className="avatar">
              {m.name
                .split(' ')
                .map((w) => w[0])
                .slice(0, 2)
                .join('')}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="row__name">{m.name}</div>
              <div className="row__sub">{m.sub}</div>
            </div>
            {/* The design shows just the state here — the exact arrival time
                lives on the person's history screen, not in a list badge. */}
            <Badge tone={m.tone}>
              {toneGlyph[m.tone]} {m.status.split(' · ')[0]}
            </Badge>
          </button>
        ))}
      </div>
    </div>
  );
}
