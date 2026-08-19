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

const MODES: Record<string, AttendanceMode> = {
  'A whole group': 'group',
  'One person': 'person',
};

export function Attendance() {
  const capability = useCapability('attendance');
  const account = useAccount();

  const groups = useGroupNames();
  const people = usePersonNames();
  const today = useToday();

  const [modeLabel, setModeLabel] = useState('A whole group');
  const [group, setGroup] = useState('');
  const [person, setPerson] = useState('');
  const [date, setDate] = useState('');

  const selectedGroup = useChoice(groups, group);
  const selectedPerson = useChoice(people, person);
  const selectedDate = date || today;
  const [result, setResult] = useState<AttendanceResult | null>(null);
  const [loading, setLoading] = useState(false);

  const mode = MODES[modeLabel];

  const run = useCallback(async () => {
    setLoading(true);
    try {
      setResult(
        await getAttendance({
          mode,
          group: selectedGroup,
          person: selectedPerson,
          date: selectedDate,
        }),
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
      setExportError(error instanceof Error ? error.message : 'Export failed');
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
          <Field label="Show me">
            <Select value={modeLabel} onChange={setModeLabel} options={Object.keys(MODES)} />
          </Field>

          {mode === 'group' ? (
            <Field label="Group">
              <Select value={selectedGroup} onChange={setGroup} options={groups} />
            </Field>
          ) : (
            <Field label="Person">
              <Select value={selectedPerson} onChange={setPerson} options={people} />
            </Field>
          )}

          <Field label="Date">
            <input
              className="input"
              type="date"
              value={selectedDate}
              onChange={(e) => setDate(e.target.value)}
            />
          </Field>

          <button type="button" className="btn" onClick={() => void run()} disabled={loading}>
            {loading ? 'Checking…' : 'Show'}
          </button>

          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => void exportSheet()}
            // Only offer the download once there is a result on screen, so the
            // file always matches what was just looked at.
            disabled={!result || exporting}
            title={result ? `Download ${selectedDate} as CSV` : 'Show a register first'}
          >
            {exporting ? 'Preparing…' : 'Export sheet'}
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

      {!result && !loading && <Empty>Choose a group and date, then press Show.</Empty>}

      {result && (
        <>
          <Card>
            <CardHeader title={result.heading} sub={result.sub} />
            <Stats items={result.stats} />

            {result.rows && (
              <>
                <div className="section-title">Needs follow-up</div>
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
                    {account.role === 'admin' ? (
                      <button type="button" className="linkbtn">
                        Notify parent
                      </button>
                    ) : (
                      <span style={{ color: 'var(--tx3)', fontSize: 13 }}>Admin only</span>
                    )}
                  </div>
                ))}
              </>
            )}

            {result.days && (
              <>
                <div className="section-title">Recent days</div>
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
            title="Entrance cameras"
            note="Face recognition runs on these 4 cameras only. Green box = recognised, red = not enrolled."
            cameras={result.cameras}
          />
        </>
      )}
    </>
  );
}
