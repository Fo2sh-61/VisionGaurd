import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CamGrid } from '@/components/CamGrid';
import {
  Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, Toggle, toneGlyph,
} from '@/components/ui';
import { Icon } from '@/components/Icon';
import { getBreaches, getIntrusionCameras, getZones, setZoneEnabled } from '@/services/api';
import type { Breach, Camera, IntrusionWindow, Zone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import { formatCount } from '@/services/format';
import type { MessageKey } from '@/i18n';

/*  Restricted zones, laid out for a phone (spec 015, P13-FR-049).
 *
 *  Built from `web/src/pages/Intrusion.tsx`: the same calls, polls, windows,
 *  notices, empty states and wording. What changed is the arrangement: a
 *  status tile leads the screen (nobody inside / still in view), because that
 *  is the one fact worth seeing before anything else. The zone switches keep
 *  the console's own words - "Protected" / "Paused" - never the design
 *  artboard's "Watching".
 *
 *  The zone Toggle is rendered unconditionally, exactly as the console does
 *  it - not gated on role here. `/zones` writes are admin-only on the engine
 *  (`ADMIN_WRITE_PREFIXES`), and that is where the enforcement lives; a guard
 *  who presses it gets the same `toggleError` rejection the console would
 *  show. Hiding the control for a guard was tried and reverted: it made a
 *  capability visibly present on the console invisible on the phone for no
 *  console-side reason.
 *
 *  Deep links from the bell ('?scene=…') get their own highlight and "not in
 *  this window" notice via `useLinkedItem`, which the console's own copy of
 *  this page has never had (see `consoleDefects`). */

const WINDOWS: IntrusionWindow[] = ['today', 'last7', 'last30'];

/** A scene becomes watchable the moment the person leaves frame, which is a
 *  thing that happens while somebody is looking at this page rather than
 *  because they did anything. Without a poll the only way to see a new clip
 *  was to navigate away and come back. */
const LOG_REFRESH_MS = 3_000;

/** The toggles and their per-camera counts. Slower: these change when a
 *  person presses something, not on their own. */
const ZONE_REFRESH_MS = 15_000;

const NO_ZONES: Zone[] = [];
const NO_BREACHES: Breach[] = [];
const NO_CAMERAS: Camera[] = [];

export function Intrusion() {
  const { language } = useLanguage();
  const capability = useCapability('breaches');
  const t = useT();
  // Ask lands here with the question resolved.
  const [params] = useSearchParams();
  const asked = params.get('window');
  const [when, setWhen] = useState<IntrusionWindow>(
    asked === 'today' || asked === 'last7' || asked === 'last30'
      ? asked : 'today');
  // An alert lands here on one scene: `?scene=` is the one the engine named.
  const linked = useLinkedItem('scene');

  const {
    data: loadedZones, error: zonesError, loading: zonesLoading, reload: reloadZones,
  } = useAsync(() => getZones(), [], NO_ZONES, ZONE_REFRESH_MS);
  const {
    data: breaches, error: breachError, loading: breachLoading, reload: reloadBreaches,
  } = useAsync(() => getBreaches(when, language),
    [when, language], NO_BREACHES, LOG_REFRESH_MS);
  const { data: cameras } = useAsync(
    () => getIntrusionCameras(language), [language], NO_CAMERAS, ZONE_REFRESH_MS);

  // Pending toggles, laid over what the engine last told us. A camera is only
  // drawn as restricted once the engine has agreed it is.
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [toggleError, setToggleError] = useState<string | null>(null);
  // The whole entry, not just its id: the log refreshes underneath the player,
  // and an entry whose clip has just been replaced leaves the list. Looking it
  // up each render would make the video vanish mid-watch.
  const [playing, setPlaying] = useState<Breach | null>(null);
  const zones = loadedZones.map((z) => (z.id in pending ? { ...z, enabled: pending[z.id] } : z));
  const anyRestricted = zones.some((z) => z.enabled);

  async function toggleZone(zone: Zone) {
    const next = !zone.enabled;
    setToggleError(null);
    // Optimistic, so the switch feels immediate...
    setPending((p) => ({ ...p, [zone.id]: next }));
    try {
      await setZoneEnabled(zone.id, next);
      // ...and confirmed from the engine, not assumed.
      reloadZones();
      setPending((p) => {
        const { [zone.id]: _dropped, ...rest } = p;
        return rest;
      });
    } catch (error) {
      setPending((p) => {
        const { [zone.id]: _dropped, ...rest } = p;
        return rest;
      });
      setToggleError(
        `${zone.name} was not changed: ${error instanceof Error ? error.message : 'the engine did not accept it'}`,
      );
    }
  }

  const counted = !breachLoading && !breachError;
  const running = breaches.filter((b) => b.status === 'Still there').length;
  const clips = breaches.filter((b) => b.clipUrl).length;
  // The engine lists only what is still watchable, so the number of rows is
  // not the number of things that happened. This is, for today.
  const detectionsToday = zones.reduce((n, z) => n + z.detectionsToday, 0);
  const stillListed = playing !== null && breaches.some((b) => b.id === playing.id);
  const linkedMissing = linked.id !== null && counted
    && !breaches.some((b) => b.id === linked.id);
  const windowName = t(`window.${when}` as MessageKey);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('intrusion.title')} lead={t('intrusion.lead')} />

      {/* Status first: what needs a look, before anything the viewer must
          configure. Three honest states, not two - a page that has not heard
          back yet must say so rather than default to "all calm". */}
      <div className="card hstack" role="status" style={{ gap: 12 }}>
        <span
          className={running > 0 ? 'icontile icontile--warn' : 'icontile'}
          aria-hidden="true"
        >
          <Icon name={counted ? (running > 0 ? 'warn' : 'check') : 'clock'} />
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="li__title">
            {counted
              ? running === 0
                ? t('intrusion.nobodyInside')
                : t('intrusion.stillInView', { count: formatCount(running, language) })
              : breachError
                ? t('intrusion.notCounted')
                : t('intrusion.counting')}
          </div>
        </div>
      </div>

      <section className="stack">
        <div className="sechead">
          <h2 className="sechead__title" style={{ margin: 0 }}>{t('intrusion.restrictedCameras')}</h2>
        </div>
        <LoadError error={zonesError} onRetry={reloadZones} what="load.cameraList" />
        <LoadError error={toggleError} what="load.change" />
        {zonesLoading && <div className="card"><Empty>{t('intrusion.loadingCameras')}</Empty></div>}
        {/* Never demo cameras. An empty roster is an empty list. */}
        {!zonesLoading && !zonesError && zones.length === 0 && (
          <div className="card"><Empty>{t('intrusion.noCameras')}</Empty></div>
        )}
        {zones.length > 0 && (
          <div className="list">
            {zones.map((zone) => (
              <div key={zone.id} className="li">
                <span className="li__main">
                  <span className="li__title">{zone.name}</span>
                  <span className="li__sub">
                    {zone.enabled
                      ? t('intrusion.wholeViewRestricted', {
                        count: formatCount(zone.detectionsToday, language),
                      })
                      : t('intrusion.notRestricted')}
                  </span>
                </span>
                <Badge tone={zone.enabled ? 'good' : 'warn'} glyph={toneGlyph[zone.enabled ? 'good' : 'warn']}>
                  {zone.enabled ? t('intrusion.protected') : t('intrusion.paused')}
                </Badge>
                {/* Console shows the switch to every signed-in role and lets
                    the server refuse the write - the phone matches that. */}
                <Toggle
                  on={zone.enabled}
                  onToggle={() => toggleZone(zone)}
                  label={t('intrusion.protectionFor', { camera: zone.name })}
                />
              </div>
            ))}
          </div>
        )}
        {/* Not a t() key on the console either - copied verbatim rather than
            invented (see consoleDefects). */}
        <p className="note" style={{ margin: '0 2px' }}>
          A camera switched on here is restricted around the clock. Switch one off during
          maintenance, then back on — pauses are visible to everyone.
        </p>
      </section>

      <section className="stack">
        <Card className="stack">
          <div className="li__title" style={{ fontSize: 18 }}>
            {counted
              ? t(clips === 1 ? 'intrusion.clipCountOne' : 'intrusion.clipCount', {
                count: clips,
                window: windowName,
              })
              : t('intrusion.clipsHeading', { window: windowName })}
          </div>
          <Field label={t('intrusion.period')}>
            <Select
              value={when}
              onChange={(v) => setWhen(v as IntrusionWindow)}
              options={WINDOWS}
              label={(o) => t(`window.${o}` as MessageKey)}
            />
          </Field>

          {/* The list is not the whole story and must not read as if it
              were. Each camera keeps three clips; everything older is still
              recorded, it just has nothing left to watch. */}
          {counted && anyRestricted && (
            <p className="note" style={{ margin: 0 }}>
              {when === 'today' && detectionsToday > 0
                ? `${t(detectionsToday === 1
                  ? 'intrusion.detectionsTodayOne'
                  : 'intrusion.detectionsToday',
                { count: formatCount(detectionsToday, language) })} `
                : ''}
              {t('intrusion.keepsThreeClips')}
            </p>
          )}
        </Card>

        <LoadError error={breachError} onRetry={reloadBreaches} what="load.detectionLog" />
        {breachLoading && <div className="card"><Empty>{t('intrusion.loadingDetections')}</Empty></div>}
        {linkedMissing && (
          <div className="linked-missing" role="status">
            {t('intrusion.linkedNotListed', { window: windowName })}
          </div>
        )}
        {/* Two different empty states, because they mean different things. An
            empty log with nothing switched on is not the same claim as an
            empty log on a camera that has been watching all day. */}
        {counted && breaches.length === 0 && !anyRestricted && (
          <div className="card"><Empty>{t('intrusion.noneRestricted')}</Empty></div>
        )}
        {counted && breaches.length === 0 && anyRestricted && (
          <div className="card"><Empty>{t('intrusion.nothingSince')}</Empty></div>
        )}

        {/* Dropped out of the chosen period while it was being watched. The
            player stays, and says so, rather than silently disappearing. */}
        {playing?.clipUrl && !stillListed && (
          <div className="card stack" style={{ gap: 8 }}>
            <video key={playing.id} src={playing.clipUrl} controls autoPlay playsInline
                   style={{ width: '100%', borderRadius: 10, background: '#000' }} />
            <p className="note">
              A newer scene on {playing.zone} has replaced this clip, so it has dropped off
              the list. It may stop playing.
            </p>
          </div>
        )}

        {breaches.map((breach) => {
          const isPlaying = playing?.id === breach.id && !!breach.clipUrl;
          return (
            <article
              key={breach.id}
              ref={breach.id === linked.id ? linked.ref : undefined}
              aria-current={breach.id === linked.id || undefined}
              className="card card--flush"
              style={breach.id === linked.id ? LINKED_STYLE : undefined}
            >
              {isPlaying && (
                <video key={breach.id} src={breach.clipUrl} controls autoPlay playsInline
                       style={{ width: '100%', display: 'block', background: '#000' }} />
              )}
              <div className="stack" style={{ padding: 14, gap: 12 }}>
                <div className="spread" style={{ alignItems: 'flex-start' }}>
                  <div style={{ minWidth: 0 }}>
                    <div className="li__title">{breach.zone}</div>
                    <div className="li__sub">
                      {[breach.time, breach.people === 1 ? '1 person' : `${breach.people} people`, breach.duration]
                        .filter(Boolean).join(' · ')}
                    </div>
                  </div>
                  <Badge tone={breach.tone} glyph={toneGlyph[breach.tone]}>
                    {breach.status}
                  </Badge>
                </div>

                {/* No dead buttons. A clip either plays or the control is gone
                    and a sentence says why. */}
                {breach.clipUrl ? (
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    aria-expanded={isPlaying}
                    onClick={() =>
                      setPlaying((current) => (current?.id === breach.id ? null : breach))
                    }
                  >
                    {isPlaying ? t('intrusion.hideClip') : t('intrusion.watchClip')}
                  </button>
                ) : (
                  <p className="note">{breach.clipReason ?? t('intrusion.noClip')}</p>
                )}
              </div>
            </article>
          );
        })}
      </section>

      {/* No `feature`: the whole camera view is the restricted area, so there
          is no overlay to draw here - a box would claim a line that does not
          exist. */}
      <CamGrid
        title={t('intrusion.gridTitle')}
        note={t('intrusion.gridNote')}
        cameras={cameras}
      />
    </>
  );
}
