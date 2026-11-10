import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AreaEditor, type AreaBase } from '@/components/AreaEditor';
import { AreaPicture } from '@/components/AreaPicture';
import { Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, Stats, toneGlyph } from '@/components/ui';
import {
  createZone, deleteZone, getAlertSettings, getBreaches, getCameras, getSchoolProfile,
  getZoneCards, setZoneEnabled, updateZone,
} from '@/services/api';
import type { Breach, Camera, IntrusionWindow, ZoneCard, ZoneDraft } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAccount } from '@/app/AuthContext';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import { formatCount, formatWatched, zoneStatusLabel, zoneStatusTone } from '@/services/format';
import type { MessageKey } from '@/i18n';

const WINDOWS: IntrusionWindow[] = ['today', 'last7', 'last30'];

/** A scene becomes watchable the moment the person leaves frame, which is a
 *  thing that happens while somebody is looking at this page rather than
 *  because they did anything. Without a poll the only way to see a new clip
 *  was to navigate away and come back. */
const LOG_REFRESH_MS = 3_000;

/** The zone cards and their counts. Slower: these change when a person presses
 *  something, or when somebody walks in. */
const ZONE_REFRESH_MS = 5_000;

const NO_ZONES: ZoneCard[] = [];
const NO_BREACHES: Breach[] = [];
const NO_CAMERAS: Camera[] = [];

/** Restricted zones: drawn areas on a camera where nobody should be.
 *
 *  Inside means feet inside. Every picture here passes `detections={false}`
 *  through `AreaPicture`: this page says WHERE somebody is, never who. */
