import { useCallback, useState } from 'react';
import { useAccount } from '@/app/AuthContext';
import { useAutoRun } from '@/app/useAutoRun';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Card, CardHeader, DataNotice, Empty, Field, PageHeader, Select, Stats, toneGlyph } from '@/components/ui';
import { exportAttendance, getAttendance } from '@/services/api';
import { useChoice, useGroupNames, usePersonNames } from '@/app/useOptions';
import { useToday } from '@/app/SiteContext';
import type { AttendanceMode, AttendanceResult } from '@/types';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';

/* The picker's values are the modes themselves; the wording comes from the
   catalogue, so a rewording cannot silently change which query runs. */
const MODES: AttendanceMode[] = ['group', 'person'];

export function Attendance() {
  const t = useT();
  const { language } = useLanguage();
  const capability = useCapability('attendance');
  const account = useAccount();

  const groups = useGroupNames();
  const people = usePersonNames();
  const today = useToday();

  const [mode, setMode] = useState<AttendanceMode>('group');
  const [group, setGroup] = useState('');
  const [person, setPerson] = useState('');
  const [date, setDate] = useState('');

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

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title="Attendance"
        lead="Recorded automatically by face recognition at the four entrance cameras."
      />

      <Card tight>
        <div className="filters">
          <Field label={t('attendance.showMe')}>
            <Select
              value={mode}
              onChange={(v) => setMode(v as AttendanceMode)}
              options={MODES}
              label={(o) => t(`attendance.mode.${o}` as MessageKey)}
            />
          </Field>

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

          <button type="button" className="btn" onClick={() => void run()} disabled={loading}>
            {t(loading ? 'attendance.checking' : 'attendance.show')}
          </button>

          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void exportSheet()}
            // Only offer the download once there is a result on screen, so the
            // file always matches what was just looked at.
            disabled={!result || exporting}
            title={result
              ? t('attendance.downloadCsv', { date: selectedDate })
              : t('attendance.showRegisterFirst')}
          >
            {t(exporting ? 'attendance.preparing' : 'attendance.exportSheet')}
          </button>
        </div>

        {exportError && (
          <div
            role="alert"
            style={{
              marginTop: 10,
              fontSize: 13,
              color: 'var(--bad)',
            }}
          >
            {exportError}
          </div>
        )}
      </Card>

      {!result && !loading && <Empty>{t('attendance.chooseFirst')}</Empty>}

      {result && (
        <>
          <Card>
            <CardHeader title={result.heading} sub={result.sub} />
            <Stats items={result.stats} />

            {result.rows && (
              <>
                <div className="section-title">{t('attendance.needsFollowUp')}</div>
                {result.rows.map((row) => (
                  <div
                    key={row.name}
                    className="row"
                    style={{ gridTemplateColumns: '1.4fr 1fr 1fr 1fr' }}
                  >
                    <span className="row__name">{row.name}</span>
                    <span>
                      <Badge tone={row.tone} glyph={toneGlyph[row.tone]}>
                        {row.status}
                      </Badge>
                    </span>
                    <span className="row__muted">{row.time}</span>
                    {/* Disabled on purpose, and it says why. Nothing holds a
                        parent's phone number and there is no way to send a
                        message, so this button did nothing when pressed -
                        which on an absence row reads as a message that went
                        out and did not. */}
                    {account.role === 'admin' ? (
                      <button
                        type="button"
                        className="linkbtn"
                        disabled
                        title={t('attendance.notifyParentWhy')}
                      >
                        {t('attendance.notifyParent')}
                      </button>
                    ) : (
                      <span style={{ color: 'var(--tx3)', fontSize: 13 }}>{t('attendance.adminOnly')}</span>
                    )}
                  </div>
                ))}
              </>
            )}

            {result.days && (
              <>
                <div className="section-title">{t('attendance.recentDays')}</div>
                {result.days.map((day) => (
                  <div
                    key={day.date}
                    className="row"
                    style={{ gridTemplateColumns: '1.2fr 1.2fr .8fr 1fr' }}
                  >
                    <span>{day.date}</span>
                    <span className="row__muted">{day.where}</span>
                    <span>{day.time}</span>
                    <span>
                      <Badge tone={day.tone} glyph={toneGlyph[day.tone]}>
                        {day.status}
                      </Badge>
                    </span>
                  </div>
                ))}
              </>
            )}
          </Card>

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
