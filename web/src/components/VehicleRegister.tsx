/** The Registered vehicles tab: import, search, add, edit, remove.
 *
 *  Split out of `VehicleGate.tsx` because one page holding three tabs' worth
 *  of state is how a form's `busy` flag ends up disabling a button on a
 *  different tab.
 *
 *  Two things here are load-bearing rather than cosmetic:
 *
 *  - **An empty register says it is empty and how to fill it.** The design
 *    this was built from shows "2,140 on record"; that figure is invented and
 *    a first-run console must not imply a list exists.
 *  - **Removing a car states what will happen before it happens.** The car
 *    keeps passing and is still photographed — it is the *register entry*
 *    that goes, and its past passes stay. Somebody clicking Remove is
 *    entitled to know that before they click, not after.
 */

import { useEffect, useRef, useState } from 'react';
import { useLanguage, useT } from '@/app/LanguageContext';
import { useToast } from '@/app/ToastContext';
import type { MessageKey } from '@/i18n';
import { Plate } from '@/components/Plate';
import { Badge, Card, Empty, LoadError, Select } from '@/components/ui';
import {
  addVehicle, editVehicle, getVehicleLastImport, getVehicleRegister,
  importVehicles, removeVehicle,
} from '@/services/api';
import { apiBase } from '@/services/http';
import {
  canonicalPlate, foldDigits, formatCount, formatEventTime, vehicleCategoryTone,
} from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

const NO_VEHICLES: W.RegisteredVehicle[] = [];

const CATEGORIES = ['all', 'staff', 'visitors', 'vip', 'blacklist'] as const;

/** The filter chip says "Visitors"; a single car is a "Visitor". Two words in
 *  English, and not necessarily two in Arabic, so both have their own key and
 *  the filter maps back to the engine's `visitor`. */
const CATEGORY_VALUE: Record<(typeof CATEGORIES)[number], string> = {
  all: 'all', staff: 'staff', visitors: 'visitor', vip: 'vip', blacklist: 'blacklist',
};

const EMPTY_FORM: W.VehicleRegistration = {
  plate: '', category: 'visitor', owner: '', phone: '', unit: '',
  carMake: '', carColour: '', validUntil: '', notes: '',
};

/** Somebody acting on a car elsewhere on the page: an alert's Add or Renew, or
 *  a read's Add to blacklist. The form opens with the plate filled in.
 *
 *  `passId` is the alert to clear **after the form has saved**, never before.
 *  `renew` focuses the expiry date. `category` pre-selects a category. */
export interface RegisterPrefill {
  plate: string;
  category?: string;
  passId?: string;
  renew?: boolean;
}

/** A plate shown as "ب ج د ١٢٣٤" back into its two halves for the two inputs.
 *  The number comes out in Western digits, which is what the engine keeps. */
function splitPlate(text: string): { letters: string; number: string } {
  const number = foldDigits(text).replace(/[^0-9]/g, '');
  const letters = text.replace(/[0-9٠-٩۰-۹]/g, '').replace(/\s+/g, ' ').trim();
  return { letters, number };
}

const inputStyle = {
  height: 42, border: '1px solid var(--line)', borderRadius: 10,
  padding: '0 12px', fontSize: 14, background: 'var(--card)',
  color: 'var(--tx)', outline: 'none', boxSizing: 'border-box' as const,
};

