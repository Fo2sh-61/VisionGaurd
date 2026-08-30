import { useNavigate, useParams } from 'react-router-dom';
import { Badge, Card, DataNotice, Empty, LoadError, PageHeader, toneGlyph } from '@/components/ui';
import { getGroup } from '@/services/api';
import type { GroupMember, GroupSummary } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import { useLanguage, useT } from '@/app/LanguageContext';

interface Group {
  summary: GroupSummary | null;
  roster: GroupMember[];
}

const NO_GROUP: Group = { summary: null, roster: [] };

export function PeopleGroup() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('groups');
  const { name = '' } = useParams();
  const navigate = useNavigate();
  const group = decodeURIComponent(name);

  const { data, error, loading, reload } = useAsync<Group>(
    () => getGroup(group, language).then((r) => ({ summary: r.summary, roster: r.roster })),
    [group, language],
    NO_GROUP,
  );
  const { summary, roster } = data;

  // This page used to `return null` until the summary arrived, so a failed
  // request rendered a blank page — no title, no error, no way back. The
  // operator's own name for the group is in the URL, so there is always
  // enough to draw a page around, even when nothing loaded.
  return (
    <>
      <div style={{ marginBottom: 4 }}>
        <button type="button" className="linkbtn" onClick={() => navigate('/people')}>
          ‹ People
        </button>
      </div>
      <DataNotice capability={capability} />
      <LoadError error={error} onRetry={reload} what="load.groupRoster" whatArgs={{ group }} />
      <PageHeader
        title={summary?.name ?? group}
        lead={
          !summary
            ? loading
              ? t('people.loading')
              : t('people.rosterUnavailable')
            : summary.here === null
              ? summary.count
              : t('people.onCampusToday', {
                count: summary.count, here: summary.here,
              })
        }
      />

      <Card>
        {loading && <Empty>{t('people.loadingRoster')}</Empty>}
        {!loading && !error && roster.length === 0 && (
          <Empty>{t('people.groupEmpty')}</Empty>
        )}

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
                  state: { from: 'group', groupName: summary?.name ?? group },
                })
              }
            >
              {t('people.attendanceHistory')}{' '}
              <span className="mirror-rtl" aria-hidden="true">→</span>
            </button>
          </div>
        ))}
      </Card>
    </>
  );
}
