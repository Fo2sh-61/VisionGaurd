/** Attendance as the cameras recorded it.
 *
 *  One page, one day. The day's register comes from the engine in one read and
 *  everything on screen is a view of it: the five tiles are counts of the same
 *  rows the table lists, so they cannot disagree. A past day is shown as it was
 *  recorded, and a day nothing was recorded on says so instead of printing
 *  everybody absent.
 *
 *  Names appear here by face only (green recognised, amber not recognised).
 *  Clothing and tracking numbers never do (rule 1, rule 3). */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToday } from '@/app/SiteContext';
import { useToast } from '@/app/ToastContext';
import { useAsync } from '@/app/useAsync';
import { CameraFrame } from '@/components/CameraFrame';
import {
  Badge, Card, CardHeader, DataNotice, Empty, Field, LoadError, PageHeader, Select,
} from '@/components/ui';
import {
  excusePerson, exportAttendance, getGroups, getRegister, getWeek,
} from '@/services/api';
import { formatDuration, formatLongDate, formatShortDate } from '@/services/format';
import type { Camera, Register, RegisterRow, RegisterStatus, WeekDay } from '@/types';

type Filter = 'all' | RegisterStatus;

const TILES: { filter: Filter; key: 'everyone' | 'onTime' | 'late' | 'notArrived' | 'excused' }[] = [
  { filter: 'all', key: 'everyone' },
  { filter: 'on_time', key: 'onTime' },
  { filter: 'late', key: 'late' },
  { filter: 'absent', key: 'notArrived' },
  { filter: 'excused', key: 'excused' },
];

const EVERYONE = 'Everyone';
const NO_GROUPS: { name: string }[] = [];

function secondsSince(utc: string | undefined): number | null {
  const then = utc ? Date.parse(utc) : Number.NaN;
  return Number.isNaN(then) ? null : Math.max(0, (Date.now() - then) / 1000);
}

