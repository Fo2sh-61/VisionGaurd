import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Badge, Card, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getGroups, getPeople, removePerson } from '@/services/api';
import type { DirectoryPerson, GroupSummary, PersonType } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';

const TABS: { key: PersonType | 'All'; label: string }[] = [
  { key: 'All', label: 'All' },
  { key: 'Student', label: 'Students' },
  { key: 'Staff', label: 'Staff' },
  { key: 'Visitor', label: 'Visitors' },
];

/** What one tab calls the thing it is counting. Singular/plural is decided
 *  against the real number, so "1 students" cannot happen. */
const NOUN: Record<PersonType | 'All', [one: string, many: string]> = {
  All: ['person', 'people'],
  Student: ['student', 'students'],
  Staff: ['staff member', 'staff'],
  Visitor: ['visitor', 'visitors'],
};

const NO_PEOPLE: DirectoryPerson[] = [];
const NO_GROUPS: GroupSummary[] = [];

export function People() {
  const capability = useCapability('people');
  const navigate = useNavigate();
  // A hint for the interface, never a permission: the engine refuses a
  // non-administrator whatever this console decides to draw.
  const isAdmin = useAccount().role === 'admin';
  const [tab, setTab] = useState<PersonType | 'All'>('All');
  const [query, setQuery] = useState('');
  // Which row is mid-confirmation, and what the last removal said if it failed.
  const [confirming, setConfirming] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const {
    data: people, error: peopleError, loading: peopleLoading, reload: reloadPeople,
  } = useAsync(() => getPeople(), [], NO_PEOPLE);
  const {
    data: groups, error: groupsError, loading: groupsLoading, reload: reloadGroups,
  } = useAsync(() => getGroups(), [], NO_GROUPS);

  /** The row is the link. History works for staff and visitors exactly as it
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

  // The heading used to come from a hard-coded table - "2,118 people",
  // "1,742 students" - which the page printed whatever the engine returned,
  // including when it returned nothing or failed outright. It is now counted
  // from the rows actually on screen, and says nothing at all until they are
  // there. A directory that invents its own size is exactly the fixture the
  // constitution forbids.
  const known = !peopleLoading && !peopleError;
  const [one, many] = NOUN[tab];
  const counted = filtered.length === 1 ? `1 ${one}` : `${filtered.length} ${many}`;
  const heading = !known
    ? peopleError ? 'People' : 'Counting…'
    : counted + (query.trim() ? ` · matching “${query.trim()}”` : '');

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={peopleError} onRetry={reloadPeople} what="the people directory" />
      <LoadError error={removeError} what="that removal" />
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
          Click anyone to see their history. A face on file is what lets the
          cameras recognise someone at the gates.
        </div>

        {filtered.map((p) => (
          <div
            key={p.id || p.name}
            className="row row--click"
            role="button"
            tabIndex={0}
            aria-label={`Open ${p.name}`}
            onClick={() => openHistory(p)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openHistory(p);
              }
            }}
            style={{ gridTemplateColumns: '1.5fr .7fr 1.4fr 1.5fr .9fr .9fr' }}
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
                {p.type}
              </Badge>
            </span>
            {/* What the cameras can actually do with this person, in a
                sentence. "Photo on file" said the same thing in words nobody
                could act on. */}
            <span style={{ fontSize: 13, lineHeight: 1.35, color: p.photoOnFile ? 'var(--tx2)' : 'var(--am)' }}>
              {p.recognition}
              {p.sub && p.enrolled && (
                <>
                  <br />
                  <span style={{ color: 'var(--tx3)', fontSize: 12.5 }}>{p.enrolled}</span>
                </>
              )}
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
                  navigate('/track', { state: { autoRun: true, presetPerson: p.name } });
                }}
              >
                Track today
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
                  Remove
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
                <span>
                  Remove <strong>{p.name}</strong>? This deletes their face data.
                  The cameras will no longer recognise them, and this cannot be
                  undone.
                </span>
                <button
                  type="button"
                  className="chip-btn chip-btn--on"
                  disabled={removing}
                  onClick={(e) => {
                    e.stopPropagation();
                    void remove(p);
                  }}
                >
                  {removing ? 'Removing…' : 'Remove'}
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
                  Cancel
                </button>
              </span>
            )}
          </div>
        ))}

        {peopleLoading && <Empty>Loading the directory…</Empty>}
        {peopleError && !peopleLoading && (
          <Empty>Nobody is listed, because the directory could not be loaded.</Empty>
        )}
        {known && filtered.length === 0 && (
          <Empty>
            {query.trim()
              ? 'Nobody matches that name.'
              : people.length === 0
                ? 'The directory is empty. Nobody has been added yet.'
                : `No ${many} in the directory.`}
          </Empty>
        )}
      </Card>

      <Card>
        <div style={{ fontWeight: 700, fontSize: 15 }}>Groups &amp; grades</div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 6px' }}>
          Everyone holds the whole school. A grade or a group is something extra on
          top, so these rows overlap and do not add up to the roll. Open one to see
          who is in it — attendance and counting can answer for any of them.
        </div>
        <LoadError error={groupsError} onRetry={reloadGroups} what="the group list" />
        {groupsLoading && <Empty>Loading groups…</Empty>}
        {!groupsLoading && !groupsError && groups.length === 0 && (
          <Empty>No groups have been set up yet.</Empty>
        )}
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
