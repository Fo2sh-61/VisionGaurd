import { type ReactNode, useState } from 'react';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import { Plate } from '@/components/Plate';
import { PlateEditor } from '@/components/PlateEditor';
import type { RegisterPrefill } from '@/components/VehicleRegister';
import { Badge, Card, CardHeader, Empty, LoadError } from '@/components/ui';
import {
  correctVehiclePlate, deleteVehiclePass, getVehiclePasses,
  getVehicleReader, getVehicleRegister, vehiclePassSnapshotUrl,
} from '@/services/api';
import {
  directionLabel, formatCount, formatTime, plateStatusLabel, plateStatusTone,
} from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** A car passes in seconds. This list is read by somebody at the gate. */
const REFRESH_MS = 3_000;

/** The most reads one day is asked for. A table that silently stopped at the
 *  limit would disagree with the tiles above it, so reaching it is said. */
const DAY_LIMIT = 1_000;

/** How many reads of one plate the panel counts. At the limit it says
 *  "N or more" rather than a total it did not reach. */
const WEEK_LIMIT = 500;

const NONE: W.VehiclePass[] = [];
const NO_VEHICLES: W.RegisteredVehicle[] = [];

/** Which tile is pressed. `null` shows every read. */
export type PassFilter = 'entered' | 'left' | 'unknown' | 'blacklist' | null;

/** Whether a row belongs under a pressed tile. The tiles count the same day
 *  the same way, so a pressed tile and the rows under it always agree. */
export function passMatches(pass: W.VehiclePass, filter: PassFilter): boolean {
  if (filter === 'entered') return pass.direction !== 'exit';
  if (filter === 'left') return pass.direction === 'exit';
  if (filter === 'unknown') return pass.status === 'unknown';
  if (filter === 'blacklist') return pass.status === 'blacklist';
  return true;
}

function Thumb({ pass, size }: { pass: W.VehiclePass; size: 'row' | 'panel' }) {
  const box = size === 'row'
    ? { width: 56, height: 38 } : { width: '100%', height: 190 };
  if (!pass.hasSnapshot) {
    return (
      <span style={{
        display: 'block', ...box, borderRadius: 5,
        border: '1px dashed var(--line)',
      }} />
    );
  }
  return (
    <img
      src={vehiclePassSnapshotUrl(pass.id)}
      alt=""
      loading="lazy"
      style={{
        display: 'block', ...box, objectFit: 'cover', borderRadius: 5,
        border: '1px solid var(--line)',
      }}
    />
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', gap: 14,
      padding: '8px 0', borderTop: '1px solid var(--line)', fontSize: 13.5,
    }}>
      <span style={{ color: 'var(--tx2)' }}>{label}</span>
      <span style={{ fontWeight: 600, textAlign: 'end' }}>{children}</span>
    </div>
  );
}

/** One read opened: the figures behind it, and what an administrator can do.
 *
 *  **No live camera frame here, only the photograph the read was made from.**
 *  A live frame carries recognition boxes with names, and a plate read has no
 *  business showing an identity.
 *
 *  The register is read ONCE, when the panel opens, and not once per row. */
