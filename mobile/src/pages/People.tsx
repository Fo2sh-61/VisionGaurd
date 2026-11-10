import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Badge, DataNotice, Empty, LoadError } from '@/components/ui';
import { Icon } from '@/components/Icon';
import { getGroups, getPeople, removePerson } from '@/services/api';
import type { DirectoryPerson, GroupSummary, PersonType } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/** People, laid out for a phone (spec 015, P13-FR-053).
 *
 *  Built from `web/src/pages/People.tsx`: the same directory, the same
 *  filters, the same two navigations off a row (history, Track today) and the
 *  same admin-only two-step Remove. What changed is the arrangement — a table
 *  row becomes a card, and the type tabs become a horizontal chip row so the
 *  count on each is visible without opening anything.
 *
 *  People is a tab root, so it draws its own `h1`/lead rather than a back
 *  header (`tabs.ts`), and Enrol sits beside the title the way the design
 *  shows it — a courtesy gate on top of the server's own admin check, not a
 *  replacement for it. */

const TABS: (PersonType | 'All')[] = ['All', 'Student', 'Staff', 'Visitor'];

const NO_PEOPLE: DirectoryPerson[] = [];
const NO_GROUPS: GroupSummary[] = [];

function initials(name: string): string {
  return name.split(' ').map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();
}

