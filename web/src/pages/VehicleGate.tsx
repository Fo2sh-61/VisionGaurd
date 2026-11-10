import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { VehicleLive } from '@/components/VehicleLive';
import { VehicleMovementsTab } from '@/components/VehicleMovements';
import { type RegisterPrefill, VehicleRegisterTab } from '@/components/VehicleRegister';
import { DataNotice, LoadError, PageHeader } from '@/components/ui';
import { dismissVehicleAlert, getVehicleSummary } from '@/services/api';
import { useAccount } from '@/app/AuthContext';
import { useCapability } from '@/app/CapabilityContext';
import { useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import { canonicalPlate } from '@/services/format';
import { useAsync } from '@/app/useAsync';

/** The tiles change as cars pass, not as fast as the frames do. */
const SUMMARY_REFRESH_MS = 3_000;

type Tab = 'live' | 'movements' | 'register';

const TABS: Tab[] = ['live', 'movements', 'register'];

export function VehicleGate() {
  const t = useT();
  const toast = useToast();
  const capability = useCapability('vehicles');
  // Ask lands here with the question resolved. See Attendance for why
  // reading these matters: a link nothing reads is decoration.
  const [params] = useSearchParams();
  const askedTab = params.get('tab');
  const askedPlate = params.get('plate');
  const [tab, setTab] = useState<Tab>(
    askedTab === 'movements' || askedTab === 'register' ? askedTab : 'live');
  // An interface hint only. The server decides, and refuses a write from a
  // guard whatever this page draws.
  const isAdmin = useAccount().role === 'admin';
  // Set when somebody acts on a car: an alert's Add or Renew, or a read's
  // Add to blacklist. The register form opens with the plate filled in, and
  // `passId` (alerts only) is the alert to clear **once the form has saved**.
  // Seeded from the URL when Ask sent us here to look a plate up.
  const [prefill, setPrefill] = useState<RegisterPrefill | null>(
    askedPlate && askedTab === 'register'
      ? { plate: canonicalPlate(askedPlate) } : null);

  const { data: summary, error: summaryError } = useAsync(
    () => getVehicleSummary(), [], null, SUMMARY_REFRESH_MS);

  function register(next: RegisterPrefill) {
    setPrefill(next);
    setTab('register');
  }

  /** The register saved, so the alert that sent the guard here is dealt with.
   *  Not before: closing the form must leave the alert waiting. A dismissal
   *  that raced another screen comes back 409, which is not an error here. */
  async function saved(passId: string | undefined) {
    toast.show(t('register.savedToast'));
    if (!passId) return;
    try {
      await dismissVehicleAlert(passId, true);
    } catch {
      // Already cleared elsewhere, or the engine refused: the alerts strip
      // shows what is actually still waiting when the Live tab is next open.
    }
  }

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader
        title={t('gate.title')}
        lead={t('gate.lead')}
      />

      {/* A summary request that threw must not leave dashes on screen: a
          dash means "the engine declined to claim a number", and a failed
          fetch means "we do not know whether it would have". */}
      {summaryError && <LoadError error={summaryError} />}

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
        <VehicleLive
          isAdmin={isAdmin}
          summary={summary}
          onRegister={register}
          onInside={() => setTab('movements')}
        />
      )}

      {tab === 'register' && (
        <VehicleRegisterTab
          isAdmin={isAdmin}
          prefill={prefill}
          onPrefillUsed={() => setPrefill(null)}
          onSaved={(passId) => { void saved(passId); }}
        />
      )}

      {tab === 'movements' && (
        <VehicleMovementsTab isAdmin={isAdmin} summary={summary} />
      )}
    </>
  );
}