export function Intrusion() {
  const { language } = useLanguage();
  const capability = useCapability('breaches');
  const t = useT();
  const toast = useToast();
  const isAdmin = useAccount().role === 'admin';   // a hint; the server decides
  const [params] = useSearchParams();
  const asked = params.get('window');
  const [when, setWhen] = useState<IntrusionWindow>(
    asked === 'today' || asked === 'last7' || asked === 'last30'
      ? asked : 'today');
  // An alert lands here on one scene: `?scene=` is the one the engine named.
  const linked = useLinkedItem('scene');

  const {
    data: zones, error: zonesError, loading: zonesLoading, reload: reloadZones,
  } = useAsync(() => getZoneCards(language), [language], NO_ZONES, ZONE_REFRESH_MS);
  const { data: cameras } = useAsync(() => getCameras(language), [language], NO_CAMERAS, 15_000);
  const { data: alertRows } = useAsync(
    () => getAlertSettings().then((s) => s.rules), [], null as null | { kind: string; inApp: boolean | null; email: boolean }[]);
  const { data: school } = useAsync(() => getSchoolProfile(), [], null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = zones.find((z) => z.id === selectedId) ?? null;

  const {
    data: breaches, error: breachError, loading: breachLoading, reload: reloadBreaches,
  } = useAsync(() => getBreaches(when, language, selected?.id),
    [when, language, selected?.id], NO_BREACHES, LOG_REFRESH_MS);

  // The whole entry, not just its id: the log refreshes underneath the player.
  const [playing, setPlaying] = useState<Breach | null>(null);
  // Drawing, editing, removing. `editing` is a zone id, or 'new'.
  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [delayMode, setDelayMode] = useState<'moment' | 'after'>('moment');
  const [delaySeconds, setDelaySeconds] = useState(10);

  const cameraOf = (id: string) => cameras.find((c) => c.id === id);
  const rule = alertRows?.find((r) => r.kind === 'intrusion');
  const editingZone = editing && editing !== 'new' ? zones.find((z) => z.id === editing) : undefined;

  const watching = zones.filter((z) => z.status === 'personInZone' || z.status === 'clear').length;
  const paused = zones.filter((z) => z.status === 'paused').length;
  const unreadable = zones.filter((z) => z.status === 'cameraOffline' || z.status === 'detectorStopped').length;
  const inNow = zones.reduce((n, z) => n + (z.inZoneNow ?? 0), 0);
  const entriesToday = zones.reduce((n, z) => n + z.detectionsToday, 0);

  const counted = !breachLoading && !breachError;
  const linkedMissing = linked.id !== null && counted
    && !breaches.some((b) => b.id === linked.id);
  const stillListed = playing !== null && breaches.some((b) => b.id === playing.id);

  const tiles = useMemo(() => [
    { label: t('zones.tile.inNow'), value: unreadable > 0 && inNow === 0 ? '—' : formatCount(inNow, language) },
    { label: t('zones.tile.entriesToday'), value: formatCount(entriesToday, language) },
    { label: t('zones.tile.watching'), value: formatCount(watching, language) },
    { label: t('zones.tile.paused'), value: formatCount(paused, language) },
  ], [t, language, inNow, entriesToday, watching, paused, unreadable]);

  async function run(action: () => Promise<void>, done: string, failure: string) {
    setBusy(true);
    setFormError(null);
    try {
      await action();
      toast.show(done, 'good');
      reloadZones();
      return true;
    } catch (error) {
      const reason = error instanceof Error ? error.message : t('zones.engineRefused');
      setFormError(t('zones.notChanged', { what: failure, reason }));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(base: AreaBase) {
    const draft: ZoneDraft = {
      ...base,
      alertAfterSeconds: delayMode === 'after' ? delaySeconds : 0,
    };
    const ok = await run(
      () => (editingZone ? updateZone(editingZone.id, draft) : createZone(draft)),
      t(editingZone ? 'zones.saved' : 'zones.created', { name: draft.name }),
      draft.name,
    );
    if (ok) setEditing(null);
  }

  async function togglePause(zone: ZoneCard) {
    // Confirmed from the engine, not assumed: this state is a safety claim.
    await run(
      () => setZoneEnabled(zone.id, !zone.enabled),
      t(zone.enabled ? 'zones.pausedToast' : 'zones.resumedToast', { name: zone.name }),
      zone.name,
    );
  }

  async function remove(zone: ZoneCard) {
    const ok = await run(() => deleteZone(zone.id), t('zones.deletedToast', { name: zone.name }), zone.name);
    if (ok) {
      setConfirmDelete(null);
      setSelectedId(null);
    }
  }

  if (editing !== null) {
    const initial = editingZone
      ? {
        name: editingZone.name, cameraId: editingZone.cameraId, polygon: editingZone.polygon,
        watched: editingZone.watched, notifyInApp: editingZone.notifyInApp,
        notifyEmail: editingZone.notifyEmail,
      }
      : { notifyInApp: rule?.inApp ?? true, notifyEmail: rule?.email ?? false };
    return (
      <>
        <PageHeader title={t('zones.title')} lead={t('zones.lead')} />
        <AreaEditor
          kind="zone"
          cameras={cameras}
          initial={initial}
          hasHoursSettings={!!school?.hoursFrom}
          busy={busy}
          error={formError}
          onSave={(base) => void save(base)}
          onCancel={() => { setEditing(null); setFormError(null); }}
        >
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{t('zones.alertTiming')}</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="button" aria-pressed={delayMode === 'moment'}
                className={`chip-btn ${delayMode === 'moment' ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setDelayMode('moment')}>
                {t('zones.alertMoment')}
              </button>
              <button type="button" aria-pressed={delayMode === 'after'}
                className={`chip-btn ${delayMode === 'after' ? 'chip-btn--on' : 'chip-btn--off'}`}
                onClick={() => setDelayMode('after')}>
                {t('zones.alertAfter')}
              </button>
              {delayMode === 'after' && (
                <input className="input" type="number" min={1} max={3600} style={{ width: 90 }}
                  value={delaySeconds}
                  onChange={(e) => setDelaySeconds(Math.max(1, Number(e.target.value) || 1))}
                  aria-label={t('zones.alertSeconds')} />
              )}
            </div>
          </div>
        </AreaEditor>
      </>
    );
  }

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('zones.title')} lead={t('zones.lead')} />

      <Stats items={tiles} />
      {unreadable > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', margin: '6px 0' }}>
          {t('zones.tile.unreadable', { count: formatCount(unreadable, language) })}
        </div>
      )}
      <div style={{ fontSize: 12.5, color: 'var(--tx2)', margin: '6px 0 12px' }}>
        {t('zones.tile.entriesNote')}
      </div>

      <LoadError error={zonesError} onRetry={reloadZones} what="load.zoneList" />
      <LoadError error={formError} what="load.change" />
      {zonesLoading && <Empty>{t('zones.loading')}</Empty>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '6px 0 10px' }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{t('zones.listHeading')}</div>
        {isAdmin && (
          <button type="button" className="chip-btn chip-btn--on"
            onClick={() => { setEditing('new'); setFormError(null); }}>
            {t('zones.draw')}
          </button>
        )}
      </div>

      {!zonesLoading && !zonesError && zones.length === 0 && (
        // Never demo zones. No zone drawn is an empty list.
        <Empty>{t(isAdmin ? 'zones.none' : 'zones.noneAsk')}</Empty>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {zones.map((zone) => {
          const camera = cameraOf(zone.cameraId);
          const tone = zoneStatusTone(zone.status);
          return (
            <Card key={zone.id} tight>
              <button type="button" className="list-row" aria-pressed={selectedId === zone.id}
                onClick={() => setSelectedId(selectedId === zone.id ? null : zone.id)}
                style={{ textAlign: 'start', width: '100%' }}>
                {camera ? (
                  <AreaPicture camera={camera} polygon={zone.polygon} tone={tone} />
                ) : (
                  <Empty>{t('zones.cameraGone')}</Empty>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
                  <span style={{ fontWeight: 600 }}>{zone.name}</span>
                  <Badge tone={tone} glyph={toneGlyph[tone]}>{zoneStatusLabel(zone.status, language)}</Badge>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 2 }}>
                  {zone.inZoneNow === null
                    ? t('zones.inNowUnknown')
                    : t('zones.inNowCount', { count: formatCount(zone.inZoneNow, language) })}
                  {' · '}
                  {t('zones.entriesCount', { count: formatCount(zone.detectionsToday, language) })}
                </div>
              </button>
            </Card>
          );
        })}
      </div>

      {selected && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 17 }}>{selected.name}</div>
              <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                {formatWatched(selected.watched, language)}
                {' · '}
                {selected.alertAfterSeconds > 0
                  ? t('zones.alertAfterN', { n: selected.alertAfterSeconds })
                  : t('zones.alertAtMoment')}
              </div>
              {selected.status === 'paused' && selected.pausedBy && (
                // Visible to everyone, not only the person who paused it.
                <div style={{ fontSize: 13, color: 'var(--am)', marginTop: 4 }}>
                  {t('zones.pausedBy', { name: selected.pausedBy, time: selected.pausedAt ?? '' })}
                </div>
              )}
              {selected.importNote && (
                <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 4 }}>{selected.importNote}</div>
              )}
            </div>
            {isAdmin && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <button type="button" className="chip-btn chip-btn--off" disabled={busy}
                  onClick={() => void togglePause(selected)}>
                  {t(selected.enabled ? 'zones.pause' : 'zones.resume')}
                </button>
                <button type="button" className="chip-btn chip-btn--off" disabled={busy}
                  onClick={() => { setEditing(selected.id); setFormError(null);
                    setDelayMode(selected.alertAfterSeconds > 0 ? 'after' : 'moment');
                    setDelaySeconds(selected.alertAfterSeconds || 10); }}>
                  {t('zones.edit')}
                </button>
                <button type="button" className="chip-btn chip-btn--off" disabled={busy}
                  onClick={() => setConfirmDelete(selected.id)}>
                  {t('zones.delete')}
                </button>
              </div>
            )}
          </div>
          {confirmDelete === selected.id && (
            <div role="alert" style={{ marginTop: 10, padding: 10, border: '1px solid var(--line)', borderRadius: 8 }}>
              <div style={{ fontSize: 13.5, marginBottom: 8 }}>
                {t('zones.deleteQuestion', { name: selected.name })}
              </div>
              <button type="button" className="chip-btn chip-btn--on" disabled={busy}
                onClick={() => void remove(selected)}>
                {t('zones.deleteConfirm')}
              </button>{' '}
              <button type="button" className="chip-btn chip-btn--off" onClick={() => setConfirmDelete(null)}>
                {t('area.editor.cancel')}
              </button>
            </div>
          )}
        </Card>
      )}

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 17 }}>
              {selected ? t('zones.logFor', { name: selected.name }) : t('zones.logAll')}
            </div>
            <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
              {counted
                ? t('zones.logCount', { count: formatCount(breaches.length, language) })
                : breachError ? t('intrusion.notCounted') : t('intrusion.counting')}
            </div>
          </div>
          <Field label={t('intrusion.period')}>
            <Select value={when} onChange={(v) => setWhen(v as IntrusionWindow)} options={WINDOWS}
              label={(o) => t(`window.${o}` as MessageKey)} />
          </Field>
        </div>

        <LoadError error={breachError} onRetry={reloadBreaches} what="load.detectionLog" />
        {breachLoading && <Empty>{t('intrusion.loadingDetections')}</Empty>}
        {linkedMissing && (
          <div className="linked-missing" role="status">
            {t('intrusion.linkedNotListed', { window: t(`window.${when}` as MessageKey) })}
          </div>
        )}
        {counted && breaches.length === 0 && (
          <Empty>{t(zones.length === 0 ? 'intrusion.noneRestricted' : 'intrusion.nothingSince')}</Empty>
        )}

        {breaches.map((breach) => (
          <div
            key={breach.id}
            ref={breach.id === linked.id ? linked.ref : undefined}
            aria-current={breach.id === linked.id || undefined}
            className="row"
            style={{
              gridTemplateColumns: '1.2fr 1fr .8fr 1fr .8fr 1.2fr',
              ...(breach.id === linked.id ? LINKED_STYLE : null),
            }}
          >
            <span className="row__name">{breach.zone}</span>
            <span className="row__muted">{breach.time}</span>
            <span className="row__muted">
              {breach.people === 1 ? '1 person' : `${breach.people} people`}
            </span>
            <span className="row__muted">
              {breach.status === 'Still there' ? t('zones.insideNow') : breach.duration}
              {breach.cut && <span title={t('zones.cutNote')}> {t('zones.cutShort')}</span>}
            </span>
            <span>
              <Badge tone={breach.tone} glyph={toneGlyph[breach.tone]}>{breach.status}</Badge>
            </span>
            {/* No dead buttons. A clip either plays or says why not. */}
            {breach.clipUrl ? (
              <button type="button" className="linkbtn"
                onClick={() => setPlaying((c) => (c?.id === breach.id ? null : breach))}>
                {playing?.id === breach.id ? t('intrusion.hideClip') : t('intrusion.watchClip')}
              </button>
            ) : (
              <span style={{ fontSize: 12.5, color: 'var(--tx2)' }}>
                {breach.clipState === 'replaced' ? t('zones.noClipKept') : breach.clipReason ?? t('intrusion.noClip')}
              </span>
            )}
          </div>
        ))}

        {playing?.clipUrl && (
          <div style={{ marginTop: 12 }}>
            <video key={playing.id} src={playing.clipUrl} controls autoPlay
              style={{ width: '100%', maxHeight: 420, borderRadius: 8 }} />
            {!stillListed && (
              <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 6 }}>
                {t('zones.clipReplacedWhileWatching', { zone: playing.zone })}
              </div>
            )}
          </div>
        )}
        {counted && breaches.length > 0 && (
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 10 }}>
            {t('intrusion.keepsThreeClips')}
          </div>
        )}
      </Card>
    </>
  );
}
