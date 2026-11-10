/** The Live tab: what is waiting, today's tiles, the gate cameras, today's reads.
 *
 *  Split out of `VehicleGate.tsx` so the page holds the tabs and the one
 *  thing they share (the summary), and each tab holds its own state.
 *
 *  Pressing a tile filters the reads table below it, in the browser, over
 *  rows already loaded: the tiles and the rows are the same day counted the
 *  same way, so there is no second request and no way for them to disagree.
 */

import { useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { VehicleAlerts } from '@/components/VehicleAlerts';
import { type PassFilter, VehiclePassesCard } from '@/components/VehiclePasses';
import { VehicleReader } from '@/components/VehicleReader';
import type { RegisterPrefill } from '@/components/VehicleRegister';
import { Card, Empty, LoadError } from '@/components/ui';
import { getVehicleCameras } from '@/services/api';
import type { Camera } from '@/types';
import { useLanguage, useT } from '@/app/LanguageContext';
import { formatCount } from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

/** The camera roster changes when somebody edits it, not on its own. */
const CAMERA_REFRESH_MS = 15_000;

const NO_CAMERAS: Camera[] = [];

/** One stat tile.
 *
 *  **`value` is nullable and that is the whole point of this component.** A
 *  number means the engine measured it. `null` means it declined to claim
 *  one, and the tile shows a dash with the reason underneath rather than a
 *  `0` — because `0` is a measurement, and "no car came through today" and
 *  "we are not looking" must never render identically. SC-010.
 *
 *  A tile with an `onClick` is a button. With none it is a plain figure: the
 *  Left tile with no exit camera has nothing to filter by, and a button that
 *  did nothing would be a dead control.
 */
function Tile({ label, value, note, tone, selected, onClick }: {
  label: string;
  value: number | null;
  note: string;
  tone?: 'accent' | 'warn' | 'bad';
  selected?: boolean;
  onClick?: () => void;
}) {
  // Taken from the context rather than a prop: `toLocaleString()` with no
  // locale followed the BROWSER, so the same count read `1,240` on one
  // machine and `1.240` on the next, in a console two people compare notes
  // over.
  const { language } = useLanguage();
  const colour = value === null ? 'var(--tx3)'
    : tone === 'bad' ? 'var(--rd)'
      : tone === 'warn' ? 'var(--am)'
        : tone === 'accent' ? 'var(--ac)' : 'var(--tx)';

  const body = (
    <>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{label}</div>
      <div style={{
        fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', color: colour,
      }}>
        {value === null ? '—' : formatCount(value, language)}
      </div>
      <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>{note}</div>
    </>
  );

  const style = {
    background: 'var(--card)', borderRadius: 14, padding: '16px 18px',
    boxShadow: 'var(--sh)', textAlign: 'start' as const, font: 'inherit',
    color: 'inherit', display: 'block', width: '100%',
    border: selected ? '2px solid var(--ac)' : '2px solid transparent',
  };

  if (!onClick) return <div style={style}>{body}</div>;
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      style={{ ...style, cursor: 'pointer' }}
    >
      {body}
    </button>
  );
}

