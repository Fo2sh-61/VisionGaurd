import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select } from '@/components/ui';
import { getGroups, getPeople, removePerson } from '@/services/api';
import type { DirectoryPerson, GroupSummary, PersonType } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import { useToday } from '@/app/SiteContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

const TABS: (PersonType | 'All')[] = ['All', 'Student', 'Staff', 'Visitor'];

/** The engine's group that holds everyone. A filter on it is no filter. */
const EVERYONE = 'Everyone';

/* What one tab calls the thing it is counting used to be a table of English
   nouns here, with singular and plural picked against the real number so
   "1 students" could not happen. Both forms now live in the catalogue as
   `people.count.*` and `people.countOne.*` — Arabic does not split the same
   way English does, and the noun cannot be glued on afterwards. */

const NO_PEOPLE: DirectoryPerson[] = [];
const NO_GROUPS: GroupSummary[] = [];

export function People() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('people');
  const navigate = useNavigate();
  // A hint for the interface, never a permission: the engine refuses a
  // non-administrator whatever this console decides to draw.
  const isAdmin = useAccount().role === 'admin';
  const [tab, setTab] = useState<PersonType | 'All'>('All');
  // Ask lands here with the question resolved. See Attendance for why
  // reading these matters: a link nothing reads is decoration.
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get('query') ?? '');
  // `/people?group=` is where a group card leads.
  const [group, setGroup] = useState(params.get('group') ?? '');
  const today = useToday();
  useEffect(() => { setGroup(params.get('group') ?? ''); }, [params]);

  function chooseGroup(next: string) {
    setGroup(next);
    const copy = new URLSearchParams(params);
    if (next) copy.set('group', next); else copy.delete('group');
    setParams(copy, { replace: true });
  }
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

  /** The row is the link. History works for staff and visitors exactly as it
   *  does for students — the page was the only thing gating it. */
  function openHistory(p: DirectoryPerson) {
    navigate(`/attendance?person=${encodeURIComponent(p.id)}&date=${encodeURIComponent(today)}`);
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

  // Real counts, from the rows the engine sent; the Student chip exists only
  // when somebody is one.
  const counts = useMemo(() => {
    const c: Record<PersonType | 'All', number> = { All: people.length, Student: 0, Staff: 0, Visitor: 0 };
    for (const p of people) c[p.type] += 1;
    return c;
  }, [people]);
  const tabs = TABS.filter((key) => key !== 'Student' || counts.Student > 0);
  const groupNames = useMemo(
    () => groups.map((g) => g.name).filter((n) => n !== EVERYONE),
    [groups],
  );
  const groupOptions = useMemo(() => {
    const names = ['', ...groupNames];
    return group && !names.includes(group) ? [...names, group] : names;
  }, [groupNames, group]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return people.filter(
      (p) => (tab === 'All' || p.type === tab)
        && (!group || group === EVERYONE || p.group === group)
        && (!q || p.name.toLowerCase().includes(q)),
    );
  }, [people, tab, query, group]);

  // The heading used to come from a hard-coded table - "2,118 people",
  // "1,742 students" - which the page printed whatever the engine returned,
  // including when it returned nothing or failed outright. It is now counted
  // from the rows actually on screen, and says nothing at all until they are
  // there. A directory that invents its own size is exactly the fixture the
  // constitution forbids.
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
      <PageHeader
        title={t('people.title')}
        lead={t('people.lead')}
      />

      <Card tight>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <input
            className="input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t('people.searchByName')}
            style={{ flex: 1, minWidth: 200, height: 44, borderRadius: 11, fontSize: 14.5 }}
          />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {tabs.map((key) => (
              <button
                key={key}
                type="button"
                className={`chip-btn ${tab === key ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setTab(key)}
              >
                {t('people.chipLabel', {
                  label: t(`people.tab.${key}` as MessageKey), count: counts[key],
                })}
              </button>
            ))}
          </div>
          <Field label={t('people.groupFilter')}>
            <Select
              value={group}
              onChange={chooseGroup}
              options={groupOptions}
              label={(o) => (o === '' ? t('people.allGroups') : o)}
            />
          </Field>
          <button
            type="button"
            className="chip-btn chip-btn--on"
            onClick={() => navigate('/people/enrol')}
          >
            {t('attendance.enrolFace')}
          </button>
        </div>
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.01em' }}>{heading}</div>
        <div style={{ fontSize: 13.5, color: 'var(--tx2)', margin: '2px 0 10px' }}>
          {known && t('people.showing', { shown: filtered.length, total: people.length })}
        </div>

        {filtered.map((p) => (
          <div
            key={p.id || p.name}
            className="row row--click"
            role="button"
            tabIndex={0}
            aria-label={t('people.open', { name: p.name })}
            onClick={() => openHistory(p)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openHistory(p);
              }
            }}
            style={{ gridTemplateColumns: '1.5fr .7fr .9fr 1.4fr 1.4fr .9fr 1fr' }}
          >
            <span>
              <span className="row__name">{p.name}</span>
              <br />
              <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                {p.sub || p.enrolled}
              </span>
            </span>
            <span>
              <Badge tone={p.type === 'Student' ? 'good' : p.type === 'Staff' ? 'neutral' : 'warn'}>
                {t(`person.type.${p.type}` as MessageKey)}
              </Badge>
            </span>
            <span style={{ fontSize: 13, color: 'var(--tx2)' }}>{p.group}</span>
            {/* What the cameras can actually do with this person: how many
                faces are on file, or plainly that they cannot be recognised. */}
            <span style={{ fontSize: 13, lineHeight: 1.35, color: p.photoOnFile ? 'var(--tx2)' : 'var(--am)' }}>
              {p.photoOnFile
                ? t(p.photos === 1 ? 'people.facesOne' : 'people.faces', { count: p.photos })
                : t('people.cannotBeRecognised')}
            </span>
            {/* "Not seen yet" is a fact, and it is written as one. */}
            <span style={{ color: 'var(--tx2)', fontSize: 13, lineHeight: 1.35 }}>
              {p.lastSeen}
            </span>
            {/* Blank when nothing is recording attendance — an empty register
                is not the same claim as everybody being absent. */}
            <span>
              {p.today ? <Badge tone={p.todayTone}>{p.today}</Badge> : null}
            </span>
            <span style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <button
                type="button"
                className="linkbtn"
                onClick={(e) => {
                  e.stopPropagation();
                  openHistory(p);
                }}
              >
                {t('people.history')}
              </button>
              {/* Administrators only. Two steps, with the consequence written
                  out — removal is rare and deliberate, and there is no undo. */}
              {isAdmin && confirming !== p.id && (
                <button
                  type="button"
                  className="linkbtn"
                  style={{ color: 'var(--rd)' }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setRemoveError(null);
                    setConfirming(p.id);
                  }}
                >
                  {t('action.remove')}
                </button>
              )}
            </span>
            {isAdmin && confirming === p.id && (
              <span
                style={{
                  gridColumn: '1 / -1',
                  display: 'flex',
                  gap: 10,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  fontSize: 13,
                  color: 'var(--rd)',
                  marginTop: 6,
                }}
                onClick={(e) => e.stopPropagation()}
              >
                <span>{t('people.removeSentence', { name: p.name })}</span>
                <button
                  type="button"
                  className="chip-btn chip-btn--on"
                  disabled={removing}
                  onClick={(e) => {
                    e.stopPropagation();
                    void remove(p);
                  }}
                >
                  {t(removing ? 'people.removing' : 'action.remove')}
                </button>
                <button
                  type="button"
                  className="chip-btn chip-btn--off"
                  disabled={removing}
                  onClick={(e) => {
                    e.stopPropagation();
                    setConfirming(null);
                  }}
                >
                  {t('action.cancel')}
                </button>
              </span>
            )}
          </div>
        ))}

        {peopleLoading && <Empty>{t('people.loadingDirectory')}</Empty>}
        {peopleError && !peopleLoading && (
          <Empty>{t('people.notListed')}</Empty>
        )}
        {known && filtered.length === 0 && (
          <Empty>
            {query.trim()
              ? t('people.noMatch')
              : people.length === 0
                ? t('people.empty')
                : t('people.noneOfType', {
                  noun: t(`people.noun.${tab}` as MessageKey),
                })}
          </Empty>
        )}
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{t('people.groupsTitle')}</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          {t('people.groupsLead')}
        </div>
        <LoadError error={groupsError} onRetry={reloadGroups} what="load.groupList" />
        {groupsLoading && <Empty>{t('people.loadingGroups')}</Empty>}
        {!groupsLoading && !groupsError && groups.length === 0 && (
          <Empty>{t('people.noGroups')}</Empty>
        )}
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))' }}>
          {groups.map((g) => (
            <button
              key={g.name}
              type="button"
              className="list-row"
              style={{ display: 'block', textAlign: 'start', padding: 14, border: '1px solid var(--line)', borderRadius: 12 }}
              onClick={() => chooseGroup(g.name === EVERYONE ? '' : g.name)}
            >
              <div className="row__name">{g.name === EVERYONE ? t('attendance.everyone') : g.name}</div>
              <div style={{ color: 'var(--tx2)', fontSize: 13, marginTop: 4 }}>{g.count}</div>
              <div style={{ color: 'var(--tx2)', fontSize: 13 }}>
                {g.here === null
                  ? t('people.cardHereUnknown')
                  : t('people.cardHere', { count: g.here })}
              </div>
              {/* The figure with the days it rests on, or "no data": never a
                  0% for a period nothing was watching. */}
              <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4 }}>{g.attendance}</div>
              <div style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13, marginTop: 6 }}>
                {t('people.seeWhoIsInIt')}{' '}
                <span className="mirror-rtl" aria-hidden="true">→</span>
              </div>
            </button>
          ))}
        </div>
        {groups.length > 0 && (
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 10 }}>
            {t('people.groupOverlap')}
          </div>
        )}
      </Card>
    </>
  );
}