function PassDetail({ pass, isAdmin, onClose, onChanged, onRegister }: {
  pass: W.VehiclePass;
  isAdmin: boolean;
  onClose: () => void;
  onChanged: () => void;
  onRegister: (prefill: RegisterPrefill) => void;
}) {
  const { language } = useLanguage();
  const t = useT();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const { data: matches, error: lookupError } = useAsync(
    () => getVehicleRegister(pass.plate), [pass.plate], NO_VEHICLES);
  const vehicle = matches.find((v) => v.plate === pass.plate) ?? null;

  // The engine's own votes-needed figure, never a number copied here.
  const { data: reader } = useAsync(
    () => getVehicleReader(), [], null as W.GateReaderNow | null);
  const votesNeeded = reader?.votesNeeded ?? 0;

  const { data: week } = useAsync(
    () => getVehiclePasses({
      plate: pass.plate, exact: true, days: 7, limit: WEEK_LIMIT,
    }), [pass.plate], NONE);

  async function fix(plate: string) {
    setBusy(true);
    setProblem(null);
    try {
      await correctVehiclePlate(pass.id, plate);
      setEditing(false);
      toast.show(t('passes.fixedToast'));
      onChanged();
    } catch (err) {
      setProblem(err instanceof Error
        ? err.message : t('passes.plateNotSaved'));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setProblem(null);
    try {
      await deleteVehiclePass(pass.id);
      toast.show(t('passes.removedToast'));
      onClose();
      onChanged();
    } catch (err) {
      setProblem(err instanceof Error
        ? err.message : t('passes.rowNotRemoved'));
      setBusy(false);
    }
  }

  const status = pass.status;

  return (
    <div style={{
      flex: '0 0 360px', maxWidth: '100%', borderInlineStart: '1px solid var(--line)',
      paddingInlineStart: 20, display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
        <Plate display={pass.plateDisplay} large latin />
        <button type="button" className="linkbtn" onClick={onClose}>
          {t('passes.close')}
        </button>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Badge tone={plateStatusTone(status)}>{plateStatusLabel(status)}</Badge>
        {pass.needsReview && <Badge tone="warn">{t('passes.weak')}</Badge>}
        <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
          {pass.gateName} · {directionLabel(pass.direction)} · {formatTime(pass.at, language)}
        </span>
      </div>

      <Thumb pass={pass} size="panel" />
      {!pass.hasSnapshot && (
        <div style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
          {t('passes.detail.noPhoto')}
        </div>
      )}

      <div>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--tx2)' }}>
          {t('passes.detail.vehicle')}
        </div>
        {lookupError ? (
          <div style={{ fontSize: 13, color: 'var(--am)', marginTop: 4 }}>
            {t('passes.detail.lookupFailed')}
          </div>
        ) : vehicle ? (
          <div style={{ fontSize: 13.5, marginTop: 4, lineHeight: 1.5 }}>
            <b>{vehicle.owner ?? t('register.noOwner')}</b>
            {vehicle.unit ? ` · ${vehicle.unit}` : ''}
            <div style={{ color: 'var(--tx2)' }}>
              {[vehicle.carMake, vehicle.carColour].filter(Boolean).join(' · ') || '—'}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 13, color: 'var(--tx3)', marginTop: 4 }}>
            {t('passes.detail.notInRegister')}
          </div>
        )}
      </div>

      <div>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--tx2)', marginBottom: 4 }}>
          {t('passes.detail.reader')}
        </div>
        <Fact label={t('passes.detail.confidence')}>
          {formatCount(Math.round(pass.confidence * 100), language)}%
        </Fact>
        <Fact label={t('passes.detail.votes')}>
          {formatCount(pass.votes, language)}
          {votesNeeded > 0 && ` ${t('passes.detail.votesGuide', {
            needed: formatCount(votesNeeded, language),
          })}`}
        </Fact>
        <Fact label={t('passes.detail.width')}>
          {pass.plateWidth === null
            ? t('passes.detail.widthNone')
            : t('passes.detail.widthPx', {
              px: formatCount(pass.plateWidth, language),
            }) + ` ${t('passes.detail.widthGuide')}`}
        </Fact>
        <Fact label={t('passes.detail.seenWeek')}>
          {week.length >= WEEK_LIMIT
            ? t('passes.detail.seenWeekMore', {
              count: formatCount(WEEK_LIMIT, language),
            })
            : formatCount(week.length, language)}
        </Fact>
        {pass.readPlateDisplay && (
          <Fact label={t('passes.detail.original')}>
            <Plate display={pass.readPlateDisplay} compact />
          </Fact>
        )}
        {pass.correctedBy && (
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', paddingTop: 6 }}>
            {t('passes.detail.typedBy', { name: pass.correctedBy })}
          </div>
        )}
      </div>

      {problem && (
        <div role="alert" style={{ fontSize: 13, color: 'var(--rd)' }}>{problem}</div>
      )}

      {isAdmin && editing && (
        <PlateEditor
          plate={pass.plate}
          busy={busy}
          onCancel={() => setEditing(false)}
          onSave={(plate) => { void fix(plate); }}
        />
      )}

      {isAdmin && !editing && !confirming && (
        <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="linkbtn"
            onClick={() => setEditing(true)}
            title={t('passes.fixTitle')}
          >
            {t('reader.fix')}
          </button>
          {status === 'unknown' && (
            <button
              type="button"
              className="linkbtn"
              onClick={() => onRegister({ plate: pass.plate })}
            >
              {t('passes.addRegister')}
            </button>
          )}
          {status === 'expired' && (
            <button
              type="button"
              className="linkbtn"
              onClick={() => onRegister({ plate: pass.plate, renew: true })}
            >
              {t('passes.renew')}
            </button>
          )}
          {status !== 'blacklist' && (
            <button
              type="button"
              className="linkbtn"
              onClick={() => onRegister({ plate: pass.plate, category: 'blacklist' })}
            >
              {t('passes.addBlacklist')}
            </button>
          )}
          <button
            type="button"
            className="linkbtn"
            onClick={() => setConfirming(true)}
            title={t('passes.removeTitle')}
            style={{ color: 'var(--rd)' }}
          >
            {t('action.remove')}
          </button>
        </div>
      )}

      {isAdmin && confirming && (
        <div style={{
          padding: '12px 14px', background: 'var(--rd-bg)', borderRadius: 10,
          fontSize: 13, color: 'var(--rd)', lineHeight: 1.45,
        }}>
          {t('passes.removeConfirm')}
          <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
            <button
              type="button"
              disabled={busy}
              onClick={() => { void remove(); }}
              style={{
                padding: '8px 14px', borderRadius: 10, border: 'none',
                background: 'var(--rd)', color: '#fff', fontWeight: 600,
                cursor: busy ? 'not-allowed' : 'pointer',
              }}
            >
              {t(busy ? 'passes.removing' : 'passes.removeYes')}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              style={{
                padding: '8px 14px', borderRadius: 10, border: 'none',
                background: 'var(--card)', color: 'var(--tx2)',
                fontWeight: 600, cursor: 'pointer',
              }}
            >
              {t('passes.keep')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Today's reads, newest first, and the panel for the one that is open.
 *
 *  **This list came back on 28 Aug, and why is worth writing down.** It was
 *  removed at the owner's request, on the understanding that "inside now" and
 *  the visit tables would carry the day's record instead. They cannot: both
 *  are derived from *pairing* an entry with an exit, and a gate with one
 *  camera has no exit to pair against, so they correctly refuse to print a
 *  figure. The result was a gate that recorded nine cars and showed none of
 *  them anywhere. A page that hides real recorded data is as dishonest as one
 *  that invents it.
 *
 *  It lives on the Live tab now and is loaded for today only, so the rows and
 *  the tiles above them count the same cars (SC-003).
 */
export function VehiclePassesCard({ isAdmin, filter, filterLabel, onClearFilter, onRegister, stopped }: {
  isAdmin: boolean;
  filter: PassFilter;
  /** The words for the pressed tile, for the line that says it is pressed. */
  filterLabel: string;
  onClearFilter: () => void;
  onRegister: (prefill: RegisterPrefill) => void;
  /** True when the reader is not running. "No cars yet" would then be a
   *  claim about a gate nobody is watching. */
  stopped: boolean;
}) {
  const { language } = useLanguage();
  const t = useT();
  const [openId, setOpenId] = useState<string | null>(null);

  const { data: passes, error, loading, reload } = useAsync(
    () => getVehiclePasses({ days: 1, limit: DAY_LIMIT }), [], NONE, REFRESH_MS);

  const shown = passes.filter((p) => passMatches(p, filter));
  const open = passes.find((p) => p.id === openId) ?? null;

  return (
    <Card>
      <CardHeader
        title={t('passes.title')}
        sub={t(isAdmin ? 'passes.leadAdmin' : 'passes.lead')}
      />

      {!isAdmin && (
        <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginBottom: 10 }}>
          {t('gate.adminOnlyNote')}
        </div>
      )}

      {error && <LoadError error={error} />}

      {filter && (
        <div style={{
          display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
          fontSize: 13, color: 'var(--tx2)', marginBottom: 10,
        }}>
          {t('gate.filterShowing', { label: filterLabel })}
          <button type="button" className="linkbtn" onClick={onClearFilter}>
            {t('gate.filterClear')}
          </button>
        </div>
      )}

      {passes.length >= DAY_LIMIT && (
        <div style={{ fontSize: 12.5, color: 'var(--am)', marginBottom: 10 }}>
          {t('passes.latestOnly', { count: formatCount(DAY_LIMIT, language) })}
        </div>
      )}

      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 480px', minWidth: 0 }}>
          {!error && !loading && shown.length === 0 && (
            <Empty>
              {stopped
                ? t('gate.readerStopped')
                : filter && passes.length > 0
                  ? t('passes.noneFilter') : t('passes.noneToday')}
            </Empty>
          )}

          {shown.map((pass) => (
            <div
              key={pass.id}
              className="row"
              role="button"
              tabIndex={0}
              aria-pressed={pass.id === openId}
              onClick={() => setOpenId(pass.id === openId ? null : pass.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setOpenId(pass.id === openId ? null : pass.id);
                }
              }}
              style={{
                gridTemplateColumns: '68px 120px 1fr .5fr .6fr',
                gap: 14, alignItems: 'center', padding: '12px 8px',
                borderTop: '1px solid var(--line)', cursor: 'pointer',
                background: pass.id === openId ? 'var(--chip)' : 'transparent',
                borderRadius: 8,
              }}
            >
              <Thumb pass={pass} size="row" />
              <Plate display={pass.plateDisplay} />
              <span style={{ minWidth: 0 }}>
                {/* Never blank. "Not in the register" is a fact about the
                    car; an empty cell reads as data we failed to load. */}
                <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
                  {pass.owner ?? t('passes.notInRegister')}
                </span>
                <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                  {pass.gateName} · {directionLabel(pass.direction)}
                </span>
              </span>
              <span style={{
                fontSize: 13, color: 'var(--tx2)',
                fontFamily: 'ui-monospace, Menlo, monospace',
              }}>
                {formatTime(pass.at, language)}
              </span>
              <span style={{
                display: 'flex', gap: 6, justifyContent: 'flex-end', flexWrap: 'wrap',
              }}>
                <Badge tone={plateStatusTone(pass.status)}>
                  {plateStatusLabel(pass.status)}
                </Badge>
                {pass.needsReview && <Badge tone="warn">{t('passes.weak')}</Badge>}
              </span>
            </div>
          ))}
        </div>

        {open && (
          <PassDetail
            key={open.id}
            pass={open}
            isAdmin={isAdmin}
            onClose={() => setOpenId(null)}
            onChanged={reload}
            onRegister={onRegister}
          />
        )}
      </div>
    </Card>
  );
}