export function VehicleLive({
  isAdmin, summary, summaryError, onRegister, onInside,
}: {
  isAdmin: boolean;
  summary: W.GateSummary | null;
  summaryError: string | null;
  onRegister: (prefill: RegisterPrefill) => void;
  /** Inside now is a list of visits, which lives on the Movements tab. */
  onInside: () => void;
}) {
  const { language } = useLanguage();
  const t = useT();
  const [filter, setFilter] = useState<PassFilter>(null);

  const { data: cameras, error: camerasError, loading: camerasLoading } = useAsync(
    () => getVehicleCameras(language), [language], NO_CAMERAS, CAMERA_REFRESH_MS);

  // Only where a gate has both an entry and an exit camera. Without one, an
  // exit can never be matched to an entry, so "inside now" is not a number
  // this engine can produce and must not be drawn as one.
  const paired = summary?.pairingAvailable ?? false;
  // The reader is not running (or every gate camera is failing): the counts
  // are null and `reason` says why. "No cars yet" would then be untrue.
  const stopped = summary !== null && summary.entered === null;

  const press = (key: Exclude<PassFilter, null>) => () =>
    setFilter((now) => (now === key ? null : key));
  const labels: Record<Exclude<PassFilter, null>, string> = {
    entered: t('gate.enteredToday'),
    left: t('gate.leftToday'),
    unknown: t('gate.notRegistered'),
    blacklist: t('gate.blacklisted'),
  };

  return (
    <>
      {/* Above everything, because these are the only things on the page
          that are waiting for somebody to do something. */}
      <VehicleAlerts
        isAdmin={isAdmin}
        onRegister={(alert) => onRegister({
          plate: alert.plate,
          passId: alert.passId,
          renew: alert.kind === 'expired',
        })}
      />

      {/* A request that threw must not leave six dashes on screen: a
          dash means "the engine declined to claim a number", and a failed
          fetch means "we do not know whether it would have". Those read
          identically and are not the same thing. */}
      {summaryError && <LoadError error={summaryError} />}

      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))',
        gap: 12, marginBottom: 14,
      }}>
        <Tile
          label={labels.entered}
          value={summary?.entered ?? null}
          note={summary?.gates
            ? t(summary.gates === 1 ? 'gate.acrossOneGate' : 'gate.acrossGates',
              { count: summary.gates })
            : t('gate.noGateConfigured')}
          selected={filter === 'entered'}
          onClick={press('entered')}
        />
        <Tile
          label={labels.left}
          value={summary?.left ?? null}
          note={t(paired ? 'gate.matchedToEntry' : 'gate.noExitCamera')}
          // A dash is not a count of anything, so there is nothing to filter.
          selected={filter === 'left'}
          onClick={summary?.left == null ? undefined : press('left')}
        />
        <Tile
          label={t('gate.insideNow')}
          value={summary?.inside ?? null}
          note={t(paired ? 'gate.entriesNoExit' : 'gate.needsExitCamera')}
          tone="accent"
          onClick={onInside}
        />
        <Tile
          label={labels.unknown}
          value={summary?.unknown ?? null}
          note={t('gate.loggedNeverBlocked')}
          tone="warn"
          selected={filter === 'unknown'}
          onClick={press('unknown')}
        />
        <Tile
          label={labels.blacklist}
          value={summary?.blacklist ?? null}
          note={t('gate.raisedOnHome')}
          tone="bad"
          selected={filter === 'blacklist'}
          onClick={press('blacklist')}
        />
        {/* A gate camera that is down (or failing every frame) is not
            reading plates, and every other tile looks perfectly healthy
            while it happens. This is the one that says so. It filters
            nothing: it is about the cameras, not about the reads. */}
        <Tile
          label={t('gate.camerasReading')}
          value={summary?.camerasReading ?? null}
          note={summary?.camerasTotal
            ? t(summary.camerasTotal === 1
              ? 'gate.ofOneGateCamera' : 'gate.ofGateCameras',
            { count: summary.camerasTotal })
            : t('gate.noGateCameraConfigured')}
          tone={summary && summary.camerasNote ? 'warn' : undefined}
        />
      </div>

      {/* Which camera is down or failing, and what it costs. Only when one is. */}
      {summary?.camerasNote && (
        <Card>
          <div style={{ fontSize: 13.5, color: 'var(--am)', lineHeight: 1.5 }}>
            {summary.camerasNote}
          </div>
        </Card>
      )}

      {/* The reason the tiles are dashes, said once and in full rather
          than repeated under each one. */}
      {summary?.reason && (
        <Card>
          <div style={{ fontSize: 13.5, color: 'var(--am)', lineHeight: 1.5 }}>
            {summary.reason}
          </div>
        </Card>
      )}

      {camerasError && <LoadError error={camerasError} />}

      {/* No gate camera at all is the state every deployment starts in,
          and an empty grid under a "Gate cameras" heading reads as a
          loading failure. Say which it is. */}
      {!camerasError && !camerasLoading && cameras.length === 0 && (
        <Card>
          <Empty>
            {t('gate.noGateSetUp')}
            <code style={{ margin: '0 4px' }}>engine.yaml</code>
            {t('gate.noGateSetUpAfter')}
          </Empty>
        </Card>
      )}

      {/* `feature="vehicles"` is what keeps names off this grid. The overlay
          request carries the feature and the engine dispatches on it in
          `_boxes`, so a vehicles tile can only ever receive plate boxes —
          recognition is not consulted at all. `detections={false}` would be
          the wrong tool: it switches the overlay off, plate boxes included. */}
      <CamGrid
        title={t('gate.gateCameras')}
        note={t('gate.gateCamerasNote')}
        cameras={cameras}
        feature="vehicles"
        tileOverlay
        // Exactly these, not merged over the roster. A camera with no
        // gate number is not watching a gate, and showing it under this
        // heading would imply plates are being read from it.
        only
      />

      <VehiclePassesCard
        isAdmin={isAdmin}
        filter={filter}
        filterLabel={filter ? labels[filter] : ''}
        onClearFilter={() => setFilter(null)}
        onRegister={onRegister}
        stopped={stopped}
      />

      {/* Under the reads, deliberately: it explains what the boxes above
          are doing, and it is the only place a read that FAILED shows up
          at all — the pass log holds successes by construction. */}
      <VehicleReader isAdmin={isAdmin} />
    </>
  );
}
