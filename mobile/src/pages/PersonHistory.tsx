import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Badge, DataNotice, Empty, LoadError, Stats } from '@/components/ui';
import { useLanguage, useT } from '@/app/LanguageContext';
import { usePageTitle } from '@/app/PageChrome';
import { useAccount } from '@/app/AuthContext';
import { getHistory, getPeople, removePerson } from '@/services/api';
import type { DirectoryPerson, PersonHistory as PersonHistoryData } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import type { MessageKey } from '@/i18n';

/** A person's page, laid out for a phone (spec 015, P13-FR-053).
 *
 *  Built from `web/src/pages/PersonHistory.tsx`: the same call, the same
 *  heading, stats, day-by-day bars and follow-up flags, the same three
 *  loading/error/empty states.
 *
 *  The console's back link carried its own target (`state.from`,
 *  `state.groupName`) because a plain `<a href>` has no history to return to.
 *  The phone's `ScreenHeader` already returns to whatever screen opened this
 *  one - People or a group - through the router's own history index (`tabs.ts`
 *  / `ScreenHeader.tsx`), and falls back to `/people` exactly as the console's
 *  default did when there is none. So the back link is not rebuilt here; the
 *  frame around every screen already does its job.
 *
 *  Track today and Remove are new on this screen (contract: "taken from the
 *  People row") - the same two actions People.tsx offers per row, reading the
 *  same directory to find this person's id for `removePerson`.
 *
 *  No camera picture is drawn here — there never was one on the console's
 *  version either, and this screen must never be the one place identity leaks
 *  in over the confirmed-people screen. A photo grid was in the approved
 *  design; the engine keeps no images once a face is embedded (see Enrol's own
 *  comment), so it cannot be shown honestly and is left out (gap). */

const NO_PEOPLE: DirectoryPerson[] = [];

function initials(name: string): string {
  return name.split(' ').map((w) => w[0]).filter(Boolean).slice(0, 2).join('').toUpperCase();
}