export function People() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('people');
  const navigate = useNavigate();
  // A hint for the interface, never a permission: the engine refuses a
  // non-administrator whatever this app decides to draw.
  const isAdmin = useAccount().role === 'admin';
  const [tab, setTab] = useState<PersonType | 'All'>('All');
  // Ask and the bell land here with the question resolved — a link nothing
  // reads is decoration.
  const [params] = useSearchParams();
  const [query, setQuery] = useState(params.get('query') ?? '');
  // Which row is mid-confirmation, and what the last removal said if it failed.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const {
    data: people, error: peopleError, loading: peopleLoading, reload: reloadPeople,
  } = useAsync(() => getPeople(language), [language], NO_PEOPLE);
  const {
    data: groups, error: groupsError, loading: groupsLoading, reload: reloadGroups,
  } = useAsync(() => getGroups(language), [language], NO_GROUPS);

  /** The card is the link. History works for staff and visitors exactly as it
   *  does for students — the page was the only thing gating it. */
  function openHistory(p: DirectoryPerson) {
    navigate(`/people/history/${encodeURIComponent(p.name)}`, {
      state: { from: 'people' },
    });
  }

  /** Remove someone, then re-read the directory from the engine.
   *
   *  Re-reading rather than splicing the row out locally: the engine is the
   *  one that knows whether it happened, and a list that removes the row on
   *  its own initiative would keep looking right after a failure. */
  async function remove(p: DirectoryPerson) {
    setRemoving(true);
    setRemoveError(null);
    try {
      await removePerson(p.id);
      setConfirming(null);
      reloadPeople();
      reloadGroups();
    } catch (err) {
      setRemoveError(
        err instanceof Error ? err.message : `${p.name} could not be removed.`,
      );
    } finally {
      setRemoving(false);
    }
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people.filter(
      (p) => (tab === 'All' || p.type === tab) && (!q || p.name.toLowerCase().includes(q)),
    );
  }, [people, tab, query]);

  const counts = useMemo(() => {
    const byType: Record<PersonType | 'All', number> = {
      All: people.length, Student: 0, Staff: 0, Visitor: 0,
    };
    for (const p of people) byType[p.type] += 1;
    return byType;
  }, [people]);

  // The heading used to come from a hard-coded table - "2,118 people",
  // "1,742 students" - which printed whatever the engine returned, including
  // when it returned nothing or failed outright. It is counted from the rows
  // actually on screen instead, and says nothing at all until they are there.
  const known = !peopleLoading && !peopleError;
  const counted = filtered.length === 1
    ? t(`people.countOne.${tab}` as MessageKey)
    : t(`people.count.${tab}` as MessageKey, { count: filtered.length });
  const heading = !known
    ? peopleError ? t('people.title') : t('people.counting')
    : query.trim()
      ? t('people.matching', { counted, query: query.trim() })
      : counted;

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={peopleError} onRetry={reloadPeople} what="load.peopleDirectory" />
      <LoadError error={removeError} what="load.removal" />

      <div className="spread" style={{ alignItems: 'flex-end' }}>
        <div>
          <h1 className="h1">{t('people.title')}</h1>
          <p className="lead">{t('people.lead')}</p>
        </div>
        {isAdmin && (
          <button type="button" className="btn btn--sm" onClick={() => navigate('/people/enrol')}>
            <Icon name="plus" size={18} />
            Enrol a face
          </button>
        )}
      </div>

      <input
        className="input"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t('people.searchByName')}
        aria-label={t('people.searchByName')}
        enterKeyHint="search"
      />

      <div className="chips">
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            className={tab === key ? 'chip chip--on' : 'chip'}
            aria-pressed={tab === key}
            onClick={() => setTab(key)}
          >
            <span>{t(`people.tab.${key}` as MessageKey)}</span>
            <span className="chip__n">{counts[key]}</span>
          </button>
        ))}
      </div>

      <div className="sechead">
        <span className="sechead__title">{heading}</span>
      </div>
      {/* "Click" on the console became "Tap" here — the same fact, said for a
          finger instead of a mouse. */}
      <p className="note" style={{ margin: '0 2px' }}>
        Tap anyone to see their history. A face on file is what lets the
        cameras recognise someone at the gates.
      </p>

      {peopleLoading && <div className="card"><Empty>{t('people.loadingDirectory')}</Empty></div>}
      {peopleError && !peopleLoading && (
        <div className="card"><Empty>{t('people.notListed')}</Empty></div>
      )}
      {known && filtered.length === 0 && (
        <div className="card">
          <Empty>
            {query.trim()
              ? t('people.noMatch')
              : people.length === 0
                ? t('people.empty')
                : t('people.noneOfType', {
                  noun: t(`people.noun.${tab}` as MessageKey),
                })}
          </Empty>
        </div>
      )}

      {filtered.map((p) => (
        <div key={p.id || p.name} className="card stack" style={{ gap: 10 }}>
          <button
            type="button"
            className="hstack"
            style={{
              background: 'none', border: 0, padding: 0, textAlign: 'start',
              width: '100%', minHeight: 44, cursor: 'pointer', color: 'inherit', font: 'inherit',
            }}
            aria-label={t('people.open', { name: p.name })}
            onClick={() => openHistory(p)}
          >
            <span className="avatar" aria-hidden="true">{initials(p.name)}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span className="hstack" style={{ gap: 8 }}>
                <span className="li__title">{p.name}</span>
                <Badge tone={p.type === 'Student' ? 'good' : p.type === 'Staff' ? 'neutral' : 'warn'}>
                  {t(`person.type.${p.type}` as MessageKey)}
                </Badge>
              </span>
              {/* The subtitle is whichever the engine sent: a group/detail
                  string, or - when there is neither - the enrolment date.
                  Folding this into one fallback (rather than always reading
                  `p.sub`) is what keeps an enrolled-but-ungrouped person's
                  date from silently vanishing. */}
              <span className="li__sub" style={{ display: 'block' }}>{p.sub || p.enrolled}</span>
            </span>
            <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
          </button>

          {/* What the cameras can actually do with this person, in a
              sentence. "Photo on file" said the same thing in words nobody
              could act on. */}
          <p className="li__sub" style={{ margin: 0, color: p.photoOnFile ? undefined : 'var(--am)' }}>
            {p.recognition}
            {p.sub && p.enrolled && ` · ${p.enrolled}`}
          </p>
          {/* "Not seen yet" is a fact, and it is written as one. */}
          <p className="li__sub" style={{ margin: 0 }}>{p.lastSeen}</p>
          {/* Blank when nothing is recording attendance — an empty register
              is not the same claim as everybody being absent. */}
          {p.today && <div><Badge tone={p.todayTone}>{p.today}</Badge></div>}

          <div className="btnrow">
            <button
              type="button"
              className="btn btn--soft btn--sm"
              onClick={() => navigate('/track', { state: { autoRun: true, presetPerson: p.name } })}
            >
              Track today
            </button>
            {/* Administrators only. Two steps, with the consequence written
                out — removal is rare and deliberate, and there is no undo.
                Hidden once confirming for this row, so exactly one
                Remove-related control shows at a time (web/src/pages/People.tsx:211). */}
            {isAdmin && confirming !== p.id && (
              <button
                type="button"
                className="btn btn--danger-outline btn--sm"
                onClick={() => {
                  setRemoveError(null);
                  setConfirming(p.id);
                }}
              >
                Remove
              </button>
            )}
          </div>

          {isAdmin && confirming === p.id && (
            <div className="notice notice--bad" style={{ flexDirection: 'column', gap: 10 }}>
              <span>
                Remove <strong>{p.name}</strong>? This deletes their face data.
                The cameras will no longer recognise them, and this cannot be
                undone.
              </span>
              <div className="btnrow">
                <button
                  type="button"
                  className="btn btn--danger btn--sm"
                  disabled={removing}
                  onClick={() => void remove(p)}
                >
                  {t(removing ? 'people.removing' : 'action.remove')}
                </button>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  disabled={removing}
                  onClick={() => setConfirming(null)}
                >
                  {t('action.cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      ))}

      <div className="sechead">
        <span className="sechead__title">{t('people.groupsTitle')}</span>
      </div>
      <p className="note" style={{ margin: '0 2px' }}>{t('people.groupsLead')}</p>
      <LoadError error={groupsError} onRetry={reloadGroups} what="load.groupList" />
      {groupsLoading && <div className="card"><Empty>{t('people.loadingGroups')}</Empty></div>}
      {!groupsLoading && !groupsError && groups.length === 0 && (
        <div className="card"><Empty>{t('people.noGroups')}</Empty></div>
      )}
      {groups.length > 0 && (
        <div className="list">
          {groups.map((g) => (
            <button
              key={g.name}
              type="button"
              className="li"
              onClick={() => navigate(`/people/groups/${encodeURIComponent(g.name)}`)}
            >
              <span className="icontile" aria-hidden="true"><Icon name="people" /></span>
              <span className="li__main">
                <span className="li__title">{g.name}</span>
                <span className="li__sub">{g.count}</span>
              </span>
              <span className="li__chev"><Icon name="chevron" size={18} mirror /></span>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
