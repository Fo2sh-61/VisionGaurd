import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAccount } from '@/app/AuthContext';
import { useAutoRun } from '@/app/useAutoRun';
import { usePageAction } from '@/app/PageChrome';
import { CamGrid } from '@/components/CamGrid';
import { Icon } from '@/components/Icon';
import {
  Badge, Card, DataNotice, Empty, Field, PageHeader, Select, Stats, toneGlyph,
} from '@/components/ui';
import { exportAttendance, getAttendance } from '@/services/api';
import { useChoice, useGroupNames, usePersonNames } from '@/app/useOptions';
import { useToday } from '@/app/SiteContext';
import type { AttendanceMode, AttendanceResult } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/*  Attendance, laid out for a phone (spec 015, P13-FR-052).
 *
 *  Built from `web/src/pages/Attendance.tsx`: the same query, the same
 *  export call, the same wording. What changed is the arrangement: the mode
 *  picker is a seg, the group/person picker opens a bottom sheet instead of a
 *  dropdown, the result leads with a headline figure instead of a table, and
 *  Export sheet moved into the back header (P13-FR-050) - it stays disabled
 *  until there is a result on screen, exactly as the console disables its own
 *  button, and a failure is shown on the page since there is no room in the
 *  header for it.
 *
 *  Unchanged on purpose: Notify parent is a dead button everywhere, because
 *  nothing on this build holds a parent's phone number - the console shows
 *  that on hover, the phone shows it as a line of text instead. */

const MODES: AttendanceMode[] = ['group', 'person'];

/** The label's own initial letters — the label may already be "Unknown". */
function initials(name: string): string {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join('');
}

