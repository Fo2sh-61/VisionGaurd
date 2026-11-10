import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AreaEditor, type AreaBase } from '@/components/AreaEditor';
import { AreaPicture } from '@/components/AreaPicture';
import {
  Badge, Card, DataNotice, Empty, Field, LoadError, PageHeader, Select, Stats, toneGlyph,
} from '@/components/ui';
import {
  acknowledgeStation, createStation, deleteStation, getAlertSettings, getCameras,
  getFaceReach, getPeople, getSchoolProfile, getStation, getStations, updateStation,
} from '@/services/api';
import type { Camera, StationCard, StationDraft, TimelineBar, Tone } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useAccount } from '@/app/AuthContext';
import { useAsync } from '@/app/useAsync';
import { LINKED_STYLE, useLinkedItem } from '@/app/useLinkedItem';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import {
  formatCount, formatDurationShort, formatPercent, formatWatched, stationEventLine,
  stationStateLabel, stationStateTone,
} from '@/services/format';

const REFRESH_MS = 5_000;
const NO_STATIONS: StationCard[] = [];
const NO_CAMERAS: Camera[] = [];

const BAR_COLOUR: Record<TimelineBar['state'], string> = {
  on: 'var(--ac2)',
  away: 'var(--am)',
  absent: 'var(--rd)',
  notWatched: 'var(--line)',
};

/** Work stations: places that must stay staffed.
 *
 *  **No picture on this page shows a name or an identity.** Every picture is an
 *  `AreaPicture` (`detections={false}`), and a station's colour is its state,
 *  never who is standing there. The assigned person is shown as an assignment
 *  ("Assigned to ..."), not as something the camera recognised on the picture. */
