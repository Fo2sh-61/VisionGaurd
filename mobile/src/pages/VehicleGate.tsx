import { useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { CamGrid } from '@/components/CamGrid';
import { VehicleAlerts } from '@/components/VehicleAlerts';
import { VehicleMovementsTab } from '@/components/VehicleMovements';
import { VehicleReader } from '@/components/VehicleReader';
import { VehicleRegisterTab } from '@/components/VehicleRegister';
import { DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getVehicleCameras, getVehicleSummary } from '@/services/api';
import type { Camera } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import { formatCount } from '@/services/format';
import { useAsync } from '@/app/useAsync';

/*  Vehicle gate, laid out for a phone (spec 015, contracts/phone-screens.md:
 *  "Vehicle gate. Keep: tabs Live/Movements/Registered with `?tab`. Live: the
 *  six tiles (null -> "—") with their notes, summary and cameras errors,
 *  VehicleAlerts ..., gate cameras `feature="vehicles"`, and VehicleReader.
 *  Movements and Registered stay the console components (R1).").
 *
 *  Built from web/src/pages/VehicleGate.tsx: the same calls, the same three
 *  polls (summary, cameras — VehicleAlerts and VehicleReader keep their own),
 *  the same tab state and `?tab`/`?plate` reads, the same admin-only gating
 *  (the server decides regardless). What changed is the arrangement:
 *
 *  - The tab strip is the phone's `seg`, not the console's chip row.
 *  - The six tiles are the phone's `statgrid` (two across) instead of an
 *    auto-fit grid of four-plus.
 *  - Movements and Registered are the console's own components
 *    (`VehicleMovementsTab`, `VehicleRegisterTab`) rendered unmodified inside
 *    `.legacy` — they are shared files this screen does not own, and `.legacy`
 *    (plus `styles/vehicles.css`) is what keeps their inline column grids from
 *    overflowing a 360px screen. `VehicleReader` gets the same treatment on
 *    Live, for the same reason: its diagnostics table is a raw inline grid. */

/** The tiles change as cars pass, not as fast as the frames do. */
const SUMMARY_REFRESH_MS = 3_000;

/** The camera roster changes when somebody edits it, not on its own. */
const CAMERA_REFRESH_MS = 15_000;

const NO_CAMERAS: Camera[] = [];

type Tab = 'live' | 'movements' | 'register';

const TABS: Tab[] = ['live', 'movements', 'register'];

/** One stat tile.
 *
 *  **`value` is nullable and that is the whole point of this component.** A
 *  number means the engine measured it. `null` means it declined to claim
 *  one, and the tile shows a dash with the reason underneath rather than a
 *  `0` — because `0` is a measurement, and "no car came through today" and
 *  "we are not looking" must never render identically. SC-010. */
function Tile({ label, value, note, tone }: {
  label: string;
  value: number | null;
  note: string;
  tone?: 'accent' | 'warn' | 'bad';
}) {
  // Taken from the context rather than a prop: `toLocaleString()` with no
  // locale followed the BROWSER, so the same count read `1,240` on one
  // machine and `1.240` on the next, in a console two people compare notes
  // over.
  const { language } = useLanguage();
  const colour = value === null ? 'var(--tx2)'
    : tone === 'bad' ? 'var(--rd)'
      : tone === 'warn' ? 'var(--am)'
        : tone === 'accent' ? 'var(--ac)' : 'var(--tx)';

  return (
    <div className="stat">
      <span className="stat__label">{label}</span>
      <span className="stat__value" style={{ color: colour }}>
        {value === null ? '—' : formatCount(value, language)}
      </span>
      <span className="stat__detail">{note}</span>
    </div>
  );
}

export function VehicleGate() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('vehicles');
  // Ask lands here with the question resolved. See Attendance for why
  // reading these matters: a link nothing reads is decoration.
  const [params] = useSearchParams();
  const askedTab = params.get('tab');
  const [tab, setTab] = useState<Tab>(
    askedTab === 'movements' || askedTab === 'register' ? askedTab : 'live');
  // An interface hint only. The server decides, and refuses a write from a
  // guard whatever this screen draws.
  const isAdmin = useAccount().role === 'admin';
  // Set when somebody acts on an unregistered car's alert: the register form
  // opens with the plate already filled in from the read. Seeded from the URL
  // when Ask sent us here to look a plate up, and overwritten by the live
  // alerts when somebody taps one. Same field, two ways of filling it.
  const prefill = useRef<string | null>(params.get('plate'));

  const { data: summary, error: summaryError } = useAsync(
    () => getVehicleSummary(), [], null, SUMMARY_REFRESH_MS);
  const { data: cameras, error: camerasError, loading: camerasLoading } = useAsync(
    () => getVehicleCameras(language), [language], NO_CAMERAS, CAMERA_REFRESH_MS);

  // Only where a gate has both an entry and an exit camera. Without one, an
  // exit can never be matched to an entry, so "inside now" is not a number
  // this engine can produce and must not be drawn as one.
  const paired = summary?.pairingAvailable ?? false;

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('gate.title')} lead={t('gate.lead')} />

      <div className="seg" role="tablist" aria-label={t('gate.title')}>
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={tab === key ? 'seg__btn seg__btn--on' : 'seg__btn'}
            onClick={() => setTab(key)}
          >
            {t(`gate.tab.${key}`)}
          </button>
        ))}
      </div>

      {tab === 'live' && (
        <>
          {/* Above everything, because these are the only things on the
              screen that are waiting for somebody to do something. */}
          <VehicleAlerts
            isAdmin={isAdmin}
            onRegister={(alert) => {
              prefill.current = alert.plateDisplay;
              setTab('register');
            }}
          />

          {/* A request that threw must not leave six dashes on screen: a
              dash means "the engine declined to claim a number", and a failed
              fetch means "we do not know whether it would have". Those read
              identically and are not the same thing. */}
          <LoadError error={summaryError} />

          <div className="statgrid">
            <Tile
              label={t('gate.enteredToday')}
              value={summary?.entered ?? null}
              note={summary?.gates
                ? t(summary.gates === 1 ? 'gate.acrossOneGate' : 'gate.acrossGates',
                  { count: summary.gates })
                : t('gate.noGateConfigured')}
            />
            <Tile
              label={t('gate.leftToday')}
              value={summary?.left ?? null}
              note={t(paired ? 'gate.matchedToEntry' : 'gate.noExitCamera')}
            />
            <Tile
              label={t('gate.insideNow')}
              value={summary?.inside ?? null}
              note={t(paired ? 'gate.entriesNoExit' : 'gate.needsExitCamera')}
              tone="accent"
            />
            <Tile
              label={t('gate.notRegistered')}
              value={summary?.unknown ?? null}
              note={t('gate.loggedNeverBlocked')}
              tone="warn"
            />
            <Tile
              label={t('gate.blacklisted')}
              value={summary?.blacklist ?? null}
              note={t('gate.raisedOnHome')}
              tone="bad"
            />
            {/* Replaced "Needs review", which retired with the pass list —
                weak reads are still recorded and still flagged, they simply
                no longer have a list to be reviewed in. */}
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

          {/* The console only ever says this inside the "Left today" and
              "Inside now" tiles' small print. On a phone, read top to bottom
              rather than tile by tile, it is worth its own line — in the
              console's own words, not a rewritten one. */}
          {summary && !paired && (
            <div className="notice notice--amber">{t('gate.noExitCamera')}</div>
          )}

          {/* Which camera is down, and what it costs. Only when one is. */}
          {summary?.camerasNote && (
            <div className="notice notice--amber">{summary.camerasNote}</div>
          )}

          {/* The reason the tiles are dashes, said once and in full rather
              than repeated under each one. */}
          {summary?.reason && (
            <div className="notice notice--amber">{summary.reason}</div>
          )}

          <LoadError error={camerasError} />

          {/* No gate camera at all is the state every deployment starts in,
              and an empty grid under a "Gate cameras" heading reads as a
              loading failure. Say which it is. */}
          {!camerasError && !camerasLoading && cameras.length === 0 && (
            <div className="card">
              <Empty>
                {t('gate.noGateSetUp')}
                <code style={{ margin: '0 4px' }}>engine.yaml</code>
                {t('gate.noGateSetUpAfter')}
              </Empty>
            </div>
          )}

          {/* `feature="vehicles"` is what keeps names off this grid — the
              overlay request carries the feature and the engine dispatches on
              it in `_boxes`, so a vehicles tile can only ever receive plate
              boxes. `only` draws exactly the cameras with a gate number, not
              the whole roster. */}
          <CamGrid
            title={t('gate.gateCameras')}
            note={t('gate.gateCamerasNote')}
            cameras={cameras}
            feature="vehicles"
            tileOverlay
            only
          />

          {/* Under the cameras, deliberately: it explains what the boxes
              above are doing, and it is the only place a read that FAILED
              shows up at all. A shared file this screen does not own, and its
              diagnostics table is a raw inline column grid — `.legacy` plus
              `styles/vehicles.css` is what keeps it inside 360px. */}
          <div className="legacy vg-vehicles-legacy">
            <VehicleReader isAdmin={isAdmin} />
          </div>
        </>
      )}

      {tab === 'register' && (
        <div className="legacy vg-vehicles-legacy">
          <VehicleRegisterTab isAdmin={isAdmin} prefillPlate={prefill} />
        </div>
      )}

      {tab === 'movements' && (
        <div className="legacy vg-vehicles-legacy">
          <VehicleMovementsTab isAdmin={isAdmin} summary={summary} />
        </div>
      )}
    </>
  );
}
