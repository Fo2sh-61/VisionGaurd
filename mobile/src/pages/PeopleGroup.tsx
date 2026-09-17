import { useNavigate, useParams } from 'react-router-dom';
import { Badge, DataNotice, Empty, LoadError, toneGlyph } from '@/components/ui';
import { Icon } from '@/components/Icon';
import { usePageTitle } from '@/app/PageChrome';
import { getGroup } from '@/services/api';
import type { GroupMember, GroupSummary } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import { useLanguage, useT } from '@/app/LanguageContext';

/** One group, laid out for a phone (spec 015, P13-FR-053).
 *
 *  Built from `web/src/pages/PeopleGroup.tsx`: the same call, the same
 *  summary line (never inventing an "X here of Y" figure when the engine has
 *  no `here` count for this group), the same roster, the same three states.
 *
 *  The console's own back link is not rebuilt here — `ScreenHeader` already
 *  returns to People, the same place the console's link pointed, through the
 *  router's history (see `PersonHistory.tsx`'s comment for why that is
 *  enough). The group's own name replaces the header's title once it is
 *  known; before that, the URL's own (decoded) name holds the place, exactly
 *  as the console's `PageHeader` did. */

interface Group {
  summary: GroupSummary | null;
  roster: GroupMember[];
}

const NO_GROUP: Group = { summary: null, roster: [] };

function initials(name: string): string {
  return name.split(' ').map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();
}

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

  usePageTitle(summary?.name ?? group);

  const lead = !summary
    ? loading
      ? t('people.loading')
      : t('people.rosterUnavailable')
    : summary.here === null
      ? summary.count
      : t('people.onCampusToday', { count: summary.count, here: summary.here });

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={error} onRetry={reload} what="load.groupRoster" whatArgs={{ group }} />

      <div className="card">
        <div className="card__title">{summary?.name ?? group}</div>
        <p className="card__sub" style={{ margin: '3px 0 0' }}>{lead}</p>
      </div>

      {loading && <div className="card"><Empty>{t('people.loadingRoster')}</Empty></div>}
      {!loading && !error && roster.length === 0 && (
        <div className="card"><Empty>{t('people.groupEmpty')}</Empty></div>
      )}

      {roster.length > 0 && (
        <div className="list">
          {roster.map((member) => (
            <button
              key={member.name}
              type="button"
              className="li"
              onClick={() => navigate(`/people/history/${encodeURIComponent(member.name)}`, {
                state: { from: 'group', groupName: summary?.name ?? group },
              })}
            >
              <span className="avatar" aria-hidden="true">{initials(member.name)}</span>
              <span className="li__main">
                <span className="li__title">{member.name}</span>
                <span className="li__sub">{member.sub}</span>
              </span>
              <Badge tone={member.tone} glyph={toneGlyph[member.tone]}>{member.status}</Badge>
              <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
