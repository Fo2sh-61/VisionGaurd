import { useRef, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { VehicleAlerts } from '@/components/VehicleAlerts';
import { VehicleMovementsTab } from '@/components/VehicleMovements';
import { VehicleReader } from '@/components/VehicleReader';
import { VehicleRegisterTab } from '@/components/VehicleRegister';
import { Card, DataNotice, Empty, LoadError, PageHeader } from '@/components/ui';
import { getVehicleCameras, getVehicleSummary } from '@/services/api';
import type { Camera } from '@/types';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useLanguage, useT } from '@/app/LanguageContext';
import { formatCount } from '@/services/format';
import { useAsync } from '@/app/useAsync';

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
 *  "we are not looking" must never render identically. SC-010.
 */
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
  const colour = value === null ? 'var(--tx3)'
    : tone === 'bad' ? 'var(--rd)'
      : tone === 'warn' ? 'var(--am)'
        : tone === 'accent' ? 'var(--ac)' : 'var(--tx)';

  return (
    <div style={{
      background: 'var(--card)', borderRadius: 14, padding: '16px 18px',
      boxShadow: 'var(--sh)',
    }}>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)' }}>{label}</div>
      <div style={{
        fontSize: 26, fontWeight: 700, letterSpacing: '-.02em', color: colour,
      }}>
        {value === null ? '—' : formatCount(value, language)}
      </div>
      <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.35 }}>{note}</div>
    </div>
  );
}

export function VehicleGate() {
  const { language } = useLanguage();
  const t = useT();
  const capability = useCapability('vehicles');
  const [tab, setTab] = useState<Tab>('live');
  // An interface hint only. The server decides, and refuses a write from a
  // guard whatever this page draws.
  const isAdmin = useAccount().role === 'admin';
  // Set when somebody acts on an unregistered car's alert: the register form
  // opens with the plate already filled in from the read. With the pass list
  // gone this is the only route from "a car nobody knows just drove in" to a
  // register entry, which is why the alert carries the action rather than
  // merely announcing the problem.
  const prefill = useRef<string | null>(null);

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
      <PageHeader
        title={t('gate.title')}
        lead={t('gate.lead')}
      />

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
        {TABS.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className="chip-btn"
            style={{
              background: tab === key ? 'var(--card)' : 'transparent',
              color: tab === key ? 'var(--ac)' : 'var(--tx2)',
              boxShadow: tab === key ? 'var(--sh)' : 'none',
              border: 'none', borderRadius: 10, padding: '9px 16px',
              fontSize: 13.5, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {t(`gate.tab.${key}`)}
          </button>
        ))}
      </div>

      {tab === 'live' && (
        <>
          {/* Above everything, because these are the only things on the page
              that are waiting for somebody to do something. */}
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
          {summaryError && <LoadError error={summaryError} />}

          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))',
            gap: 12, marginBottom: 14,
          }}>
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
                no longer have a list to be reviewed in. This answers a
                question that stayed unanswerable: a gate camera that is down
                is not reading plates, and every other tile looks perfectly
                healthy while it happens. */}
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

          {/* Which camera is down, and what it costs. Only when one is. */}
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
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', lineHeight: 1.5 }}>
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

          {/* The pass list that stood here is gone, and the engine still
              records every pass exactly as before — the photograph, the
              crop, the confidence, the votes and the review flag. What
              changed is the console: the owner asked for it on 27 Aug
              knowing the costs (P6-FR-052). Registering from a read now
              lives on the alert above; the day's record lives in the
              Movements export. */}

          {/* `feature="vehicles"` is what keeps names off this grid, and it
              is worth being precise about why. The overlay request carries
              the feature (`getCameraDetections(id, feature)`) and the engine
              dispatches on it in `_boxes`, so a vehicles tile can only ever
              receive plate boxes — recognition is not consulted at all.

              `detections={false}` would be the wrong tool here: it switches
              the overlay off entirely, taking the plate boxes with it. That
              flag is for a tile showing a bare picture with no feature named,
              where the poll would otherwise fall through to faces. */}
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

          {/* Under the cameras, deliberately: it explains what the boxes above
              are doing, and it is the only place a read that FAILED shows up
              at all — the pass log holds successes by construction. */}
          <VehicleReader isAdmin={isAdmin} />
        </>
      )}

      {tab === 'register' && (
        <VehicleRegisterTab isAdmin={isAdmin} prefillPlate={prefill} />
      )}

      {tab === 'movements' && (
        <VehicleMovementsTab isAdmin={isAdmin} summary={summary} />
      )}
    </>
  );
}