export function PersonHistory() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('attendance');
  const { name = '' } = useParams();
  const navigate = useNavigate();
  const person = decodeURIComponent(name);
  const isAdmin = useAccount().role === 'admin';

  usePageTitle(person);

  const { data: history, error, loading, reload } = useAsync<PersonHistoryData | null>(
    () => getHistory(person, language),
    [person, language],
    null,
  );

  // The same directory People.tsx reads, so Remove can find this person's id
  // — PersonHistory's own call has no id in it at all.
  const { data: people } = useAsync(() => getPeople(language), [language], NO_PEOPLE);
  const directoryPerson = people.find((p) => p.name === person) ?? null;

  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  async function remove() {
    if (!directoryPerson) return;
    setRemoving(true);
    setRemoveError(null);
    try {
      await removePerson(directoryPerson.id);
      // Nothing on this page would still be true, so this is the one screen
      // where continuing to render it after success would be the dishonest
      // choice — back to the directory the removal actually changed.
      navigate('/people', { replace: true });
    } catch (err) {
      setRemoveError(
        err instanceof Error ? err.message : `${person} could not be removed.`,
      );
    } finally {
      setRemoving(false);
    }
  }

  const actions = (
    <div className="stack">
      <div className="btnrow">
        <button
          type="button"
          className="btn"
          onClick={() => navigate('/track', { state: { autoRun: true, presetPerson: person } })}
        >
          Track today
        </button>
        {/* Hidden once confirming, so only the confirmation panel's
            Remove/Cancel pair shows (mirrors People.tsx's per-row gating,
            web/src/pages/People.tsx:211). */}
        {isAdmin && !confirming && (
          <button
            type="button"
            className="btn btn--danger-outline"
            disabled={!directoryPerson}
            onClick={() => {
              setRemoveError(null);
              setConfirming(true);
            }}
          >
            Remove
          </button>
        )}
      </div>
      <LoadError error={removeError} what="load.removal" />
      {isAdmin && confirming && (
        <div className="notice notice--bad" style={{ flexDirection: 'column', gap: 10 }}>
          <span>
            Remove <strong>{person}</strong>? This deletes their face data.
            The cameras will no longer recognise them, and this cannot be
            undone.
          </span>
          <div className="btnrow">
            <button
              type="button"
              className="btn btn--danger btn--sm"
              disabled={removing}
              onClick={() => void remove()}
            >
              {t(removing ? 'people.removing' : 'action.remove')}
            </button>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              disabled={removing}
              onClick={() => setConfirming(false)}
            >
              {t('action.cancel')}
            </button>
          </div>
        </div>
      )}
    </div>
  );

  // Previously `if (!history) return null` on the console, which meant a
  // failed request drew an empty page with nothing on it. This screen still
  // has a title (from the URL, via `usePageTitle` above) and a way back (the
  // header) even when nothing loaded, so the same is kept here.
  if (!history) {
    return (
      <>
        <DataNotice capability={capability} />
        <LoadError error={error} onRetry={reload} what="load.personHistory" whatArgs={{ person }} />
        <div className="stack" style={{ alignItems: 'center', textAlign: 'center' }}>
          <span className="avatar avatar--lg" aria-hidden="true">{initials(person)}</span>
          <div style={{ fontSize: 22, fontWeight: 800 }}>{person}</div>
        </div>
        {actions}
        <div className="card">
          {loading ? (
            <Empty>{t('people.loadingHistory')}</Empty>
          ) : error ? (
            <Empty>{t('people.noHistory')}</Empty>
          ) : (
            <Empty>{t('people.noHistoryFor', { person })}</Empty>
          )}
        </div>
      </>
    );
  }

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={error} onRetry={reload} what="load.personHistory" whatArgs={{ person }} />

      <div className="stack" style={{ alignItems: 'center', textAlign: 'center' }}>
        <span className="avatar avatar--lg" aria-hidden="true">{initials(history.name)}</span>
        <div style={{ fontSize: 22, fontWeight: 800 }}>{history.name}</div>
        <p className="lead" style={{ margin: 0 }}>{history.sub} · attendance this term</p>
        {directoryPerson && (
          <div className="hstack" style={{ gap: 6, justifyContent: 'center' }}>
            <Badge tone={directoryPerson.type === 'Student' ? 'good' : directoryPerson.type === 'Staff' ? 'neutral' : 'warn'}>
              {t(`person.type.${directoryPerson.type}` as MessageKey)}
            </Badge>
            <Badge tone={directoryPerson.photoOnFile ? 'good' : 'warn'}>
              {directoryPerson.recognition}
            </Badge>
          </div>
        )}
      </div>

      {actions}

      <div className="card">
        <div className="card__title">{history.heading}</div>
        <p className="card__sub">{history.lead}</p>
        <Stats items={history.stats} columns={4} />
      </div>

      <div className="sechead">
        <span className="sechead__title">Day by day</span>
      </div>
      {history.bars.map((bar) => (
        <div key={bar.date} className="card stack" style={{ gap: 8 }}>
          <div className="spread">
            <span className="li__title">{bar.day}</span>
            <span
              style={{
                fontSize: 13, fontWeight: 700,
                color: bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac2)',
              }}
            >
              {bar.label}
            </span>
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              style={{
                width: `${bar.pct}%`,
                background: bar.tone === 'bad' ? 'var(--rd)' : bar.tone === 'warn' ? 'var(--am)' : 'var(--ac)',
              }}
            />
          </div>
        </div>
      ))}
      <p className="note" style={{ margin: '0 2px' }}>
        One row per day the cameras were recording. Green is on time, amber is after the cut-off,
        red is not seen at all. Days nothing was recording are not counted either way.
      </p>

      <div className="sechead">
        <span className="sechead__title">Days that needed follow-up</span>
      </div>
      {history.flags.length === 0 && (
        <div className="card"><Empty>Nothing to follow up.</Empty></div>
      )}
      {history.flags.map((flag) => (
        <div key={`${flag.date}-${flag.badge}`} className="card stack" style={{ gap: 6 }}>
          <div className="spread">
            <span className="li__title">{flag.date}</span>
            <Badge tone={flag.tone}>{flag.badge}</Badge>
          </div>
          <span className="li__sub">{flag.detail}</span>
        </div>
      ))}
    </>
  );
}