export function VehicleRegisterTab({ isAdmin, prefill, onPrefillUsed, onSaved }: {
  isAdmin: boolean;
  prefill: RegisterPrefill | null;
  /** Called once the prefill has been read, so it is not read again. */
  onPrefillUsed: () => void;
  /** The register saved. `passId` is the alert that sent the guard here. */
  onSaved: (passId: string | undefined) => void;
}) {
  const { language } = useLanguage();
  const t = useT();
  const toast = useToast();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [form, setForm] = useState<W.VehicleRegistration | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // The plate is two inputs, joined with a space on save: letters and number
  // are separate halves of a plate and one box invites the wrong order.
  const [letters, setLetters] = useState('');
  const [number, setNumber] = useState('');
  // The alert waiting on this form, and what to say about how it opened.
  const [alertPass, setAlertPass] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [focusDate, setFocusDate] = useState(false);
  const [imported, setImported] = useState<W.VehicleImportResult | null>(null);
  // The last import that actually ran, from the database. The design
  // draws "Last import: 2,140 rows · 6 skipped · 12 Aug" — that line is
  // either a fact or it is absent, and on a fresh register it is absent.
  const { data: lastImport, reload: reloadLastImport } =
    useAsync(() => getVehicleLastImport(), [], null);

  const {
    data: vehicles, error, loading, reload,
  } = useAsync(() => getVehicleRegister(query, category), [query, category],
    NO_VEHICLES);

  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  function openForm(vehicle: W.RegisteredVehicle | null, plate: string) {
    const halves = splitPlate(vehicle ? vehicle.plateDisplay : plate);
    setLetters(halves.letters);
    setNumber(halves.number);
    setEditing(vehicle?.id ?? null);
    setProblem(null);
    setForm(vehicle ? {
      plate: vehicle.plateDisplay,
      category: vehicle.category,
      owner: vehicle.owner ?? '',
      phone: vehicle.phone ?? '',
      unit: vehicle.unit ?? '',
      carMake: vehicle.carMake ?? '',
      carColour: vehicle.carColour ?? '',
      validUntil: vehicle.validUntil ?? '',
      notes: vehicle.notes ?? '',
    } : { ...EMPTY_FORM, plate });
  }

  /** The plate on the register, looked up by its exact canonical form. */
  async function findOnRegister(plate: string): Promise<W.RegisteredVehicle | null> {
    const wanted = canonicalPlate(plate);
    const found = await getVehicleRegister(wanted);
    return found.find((v) => canonicalPlate(v.plate) === wanted) ?? null;
  }

  // A car carried over from the Live tab. Read once and handed back, so
  // switching tabs again does not reopen the form. A plate already on the
  // register opens its EDIT form: adding it again would only be refused.
  useEffect(() => {
    if (!prefill) return;
    const next = prefill;
    onPrefillUsed();
    setAlertPass(next.passId ?? null);
    setFocusDate(Boolean(next.renew));
    setNote(null);
    void (async () => {
      let existing: W.RegisteredVehicle | null = null;
      let lookupFailed = false;
      try {
        existing = await findOnRegister(next.plate);
      } catch {
        lookupFailed = true;
      }
      if (!alive.current) return;
      openForm(existing, next.plate);
      if (next.category) {
        setForm((now) => (now ? { ...now, category: next.category } : now));
      }
      setNote(lookupFailed ? t('register.prefillLookupFailed')
        : existing ? t('register.prefillExists')
          : t('register.prefillNew'));
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill]);

  function close() {
    // Closing without saving leaves the alert where it was, and says so.
    if (alertPass) setNote(t('register.alertKept'));
    else setNote(null);
    setAlertPass(null);
    setForm(null);
    setEditing(null);
    setProblem(null);
    setFocusDate(false);
  }

  async function save() {
    const plate = `${letters.trim()} ${number.trim()}`.trim();
    if (!form || !plate) {
      setProblem(t('register.needsPlate'));
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (!editing && await findOnRegister(plate)) {
        setProblem(t('register.duplicate'));
        return;
      }
      const body = { ...form, plate };
      if (editing) await editVehicle(editing, body);
      else await addVehicle(body);
      const waiting = alertPass ?? undefined;
      setForm(null);
      setEditing(null);
      setAlertPass(null);
      setNote(null);
      setFocusDate(false);
      onSaved(waiting);
      // Re-read rather than patching in place: the canonical plate and the
      // expiry come from the engine, and inventing them here is how a page
      // shows a save that did not happen the way it thinks it did.
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : t('register.notSaved'));
    } finally {
      setBusy(false);
    }
  }

  async function drop(id: string) {
    setBusy(true);
    setProblem(null);
    try {
      await removeVehicle(id);
      toast.show(t('register.removedToast'));
      setConfirming(null);
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : t('register.notRemoved'));
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setBusy(true);
    setProblem(null);
    setImported(null);
    try {
      setImported(await importVehicles(file));
      reloadLastImport();
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : t('register.fileNotLoaded'));
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof W.VehicleRegistration, label: string,
                 placeholder = '', hint = '', autoFocus = false) => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
        {label}
      </label>
      <input
        value={(form?.[key] as string) ?? ''}
        placeholder={placeholder}
        autoFocus={autoFocus}
        onChange={(e) => setForm({ ...form!, [key]: e.target.value })}
        style={inputStyle}
      />
      {hint && (
        <span style={{ fontSize: 11.5, color: 'var(--tx3)', lineHeight: 1.35 }}>
          {hint}
        </span>
      )}
    </div>
  );

  return (
    <>
      {isAdmin && (
        <Card>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{t('register.importTitle')}</div>
          <div style={{
            fontSize: 13, color: 'var(--tx2)', margin: '2px 0 14px', maxWidth: 640,
          }}>
            {t('register.importLead')}
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <a
              href={`${apiBase}/vehicles/template`}
              style={{
                height: 40, padding: '0 18px', border: '1px solid var(--line)',
                borderRadius: 10, background: 'var(--card)', color: 'var(--tx)',
                fontWeight: 600, fontSize: 13.5, display: 'inline-flex',
                alignItems: 'center', textDecoration: 'none',
              }}
            >
              {t('register.downloadTemplate')}
            </a>
            <label
              style={{
                height: 40, padding: '0 18px', border: 'none', borderRadius: 10,
                background: 'var(--ac)', color: 'var(--on-ac)', fontWeight: 600,
                fontSize: 13.5, cursor: busy ? 'not-allowed' : 'pointer',
                display: 'inline-flex', alignItems: 'center',
                opacity: busy ? 0.6 : 1,
              }}
            >
              {t(busy ? 'register.uploading' : 'register.upload')}
              <input
                type="file"
                accept=".csv,.xlsx,.xlsm"
                disabled={busy}
                style={{ display: 'none' }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                  e.target.value = '';
                }}
              />
            </label>

            {/* A fact or nothing. "0 rows imported" reads as a failed import
                rather than as an import that never happened, so a register
                nobody has ever imported into shows no line at all. */}
            {lastImport && (
              <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                {/* One sentence from the catalogue, not three fragments
                    concatenated here. Joined in JSX it could only ever be
                    English, and the counts followed the BROWSER's number
                    format rather than the console's - so the same import
                    read `1,240` on one machine and `1.240` on the next. */}
                {t('register.lastImport', {
                  added: formatCount(lastImport.added, language),
                })}
                {lastImport.skipped > 0
                  && ` · ${t('register.lastImportSkipped', {
                    count: formatCount(lastImport.skipped, language),
                  })}`}
                {lastImport.rejected > 0
                  && ` · ${t('register.lastImportRejected', {
                    count: formatCount(lastImport.rejected, language),
                  })}`}
                {' · '}{formatEventTime(lastImport.at, language)}
              </span>
            )}
          </div>

          {/* Never a bare count. Every rejected row is named, because an
              office that believes a list is loaded finds out at the gate. */}
          {imported && (
            <div style={{ marginTop: 14, fontSize: 13, lineHeight: 1.5 }}>
              <div style={{ color: 'var(--tx2)' }}>
                {imported.added} added
                {imported.skippedDuplicates > 0
                  && ` · ${imported.skippedDuplicates} already on the list, updated`}
                {imported.problems.length > 0
                  && ` · ${imported.problems.length} not loaded`}
              </div>
              {imported.problems.length > 0 && (
                <ul style={{ margin: '8px 0 0', paddingInlineStart: 18, color: 'var(--am)' }}>
                  {imported.problems.map((p) => <li key={p}>{p}</li>)}
                </ul>
              )}
            </div>
          )}
        </Card>
      )}

      <Card>
        <div style={{
          display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
          marginBottom: 16,
        }}>
          <input
            value={query}
            placeholder="Search plate, owner, phone or unit…"
            onChange={(e) => setQuery(e.target.value)}
            style={{ ...inputStyle, flex: 1, minWidth: 200, height: 42, fontSize: 14.5 }}
          />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {CATEGORIES.map((chip) => (
              <button
                key={chip}
                type="button"
                onClick={() => setCategory(CATEGORY_VALUE[chip])}
                style={{
                  padding: '9px 14px', borderRadius: 10, border: 'none',
                  fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  background: category === CATEGORY_VALUE[chip] ? 'var(--chip)' : 'var(--bg)',
                  color: category === CATEGORY_VALUE[chip] ? 'var(--ac2)' : 'var(--tx3)',
                }}
              >
                {t(`vehicle.category.${chip}` as MessageKey)}
              </button>
            ))}
          </div>
          {isAdmin && (
            <button
              type="button"
              onClick={() => { setNote(null); setAlertPass(null); openForm(null, ''); }}
              style={{
                padding: '10px 17px', borderRadius: 10, border: 'none',
                background: 'var(--ac)', color: 'var(--on-ac)',
                fontSize: 13, fontWeight: 600, cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              + Add a vehicle
            </button>
          )}
        </div>

        {!isAdmin && (
          <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginBottom: 12 }}>
            {t('gate.adminOnlyNote')}
          </div>
        )}

        {note && !form && (
          <div role="status" style={{
            fontSize: 13, color: 'var(--am)', marginBottom: 12,
          }}>
            {note}
          </div>
        )}

        {/* One form for add and edit. A second form for editing is a second
            thing to keep in step, and they drift. */}
        {form && (
          <div style={{
            padding: '22px 0', borderTop: '1px solid var(--line)',
            borderBottom: '1px solid var(--line)', marginBottom: 16,
          }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              {t(editing ? 'register.editing' : 'register.adding')}
            </div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 16px' }}>
              {t(editing ? 'register.editingLead' : 'register.addingLead')}
            </div>

            <div style={{
              display: 'grid', gap: 12,
              gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))',
            }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
                  {t('register.plate')}
                </label>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    value={letters}
                    aria-label={t('register.plateLetters')}
                    placeholder="ب ج د"
                    onChange={(e) => setLetters(e.target.value)}
                    style={{
                      ...inputStyle, flex: 1, minWidth: 0, direction: 'rtl',
                      textAlign: 'center', fontFamily: "'Noto Sans Arabic', sans-serif",
                      fontSize: 15, fontWeight: 700,
                    }}
                  />
                  <input
                    value={number}
                    aria-label={t('register.plateNumber')}
                    placeholder="1234"
                    inputMode="numeric"
                    dir="ltr"
                    onChange={(e) => setNumber(e.target.value)}
                    style={{
                      ...inputStyle, width: 90, textAlign: 'center',
                      fontSize: 15, fontWeight: 700,
                    }}
                  />
                </div>
                <span style={{ fontSize: 11.5, color: 'var(--tx3)', lineHeight: 1.35 }}>
                  {t('register.plateHint')}
                </span>
              </div>
              {field('owner', t('register.owner'), t('register.ownerPlaceholder'))}
              {field('phone', t('register.phone'), t('register.phonePlaceholder'))}
              {field('unit', t('register.unit'), t('register.unitPlaceholder'))}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
                  {t('register.category')}
                </label>
                {/* The option values are the engine's own categories now.
                    They used to be the English labels, mapped back by
                    comparing strings — which meant an Arabic label could
                    never have matched, and rewording one silently changed
                    which category was saved. */}
                <Select
                  value={form.category ?? 'visitor'}
                  onChange={(category) => setForm({ ...form, category })}
                  options={['staff', 'visitor', 'vip', 'blacklist']}
                  label={(c) => t(`vehicle.category.${c}` as MessageKey)}
                />
              </div>
              {field('validUntil', t('register.validUntil'), 'YYYY-MM-DD',
                t('register.validUntilHint'), focusDate)}
              {field('carMake', t('register.carMake'), t('register.carMakePlaceholder'))}
              {field('carColour', t('register.colour'), t('register.colourPlaceholder'))}
            </div>
            {note && (
              <div role="status" style={{
                marginTop: 12, fontSize: 13, color: 'var(--tx2)',
              }}>
                {note}
                {focusDate && ` ${t('register.renewHint')}`}
                {form.category === 'blacklist'
                  && ` ${t('register.blacklistHint')}`}
              </div>
            )}
            <div style={{ marginTop: 12 }}>
              {field('notes', t('register.notes'), t('register.notesPlaceholder'))}
            </div>

            {problem && (
              <div role="alert" style={{
                marginTop: 14, padding: '10px 13px', borderRadius: 10,
                background: 'var(--rd-bg)', color: 'var(--rd)', fontSize: 13.5,
              }}>
                {problem}
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 16, flexWrap: 'wrap' }}>
              <button
                type="button"
                disabled={busy}
                onClick={() => void save()}
                style={{
                  height: 42, padding: '0 20px', border: 'none', borderRadius: 10,
                  background: 'var(--ac)', color: 'var(--on-ac)', fontWeight: 600,
                  fontSize: 13.5, cursor: busy ? 'not-allowed' : 'pointer',
                  opacity: busy ? 0.6 : 1,
                }}
              >
                {t(editing ? 'register.saveChanges' : 'register.addToRegister')}
              </button>
              <button
                type="button"
                onClick={close}
                style={{
                  height: 42, padding: '0 18px', border: '1px solid var(--line)',
                  borderRadius: 10, background: 'var(--card)', color: 'var(--tx)',
                  fontWeight: 600, fontSize: 13.5, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                Takes effect at the gates immediately — no restart.
              </span>
            </div>
          </div>
        )}

        {error && <LoadError error={error} />}

        {!error && !loading && vehicles.length === 0 && (
          <Empty>
            {query || category !== 'all'
              ? t('register.noMatch')
              : t('register.empty')}
          </Empty>
        )}

        {vehicles.map((vehicle) => (
          <div key={vehicle.id}>
            <div
              className="row"
              style={{
                gridTemplateColumns: '120px 1.2fr .8fr .8fr .9fr 118px',
                gap: 12, alignItems: 'center', padding: '13px 0',
                borderTop: '1px solid var(--line)',
              }}
            >
              <Plate display={vehicle.plateDisplay} compact latin />
              <span style={{ minWidth: 0 }}>
                <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
                  {vehicle.owner ?? t('register.noOwner')}
                </span>
                <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                  {[vehicle.carMake, vehicle.carColour].filter(Boolean).join(' · ') || '—'}
                </span>
              </span>
              <span style={{ fontSize: 13.5, color: 'var(--tx2)' }}>
                {vehicle.unit ?? '—'}
              </span>
              <span>
                <Badge tone={vehicleCategoryTone(vehicle.category)}>
                  {t(`vehicle.category.${vehicle.category}` as MessageKey)}
                </Badge>
              </span>
              <span style={{
                fontSize: 13,
                color: vehicle.expired ? 'var(--am)' : 'var(--tx2)',
              }}>
                {vehicle.validUntil
                  ? `${t(vehicle.expired ? 'register.expired' : 'register.validTo')} ${vehicle.validUntil}`
                  : t('register.noExpiry')}
              </span>
              <span style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                {isAdmin && confirming !== vehicle.id && (
                  <>
                    <button
                      type="button"
                      className="linkbtn"
                      onClick={() => {
                        setNote(null);
                        setAlertPass(null);
                        setFocusDate(false);
                        openForm(vehicle, vehicle.plateDisplay);
                      }}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="linkbtn"
                      style={{ color: 'var(--rd)' }}
                      onClick={() => setConfirming(vehicle.id)}
                    >
                      Remove
                    </button>
                  </>
                )}
              </span>
            </div>

            {/* States what will actually happen, in full, before it happens.
                "Are you sure?" tells somebody nothing they did not know. */}
            {confirming === vehicle.id && (
              <div style={{
                display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
                fontSize: 13, color: 'var(--rd)', padding: '12px 14px',
                background: 'var(--rd-bg)', borderRadius: 10, marginBottom: 8,
              }}>
                <span style={{ flex: '1 1 340px', lineHeight: 1.45 }}>
                  Remove <b>{vehicle.plateDisplay}</b>
                  {vehicle.owner ? ` — ${vehicle.owner}` : ''}? The car keeps
                  passing and is still photographed, but from its next pass it
                  is logged as <b>not registered</b>. Its past passes are kept.
                  This cannot be undone.
                </span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void drop(vehicle.id)}
                  style={{
                    padding: '8px 14px', borderRadius: 10, border: 'none',
                    background: 'var(--rd)', color: '#fff', fontWeight: 600,
                    cursor: busy ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
                  }}
                >
                  {t('register.removeFromRegister')}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(null)}
                  style={{
                    padding: '8px 14px', borderRadius: 10, border: 'none',
                    background: 'var(--card)', color: 'var(--tx2)',
                    fontWeight: 600, cursor: 'pointer', whiteSpace: 'nowrap',
                  }}
                >
                  Keep it
                </button>
              </div>
            )}
          </div>
        ))}

        {vehicles.length > 0 && (
          <div style={{
            marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--line)',
            fontSize: 13, color: 'var(--tx2)', lineHeight: 1.5,
          }}>
            {vehicles.length} {vehicles.length === 1 ? 'vehicle' : 'vehicles'}
            {' '}· a car that is not on this list still passes and is still
            recorded — it is logged as not registered, never blocked by the
            software.
          </div>
        )}
      </Card>
    </>
  );
}