export function Attendance() {
  const t = useT();
  const { language } = useLanguage();
  const navigate = useNavigate();
  const toast = useToast();
  const capability = useCapability('attendance');
  const isAdmin = useAccount().role === 'admin';
  const today = useToday();

  // People opens a person here (`?person=<id>&date=`), and Ask arrives with a
  // question already resolved (`?mode=group&subject=Grade 8`, or `?mode=person
  // &subject=Sara Ahmed`). Reading them is what makes the link do something.
  const [params] = useSearchParams();
  const askedMode = params.get('mode');
  const asked = params.get('subject') ?? '';
  const [date, setDate] = useState(params.get('date') ?? '');
  const [group, setGroup] = useState(
    params.get('group') ?? (askedMode === 'group' ? asked : ''));
  const [query, setQuery] = useState(askedMode === 'person' ? asked : '');
  const [filter, setFilter] = useState<Filter>('all');
  const [selectedId, setSelectedId] = useState<string | null>(params.get('person'));
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [marking, setMarking] = useState(false);

  // The picker cannot offer a future day; a typed one is pulled back to today.
  const chosen = date && date <= today ? date : today;
  const isPast = chosen < today;
  const groupName = group || EVERYONE;

  const {
    data: groups,
  } = useAsync(() => getGroups(language), [language], [] as { name: string }[]);
  const groupOptions = useMemo(() => {
    const names = (groups ?? NO_GROUPS).map((g) => g.name);
    if (!names.includes(EVERYONE)) names.unshift(EVERYONE);
    if (group && !names.includes(group)) names.push(group);
    return names;
  }, [groups, group]);

  // Today refreshes by itself, because arrivals keep coming in. A past day is
  // fixed, so it is read once.
  const {
    data: register, error: registerError, loading, reload,
  } = useAsync<Register | null>(
    () => getRegister(chosen, groupName, language),
    [chosen, groupName, language],
    null,
    isPast ? undefined : 20_000,
  );

  // Never show another day's figures under this day's heading.
  const current = register && register.date === chosen ? register : null;
  const recognitionOff = capability?.state === 'unavailable';

  const rows = current?.rows ?? [];
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) =>
      (filter === 'all' || r.status === filter)
      && (!q || r.name.toLowerCase().includes(q) || r.group.toLowerCase().includes(q)));
  }, [rows, filter, query]);

  const selected: RegisterRow | null = useMemo(
    () => rows.find((r) => r.id && r.id === selectedId) ?? null,
    [rows, selectedId],
  );

  const week = useAsync<WeekDay[]>(
    () => (selected ? getWeek(selected.id, chosen, language) : Promise.resolve([])),
    [selected?.id, chosen, language, current?.excused],
    [],
  );

  // A person picked on another day or group may not be on this register.
  useEffect(() => {
    if (selectedId && current && !selected) setSelectedId(null);
  }, [selectedId, current, selected]);

  async function exportSheet() {
    setExporting(true);
    setExportError(null);
    try {
      await exportAttendance({ mode: 'group', group: groupName, date: chosen });
    } catch (error) {
      setExportError(error instanceof Error ? error.message : t('attendance.exportFailed'));
    } finally {
      setExporting(false);
    }
  }

  async function markExcused(row: RegisterRow) {
    setMarking(true);
    try {
      await excusePerson(row.id, chosen);
      toast.show(t('attendance.excusedDone', {
        name: row.name, date: formatShortDate(chosen, language),
      }));
      reload();
    } catch (error) {
      // The engine's plain reason: already arrived, nothing recorded, and so on.
      toast.show(t('attendance.excuseFailed', {
        name: row.name,
        reason: error instanceof Error ? error.message : t('enrol.somethingWentWrong'),
      }), 'bad');
    } finally {
      setMarking(false);
    }
  }

  const doorways: Camera[] = current?.cameras ?? [];
  const tileCount = (filterKey: Filter): number => {
    if (!current) return 0;
    switch (filterKey) {
      case 'all': return current.expected;
      case 'on_time': return current.onTime;
      case 'late': return current.late;
      case 'absent': return current.absent;
      case 'excused': return current.excused;
      default: return 0;
    }
  };

  const nobodyEnrolled = !!current && current.recorded && current.expected === 0 && !isPast;

  return (
    <>
      <DataNotice capability={capability} />
      <LoadError error={registerError} onRetry={reload} what="load.attendanceRegister" />
      <PageHeader title={t('nav.attendance.label')} lead={t('attendance.lead')} />

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
        <button
          type="button"
          className="chip-btn chip-btn--on"
          onClick={() => navigate('/people/enrol')}
        >
          {t('attendance.enrolFace')}
        </button>
        <button
          type="button"
          className="chip-btn chip-btn--off"
          disabled={exporting || !current || recognitionOff}
          onClick={() => void exportSheet()}
          title={t('attendance.downloadCsv', { date: chosen })}
        >
          {t(exporting ? 'attendance.preparing' : 'attendance.exportCsv')}
        </button>
      </div>
      {exportError && (
        <div role="alert" style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--bad)' }}>
          {exportError}
        </div>
      )}

      {/* The doorway strip. Only the cameras attendance is read from, offline
          ones kept in place and marked, never dropped. */}
      <Card>
        <CardHeader title={t('attendance.stripTitle')} />
        {doorways.length === 0 ? (
          <Empty>
            {recognitionOff || !current ? t('attendance.recognitionNotRunning') : t('attendance.noDoorway')}
          </Empty>
        ) : (
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}>
            {doorways.map((camera) => (
              <DoorwayTile key={camera.id} camera={camera} />
            ))}
          </div>
        )}
        {doorways.length > 0 && (
          <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 10 }}>
            {current && current.recognitionElsewhere > 0
              ? t('attendance.doorwayNoteElsewhere', { count: current.recognitionElsewhere })
              : t('attendance.doorwayNote')}
            {doorways.some((c) => c.offline) && <> {t('attendance.offlineNote')}</>}
          </div>
        )}
      </Card>

      {isPast && (
        <div
          role="status"
          style={{
            padding: '11px 14px', borderRadius: 10, marginBottom: 14, fontSize: 13.5,
            background: 'var(--am-bg)', color: 'var(--am)',
          }}
        >
          {t('attendance.pastBanner', { date: formatLongDate(chosen, language) })}
        </div>
      )}

      <Card tight>
        <div className="filters">
          <Field label={t('attendance.group')}>
            <Select
              value={groupOptions.includes(groupName) ? groupName : EVERYONE}
              onChange={(v) => { setGroup(v === EVERYONE ? '' : v); setSelectedId(null); }}
              options={groupOptions}
              label={(o) => (o === EVERYONE ? t('attendance.everyone') : o)}
            />
          </Field>
          <Field label={t('attendance.date')}>
            <input
              className="input"
              type="date"
              value={chosen}
              max={today}
              onChange={(e) => { setDate(e.target.value); setSelectedId(null); }}
            />
          </Field>
          <div style={{ flex: 1, minWidth: 200 }}>
            <Field label={t('attendance.col.name')}>
              <input
                className="input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t('attendance.searchPlaceholder')}
                style={{ width: '100%' }}
              />
            </Field>
          </div>
        </div>
      </Card>

      {!current && loading && <Empty>{t('attendance.loadingRegister')}</Empty>}

      {current && recognitionOff && (
        <Card><Empty>{t('attendance.recognitionNotRunning')}</Empty></Card>
      )}

      {current && !recognitionOff && !current.recorded && (
        <Card>
          <Empty>{t('attendance.nothingRecorded', { date: formatLongDate(chosen, language) })}</Empty>
        </Card>
      )}

      {current && !recognitionOff && current.recorded && nobodyEnrolled && (
        <Card>
          <Empty>
            {t('attendance.nobodyEnrolled')}{' '}
            <button type="button" className="linkbtn" onClick={() => navigate('/people/enrol')}>
              {t('attendance.enrolFirst')}
            </button>
          </Empty>
        </Card>
      )}

      {current && !recognitionOff && current.recorded && !nobodyEnrolled && (
        <>
          <div
            role="group"
            aria-label={t('attendance.tilesLabel')}
            style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', marginBottom: 14 }}
          >
            {TILES.map(({ filter: f, key }) => (
              <button
                key={f}
                type="button"
                className="stat"
                aria-pressed={filter === f}
                onClick={() => setFilter(filter === f && f !== 'all' ? 'all' : f)}
                style={{
                  textAlign: 'start', cursor: 'pointer',
                  border: filter === f ? '2px solid var(--ac)' : '2px solid transparent',
                }}
              >
                <div className="stat__label">{t(`attendance.tile.${key}`)}</div>
                <div className="stat__value">{tileCount(f)}</div>
              </button>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <div style={{ flex: '1 1 520px', minWidth: 0 }}>
              <Card>
                <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginBottom: 8 }}>
                  {t('attendance.rowsShown', { shown: visible.length, total: rows.length })}
                </div>
                <div
                  className="row row--head"
                  style={{ gridTemplateColumns: '1.6fr 1fr .8fr 1.1fr 1fr' }}
                >
                  <span>{t('attendance.col.name')}</span>
                  <span>{t('attendance.col.group')}</span>
                  <span>{t('attendance.col.arrived')}</span>
                  <span>{t('attendance.col.camera')}</span>
                  <span>{t('attendance.col.status')}</span>
                </div>
                {visible.map((r) => (
                  <div
                    key={r.id || r.name}
                    className="row row--click"
                    role="button"
                    tabIndex={0}
                    aria-pressed={selected?.id === r.id}
                    onClick={() => setSelectedId(r.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedId(r.id);
                      }
                    }}
                    style={{
                      gridTemplateColumns: '1.6fr 1fr .8fr 1.1fr 1fr',
                      background: selected?.id === r.id ? 'var(--chip)' : undefined,
                    }}
                  >
                    <span className="row__name">{r.name}</span>
                    <span className="row__muted">{r.group}</span>
                    <span>{r.arrived}</span>
                    <span className="row__muted">{r.camera}</span>
                    <span><Badge tone={r.tone}>{r.label}</Badge></span>
                  </div>
                ))}
                {visible.length === 0 && <Empty>{t('attendance.noOneMatches')}</Empty>}
              </Card>
            </div>

            {selected && (
              <div style={{ flex: '0 1 340px', minWidth: 280 }}>
                <Card>
                  <CardHeader title={selected.name} sub={selected.group} />
                  <div style={{ marginBottom: 10 }}>
                    <Badge tone={selected.tone}>{selected.label}</Badge>
                    {selected.minutesLate ? (
                      <span style={{ marginInlineStart: 8, fontSize: 13, color: 'var(--tx2)' }}>
                        {t('attendance.minutesLate', { minutes: selected.minutesLate })}
                      </span>
                    ) : null}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13.5 }}>
                    <div>
                      <div className="stat__label">{t('attendance.firstSeen')}</div>
                      <div>{selected.arrived || t('attendance.notSeenThatDay')}</div>
                      {selected.camera && <div className="row__muted">{selected.camera}</div>}
                    </div>
                    <div>
                      <div className="stat__label">{t('attendance.lastSeen')}</div>
                      <div>{selected.lastSeen || t('attendance.notSeenThatDay')}</div>
                    </div>
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--tx3)', margin: '8px 0 12px' }}>
                    {t('attendance.noArrivalPicture')}
                  </div>

                  <div className="section-title">{t('attendance.weekTitle')}</div>
                  <LoadError error={week.error} onRetry={week.reload} what="load.attendanceWeek" />
                  {week.loading && <Empty>{t('attendance.weekLoading')}</Empty>}
                  {!week.loading && !week.error && week.data.length === 0 && (
                    <Empty>{t('attendance.weekEmpty')}</Empty>
                  )}
                  {week.data.map((d) => (
                    <div
                      key={d.date}
                      className="row"
                      style={{ gridTemplateColumns: '1.2fr .8fr 1fr' }}
                    >
                      <span>{formatShortDate(d.date, language)}</span>
                      <span className="row__muted">{d.time}</span>
                      <span><Badge tone={d.tone}>{d.label}</Badge></span>
                    </div>
                  ))}

                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
                    {/* Offered for somebody not arrived on a recorded day. The
                        engine decides the rest and its reason is shown. */}
                    {isAdmin && selected.status === 'absent' && (
                      <button
                        type="button"
                        className="chip-btn chip-btn--on"
                        disabled={marking}
                        onClick={() => void markExcused(selected)}
                      >
                        {t(marking ? 'attendance.markingExcused' : 'attendance.markExcused')}
                      </button>
                    )}
                    {/* Disabled on purpose, and it says why: nothing can send
                        a message to a manager yet. Never clickable. */}
                    <button
                      type="button"
                      className="linkbtn"
                      disabled
                      title={t('attendance.notifyManagerWhy')}
                    >
                      {t('attendance.notifyManager')}
                    </button>
                  </div>
                  <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 6 }}>
                    {t('attendance.notifyManagerWhy')}
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <button type="button" className="linkbtn" onClick={() => setSelectedId(null)}>
                      {t('attendance.closeDetail')}
                    </button>
                  </div>
                </Card>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}

/** One doorway camera in the strip. An offline one is not drawn as a picture:
 *  it says why, and how long ago it last sent one. */
function DoorwayTile({ camera }: { camera: Camera }) {
  const t = useT();
  const { language } = useLanguage();
  if (!camera.offline) {
    return (
      <div>
        <CameraFrame camera={camera} size="sm" feature="attendance" tileOverlay />
        <div style={{ fontSize: 13, fontWeight: 600, marginTop: 4 }}>{camera.name}</div>
      </div>
    );
  }
  const seconds = secondsSince(camera.lastPictureUtc);
  return (
    <div
      style={{
        minHeight: 121, borderRadius: 10, padding: 12, background: 'var(--bg)',
        color: 'var(--tx2)', fontSize: 13, display: 'flex', flexDirection: 'column', gap: 4,
        justifyContent: 'center',
      }}
    >
      <div style={{ fontWeight: 600, color: 'var(--tx)' }}>{camera.name}</div>
      <div>
        {seconds === null
          ? t('attendance.offlineNoPicture')
          : t('attendance.offlineSince', { since: formatDuration(seconds, language) })}
      </div>
      {camera.offlineReason && <div>{camera.offlineReason}</div>}
    </div>
  );
}
