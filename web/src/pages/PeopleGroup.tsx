import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, Card, DataNotice, PageHeader, toneGlyph } from '@/components/ui';
import { getGroup } from '@/services/api';
import type { GroupMember, GroupSummary } from '@/types';
import { useCapability } from '@/app/CapabilityContext';

export function PeopleGroup() {
  const capability = useCapability('groups');
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
    <>
      <div style={{ marginBottom: 4 }}>
        <button type="button" className="linkbtn" onClick={() => navigate('/people')}>
          ‹ People
        </button>
      </div>
      <DataNotice capability={capability} />
      <PageHeader
        title={summary.name}
        lead={
          summary.here === null
            ? summary.count
            : `${summary.count} · ${summary.here} on campus today`
        }
      />

      <Card>
        {roster.map((member) => (
          <div key={member.name} className="row" style={{ gridTemplateColumns: '1.4fr 1fr 1fr 1.2fr' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <span
                style={{
                  width: 34,
                  height: 34,
                  borderRadius: '50%',
                  background: 'var(--chip)',
                  color: 'var(--ac2)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontWeight: 700,
                  fontSize: 12,
                  flexShrink: 0,
                }}
              >
                {member.name
                  .split(' ')
                  .map((w) => w[0])
                  .slice(0, 2)
                  .join('')}
              </span>
              <span className="row__name">{member.name}</span>
            </span>
            <span className="row__muted">{member.sub}</span>
            <span>
              <Badge tone={member.tone} glyph={toneGlyph[member.tone]}>
                {member.status}
              </Badge>
            </span>
            <button
              type="button"
              className="linkbtn"
              onClick={() =>
                navigate(`/people/history/${encodeURIComponent(member.name)}`, {
                  state: { from: 'group', groupName: summary.name },
                })
              }
            >
              Attendance history →
            </button>
          </div>
        ))}
      </Card>
    </>
  );
}