export function Attendance() {
  const t = useT();
  const { language } = useLanguage();
  const capability = useCapability('attendance');
  const account = useAccount();

  const groups = useGroupNames();
  const people = usePersonNames();
  const today = useToday();

  // Ask arrives here with the question already resolved:
  // `?mode=person&subject=Sara Ahmed&date=2026-08-30`.
  const [params] = useSearchParams();
  const asked = params.get('subject') ?? '';
  const askedMode = params.get('mode');

  const [mode, setMode] = useState<AttendanceMode>(
    askedMode === 'person' || askedMode === 'group' ? askedMode : 'group');
  const [group, setGroup] = useState(askedMode === 'group' ? asked : '');
  const [person, setPerson] = useState(askedMode === 'person' ? asked : '');
  const [date, setDate] = useState(params.get('date') ?? '');

  const selectedGroup = useChoice(groups, group);
  const selectedPerson = useChoice(people, person);
  const selectedDate = date || today;
  const [result, setResult] = useState<AttendanceResult | null>(null);
  const [loading, setLoading] = useState(false);

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setResult(
        await getAttendance({
          mode,
          group: selectedGroup,
          person: selectedPerson,
          date: selectedDate,
        }, language),
      );
    } finally {
      setLoading(false);
    }
  }, [mode, selectedGroup, selectedPerson, selectedDate]);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const exportSheet = useCallback(async () => {
    setExporting(true);
    setExportError(null);
    try {
      // Exports the same query that produced what is on screen, so the file
      // can never disagree with the page it came from.
      await exportAttendance({
        mode,
        group: selectedGroup,
        person: selectedPerson,
        date: selectedDate,
      });
    } catch (error) {
      setExportError(error instanceof Error ? error.message : t('attendance.exportFailed'));
    } finally {
      setExporting(false);
    }
  }, [mode, selectedGroup, selectedPerson, selectedDate]);

  useAutoRun(run);

  const exportDisabled = !result || exporting;
  usePageAction(
    <button
      type="button"
      className="iconbtn"
      aria-label={t(exporting ? 'attendance.preparing' : 'attendance.exportSheet')}
      disabled={exportDisabled}
      onClick={() => void exportSheet()}
    >
      <Icon name="export" size={22} />
    </button>,
    [exportDisabled, exporting, t],
  );

  return (
    <>
      <DataNotice capability={capability} />
      {/* Same fact as the console's PageHeader lead (web/src/pages/Attendance.tsx:93-96) -
          the register is filled in automatically by face recognition, not by a person
          taking roll. The console literal stays the same literal, untranslated. */}
      <PageHeader
        title={t('nav.attendance.label')}
        lead="Recorded automatically by face recognition at the four entrance cameras."
      />

      <Card className="stack">
        <div className="field">
          <span className="field__label" id="attendance-showme">{t('attendance.showMe')}</span>
          <div className="seg" role="group" aria-labelledby="attendance-showme">
            {MODES.map((m) => (
              <button
                key={m}
                type="button"
                className={mode === m ? 'seg__btn seg__btn--on' : 'seg__btn'}
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
              >
                {t(`attendance.mode.${m}` as MessageKey)}
              </button>
            ))}
          </div>
        </div>

        {mode === 'group' ? (
          <Field label={t('attendance.group')}>
            <Select value={selectedGroup} onChange={setGroup} options={groups} />
          </Field>
        ) : (
          <Field label={t('attendance.person')}>
            <Select value={selectedPerson} onChange={setPerson} options={people} />
          </Field>
        )}

        <Field label={t('attendance.date')}>
          <input
            className="input"
            type="date"
            value={selectedDate}
            onChange={(e) => setDate(e.target.value)}
          />
        </Field>

        <button type="button" className="btn btn--block" onClick={() => void run()} disabled={loading}>
          {t(loading ? 'attendance.checking' : 'attendance.show')}
        </button>

        {/* The console only says this on hover (title= on the Export sheet button,
            web/src/pages/Attendance.tsx:139-141) - here it is always-visible text,
            same wording, same keys, telling you what Export sheet in the header
            will do or why it is greyed out. */}
        <p className="note">
          {result
            ? t('attendance.downloadCsv', { date: selectedDate })
            : t('attendance.showRegisterFirst')}
        </p>

        {exportError && (
          <div role="alert" className="notice notice--bad">{exportError}</div>
        )}
      </Card>

      {!result && !loading && <Empty>{t('attendance.chooseFirst')}</Empty>}

      {result && (
        <>
          <Card>
            <div className="hero__value">{result.heading}</div>
            <p className="li__sub" style={{ marginTop: 4 }}>{result.sub}</p>
            <div style={{ marginTop: 14 }}>
              <Stats items={result.stats} />
            </div>
          </Card>

          {result.rows && (
            <>
              <div className="sechead">
                <span className="sechead__title">
                  {t('attendance.needsFollowUp')} · {result.rows.length}
                </span>
              </div>
              {result.rows.map((row) => (
                <Card key={row.name} className="stack">
                  <div className="hstack">
                    <span className="avatar" aria-hidden="true">{initials(row.name)}</span>
                    <span className="li__main">
                      <span className="li__title">{row.name}</span>
                      <span className="li__sub">{row.time}</span>
                    </span>
                    <Badge tone={row.tone} glyph={toneGlyph[row.tone]}>{row.status}</Badge>
                  </div>
                  {/* Disabled on purpose, and it says why. Nothing holds a
                      parent's phone number and there is no way to send a
                      message, so this button did nothing when pressed - which
                      on an absence row reads as a message that went out and
                      did not. */}
                  {account.role === 'admin' ? (
                    <div>
                      <button type="button" className="btn btn--soft btn--block" disabled>
                        {t('attendance.notifyParent')}
                      </button>
                      <p className="note" style={{ marginTop: 6 }}>{t('attendance.notifyParentWhy')}</p>
                    </div>
                  ) : (
                    <p className="note">{t('attendance.adminOnly')}</p>
                  )}
                </Card>
              ))}
            </>
          )}

          {result.days && (
            <>
              <div className="sechead">
                <span className="sechead__title">{t('attendance.recentDays')}</span>
              </div>
              {result.days.map((day) => (
                <Card key={day.date} className="stack">
                  <div className="spread">
                    <span className="li__title">{day.date}</span>
                    <Badge tone={day.tone} glyph={toneGlyph[day.tone]}>{day.status}</Badge>
                  </div>
                  <span className="li__sub">{day.where} · {day.time}</span>
                </Card>
              ))}
            </>
          )}

          <CamGrid
            title={t('attendance.entranceCameras')}
            note={t('attendance.entranceCamerasNote')}
            cameras={result.cameras}
          />
        </>
      )}
    </>
  );
}