export function Stations() {
  const { language } = useLanguage();
  const t = useT();
  const toast = useToast();
  const capability = useCapability('stations');
  const isAdmin = useAccount().role === 'admin';   // a hint; the server decides
  const [params] = useSearchParams();
  const linked = useLinkedItem('station');

  const { data: stations, error, loading, reload } = useAsync(
    () => getStations(language), [language], NO_STATIONS, REFRESH_MS);
  const { data: removed, reload: reloadRemoved } = useAsync(
    () => getStations(language, true).then((all) => all.filter((s) => s.deleted)),
    [language], NO_STATIONS);
  const { data: cameras } = useAsync(() => getCameras(language), [language], NO_CAMERAS, 15_000);
  const { data: alertRows } = useAsync(
    () => getAlertSettings().then((s) => s.rules), [],
    null as null | { kind: string; inApp: boolean | null; email: boolean }[]);
  const { data: school } = useAsync(() => getSchoolProfile(), [], null);
  // The directory is admin-only; an IT account never asks for it.
  const { data: people } = useAsync(
    () => (isAdmin ? getPeople(language) : Promise.resolve([])), [language, isAdmin], []);

  const [selectedId, setSelectedId] = useState<string | null>(params.get('station'));
  const [day, setDay] = useState('');
  const { data: detail, reload: reloadDetail } = useAsync(
    () => (selectedId ? getStation(selectedId, language, day || undefined) : Promise.resolve(null)),
    [selectedId, language, day], null as StationCard | null, REFRESH_MS);

  const [editing, setEditing] = useState<string | 'new' | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [assignee, setAssignee] = useState<string>('');
  const [limit, setLimit] = useState(10);
  const [reachCamera, setReachCamera] = useState('');

  const editingStation = editing && editing !== 'new'
    ? stations.find((s) => s.id === editing) : undefined;
  const cameraOf = (id: string) => cameras.find((c) => c.id === id);
  const rule = alertRows?.find((r) => r.kind === 'station');

  const { data: reach } = useAsync(
    () => (assignee && reachCamera ? getFaceReach(reachCamera) : Promise.resolve(null)),
    [assignee, reachCamera], null);

  const open = stations.filter((s) => s.state === 'on' || s.state === 'away' || s.state === 'absent');
  const staffed = open.filter((s) => s.state === 'on').length;
  const away = open.filter((s) => s.state === 'away').length;
  const absent = open.filter((s) => s.state === 'absent').length;
  const unknown = stations.filter((s) => s.state === 'unknown');
  const work = open.reduce((n, s) => n + s.workSeconds, 0);
  const off = open.reduce((n, s) => n + s.absentSeconds, 0);
  const todayRate = work + off > 0 ? work / (work + off) : null;

  const tiles = useMemo(() => [
    { label: t('stations.tile.staffed'), value: formatCount(staffed, language) },
    { label: t('stations.tile.away'), value: formatCount(away, language) },
    { label: t('stations.tile.absent'), value: formatCount(absent, language) },
    {
      label: t('stations.tile.rate'),
      value: todayRate === null ? t('stations.notWatched')
        : t('stations.tile.rateOf', {
          rate: formatPercent(todayRate, language),
          n: formatCount(open.length, language),
        }),
    },
  ], [t, language, staffed, away, absent, todayRate, open.length]);

  async function run(action: () => Promise<void>, done: string, failure: string) {
    setBusy(true);
    setFormError(null);
    try {
      await action();
      toast.show(done, 'good');
      reload();
      reloadRemoved();
      reloadDetail();
      return true;
    } catch (e) {
      const reason = e instanceof Error ? e.message : t('zones.engineRefused');
      setFormError(t('zones.notChanged', { what: failure, reason }));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function save(base: AreaBase) {
    const draft: StationDraft = {
      ...base, assigneeId: assignee || undefined, limitMinutes: limit,
    };
    const ok = await run(
      () => (editingStation ? updateStation(editingStation.id, draft) : createStation(draft)),
      t(editingStation ? 'stations.saved' : 'stations.created', { name: draft.name }),
      draft.name,
    );
    if (ok) setEditing(null);
  }

  function startEditing(station: StationCard | null) {
    setFormError(null);
    setAssignee(station?.assigneeId ?? '');
    setLimit(station?.limitMinutes ?? 10);
    setReachCamera(station?.cameraId ?? cameras[0]?.id ?? '');
    setEditing(station ? station.id : 'new');
  }

  function assignedLine(s: StationCard): string {
    if (!s.assigneeId) return t('stations.anyoneCounts');
    if (s.assigneeMissing) return t('stations.assigneeMissing');
    if (s.faceCheck === 'facesTooSmall') return t('stations.facesTooSmall');
    // IT gets the id and no name (spec 022): "a person", not who.
    return s.assigneeName
      ? t('stations.assignedTo', { name: s.assigneeName })
      : t('stations.assignedToPerson');
  }

  function stateLine(s: StationCard): string {
    if (s.state === 'notStarted' && s.opensAt) return t('stations.opensAt', { time: s.opensAt });
    if (s.state === 'unknown' && s.unknownReason) return t(`stations.unknown.${s.unknownReason}`);
    if (s.state === 'on' && s.presentNotRecognised) return t('stations.presentNotRecognised');
    return s.since ? t('stations.since', { time: s.since }) : '';
  }

  if (editing !== null) {
    const initial = editingStation
      ? {
        name: editingStation.name, cameraId: editingStation.cameraId,
        polygon: editingStation.polygon, watched: editingStation.watched,
        notifyInApp: editingStation.notifyInApp, notifyEmail: editingStation.notifyEmail,
      }
      : { notifyInApp: rule?.inApp ?? true, notifyEmail: rule?.email ?? false };
    return (
      <>
        <PageHeader title={t('stations.title')} lead={t('stations.lead')} />
        <AreaEditor
          kind="station"
          cameras={cameras}
          initial={initial}
          hasHoursSettings={!!school?.hoursFrom}
          busy={busy}
          error={formError}
          extraReady={limit >= 1 && limit <= 480}
          onSave={(base) => void save(base)}
          onCancel={() => { setEditing(null); setFormError(null); }}
          onCameraChange={setReachCamera}
        >
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
            <Field label={t('stations.editor.assignee')}>
              <Select
                value={assignee}
                onChange={setAssignee}
                options={['', ...people.map((p) => p.id)]}
                label={(id) => (id ? people.find((p) => p.id === id)?.name ?? id : t('stations.editor.anyone'))}
              />
            </Field>
            <Field label={t('stations.editor.limit')}>
              <input className="input" type="number" min={1} max={480} style={{ width: 100 }}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value) || 0)} />
            </Field>
          </div>
          {assignee && reach && (
            <div style={{ fontSize: 12.5, marginBottom: 10,
              color: reach.facePx !== null && reach.facePx >= reach.needed ? 'var(--tx2)' : 'var(--am)' }}>
              {reach.facePx === null
                ? t('stations.editor.reachUnknown')
                : reach.facePx < reach.needed
                  ? t('stations.editor.reachSmall', { px: Math.round(reach.facePx), needed: reach.needed })
                  : t('stations.editor.reachOk', { px: Math.round(reach.facePx) })}
            </div>
          )}
        </AreaEditor>
      </>
    );
  }

  const selected = detail ?? stations.find((s) => s.id === selectedId) ?? null;

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('stations.title')} lead={t('stations.lead')} />

      <Stats items={tiles} />
      {unknown.length > 0 && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', margin: '6px 0' }}>
          {unknown.map((s) => (
            <div key={s.id}>
              {t('stations.unknownNamed', {
                name: s.name,
                reason: s.unknownReason ? t(`stations.unknown.${s.unknownReason}`) : '',
              })}
            </div>
          ))}
        </div>
      )}
      <div style={{ fontSize: 12.5, color: 'var(--tx2)', margin: '6px 0 12px' }}>
        {t('stations.tile.note')}
      </div>

      <LoadError error={error} onRetry={reload} what="load.cameraList" />
      <LoadError error={formError} what="load.change" />
      {loading && <Empty>{t('stations.loading')}</Empty>}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '6px 0 10px' }}>
        <div style={{ fontWeight: 700, fontSize: 15 }}>{t('stations.listHeading')}</div>
        {isAdmin && (
          <button type="button" className="chip-btn chip-btn--on" onClick={() => startEditing(null)}>
            {t('stations.draw')}
          </button>
        )}
      </div>

      {!loading && !error && stations.length === 0 && (
        <Empty>{t(isAdmin ? 'stations.none' : 'stations.noneAsk')}</Empty>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
        {stations.map((s) => {
          const camera = cameraOf(s.cameraId);
          const tone: Tone = stationStateTone(s.state);
          return (
            <Card key={s.id} tight>
              <button
                type="button"
                className="list-row"
                ref={s.id === linked.id ? linked.ref as never : undefined}
                aria-pressed={selectedId === s.id}
                onClick={() => { setSelectedId(selectedId === s.id ? null : s.id); setDay(''); }}
                style={{ textAlign: 'start', width: '100%',
                  ...(s.id === linked.id ? LINKED_STYLE : null) }}
              >
                {camera ? (
                  <AreaPicture camera={camera} polygon={s.polygon} tone={tone} />
                ) : (
                  <Empty>{t('zones.cameraGone')}</Empty>
                )}
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 8 }}>
                  <span style={{ fontWeight: 600 }}>{s.name}</span>
                  <Badge tone={tone} glyph={toneGlyph[tone]}>{stationStateLabel(s.state, language)}</Badge>
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{assignedLine(s)}</div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{stateLine(s)}</div>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 2 }}>
                  {t('stations.worked', { time: formatDurationShort(s.workSeconds, language) })}
                  {' · '}
                  {t('stations.awayTime', { time: formatDurationShort(s.absentSeconds, language) })}
                  {' · '}
                  {s.rate === null ? t('stations.notWatched') : formatPercent(s.rate, language)}
                </div>
                <Timeline bars={s.timeline} label={t('stations.timeline')} />
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
                {stationStateLabel(selected.state, language)}
                {stateLine(selected) ? ` · ${stateLine(selected)}` : ''}
              </div>
              <div style={{ fontSize: 13, color: 'var(--tx2)' }}>{assignedLine(selected)}</div>
              <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
                {t('stations.rules', {
                  limit: selected.limitMinutes,
                  hours: formatWatched(selected.watched, language),
                })}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              {selected.alertEventId && (
                <button type="button" className="chip-btn chip-btn--on" disabled={busy}
                  onClick={() => void run(
                    () => acknowledgeStation(selected.id),
                    t('stations.acknowledged', { name: selected.name }), selected.name)}>
                  {t('stations.acknowledge')}
                </button>
              )}
              {isAdmin && !selected.deleted && (
                <>
                  <button type="button" className="chip-btn chip-btn--off" disabled={busy}
                    onClick={() => startEditing(selected)}>
                    {t('stations.edit')}
                  </button>
                  <button type="button" className="chip-btn chip-btn--off" disabled={busy}
                    onClick={() => setConfirmDelete(true)}>
                    {t('stations.delete')}
                  </button>
                </>
              )}
            </div>
          </div>
          {confirmDelete && (
            <div role="alert" style={{ marginTop: 10, padding: 10, border: '1px solid var(--line)', borderRadius: 8 }}>
              <div style={{ fontSize: 13.5, marginBottom: 8 }}>
                {t('stations.deleteQuestion', { name: selected.name })}
              </div>
              <button type="button" className="chip-btn chip-btn--on" disabled={busy}
                onClick={async () => {
                  if (await run(() => deleteStation(selected.id),
                    t('stations.deletedToast', { name: selected.name }), selected.name)) {
                    setConfirmDelete(false);
                    setSelectedId(null);
                  }
                }}>
                {t('stations.deleteConfirm')}
              </button>{' '}
              <button type="button" className="chip-btn chip-btn--off" onClick={() => setConfirmDelete(false)}>
                {t('area.editor.cancel')}
              </button>
            </div>
          )}

          <div style={{ marginTop: 14, display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <Field label={t('stations.day')}>
              <input className="input" type="date" value={day}
                onChange={(e) => setDay(e.target.value)} />
            </Field>
            <div style={{ fontSize: 13, color: 'var(--tx2)' }}>
              {t('stations.worked', { time: formatDurationShort(selected.workSeconds, language) })}
              {' · '}
              {t('stations.awayTime', { time: formatDurationShort(selected.absentSeconds, language) })}
              {selected.notWatchedSeconds > 0 && (
                <>{' · '}{t('stations.notWatchedTime', {
                  time: formatDurationShort(selected.notWatchedSeconds, language) })}</>
              )}
            </div>
          </div>
          <Timeline bars={selected.timeline} label={t('stations.timeline')} tall />

          <div style={{ fontWeight: 600, margin: '14px 0 6px' }}>{t('stations.log')}</div>
          {selected.events.length === 0 && <Empty>{t('stations.noEvents')}</Empty>}
          {selected.events.map((e) => (
            <div key={e.id} className="row" style={{ gridTemplateColumns: '90px 1fr' }}>
              <span className="row__muted">{e.time}</span>
              <span>{stationEventLine(e, language)}</span>
            </div>
          ))}
        </Card>
      )}

      {removed.length > 0 && (
        <Card>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{t('stations.removed')}</div>
          {removed.map((s) => (
            <button key={s.id} type="button" className="list-row"
              onClick={() => { setSelectedId(s.id); setDay(''); }}>
              {s.name}
            </button>
          ))}
        </Card>
      )}
    </>
  );
}

/** Today's timeline, left to right in every language: it is a clock, and a
 *  clock does not mirror. */
function Timeline({ bars, label, tall }: { bars: TimelineBar[]; label: string; tall?: boolean }) {
  if (bars.length === 0) return null;
  return (
    <div dir="ltr" role="img" aria-label={label}
      style={{ position: 'relative', height: tall ? 18 : 8, marginTop: 8, borderRadius: 4,
        background: 'var(--bg)', overflow: 'hidden' }}>
      {bars.map((b, i) => (
        <span
          key={`${b.from}-${i}`}
          title={`${b.from} - ${b.to}`}
          style={{
            position: 'absolute', top: 0, bottom: 0,
            left: `${b.start * 100}%`, width: `${b.width * 100}%`,
            background: BAR_COLOUR[b.state],
          }}
        />
      ))}
    </div>
  );
}
