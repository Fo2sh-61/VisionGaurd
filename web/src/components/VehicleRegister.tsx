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

import { type MutableRefObject, useEffect, useState } from 'react';
import { Plate } from '@/components/Plate';
import { Badge, Card, Empty, LoadError, Select } from '@/components/ui';
import {
  addVehicle, editVehicle, getVehicleRegister, importVehicles, removeVehicle,
} from '@/services/api';
import { apiBase } from '@/services/http';
import { vehicleCategoryLabel, vehicleCategoryTone } from '@/services/format';
import type * as W from '@/services/wire';
import { useAsync } from '@/app/useAsync';

const NO_VEHICLES: W.RegisteredVehicle[] = [];

const CATEGORIES: [string, string][] = [
  ['all', 'All'],
  ['staff', 'Staff'],
  ['visitor', 'Visitors'],
  ['vip', 'VIP'],
  ['blacklist', 'Blacklisted'],
];

const EMPTY_FORM: W.VehicleRegistration = {
  plate: '', category: 'visitor', owner: '', phone: '', unit: '',
  carMake: '', carColour: '', validUntil: '', notes: '',
};

const inputStyle = {
  height: 42, border: '1px solid var(--line)', borderRadius: 10,
  padding: '0 12px', fontSize: 14, background: 'var(--card)',
  color: 'var(--tx)', outline: 'none', boxSizing: 'border-box' as const,
};

export function VehicleRegisterTab({ isAdmin, prefillPlate }: {
  isAdmin: boolean;
  prefillPlate: MutableRefObject<string | null>;
}) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('all');
  const [form, setForm] = useState<W.VehicleRegistration | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [imported, setImported] = useState<W.VehicleImportResult | null>(null);

  const {
    data: vehicles, error, loading, reload,
  } = useAsync(() => getVehicleRegister(query, category), [query, category],
    NO_VEHICLES);

  // A plate carried over from the Live tab's Register button. Read once and
  // cleared, so switching tabs again does not reopen the form.
  useEffect(() => {
    if (prefillPlate.current) {
      setForm({ ...EMPTY_FORM, plate: prefillPlate.current });
      setEditing(null);
      prefillPlate.current = null;
    }
  }, [prefillPlate]);

  async function save() {
    if (!form?.plate.trim()) {
      setProblem('A vehicle needs a plate. Everything else is optional.');
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (editing) await editVehicle(editing, form);
      else await addVehicle(form);
      setForm(null);
      setEditing(null);
      // Re-read rather than patching in place: the canonical plate and the
      // expiry come from the engine, and inventing them here is how a page
      // shows a save that did not happen the way it thinks it did.
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That was not saved.');
    } finally {
      setBusy(false);
    }
  }

  async function drop(id: string) {
    setBusy(true);
    setProblem(null);
    try {
      await removeVehicle(id);
      setConfirming(null);
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That was not removed.');
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
      reload();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That file was not loaded.');
    } finally {
      setBusy(false);
    }
  }

  const field = (key: keyof W.VehicleRegistration, label: string,
                 placeholder = '', hint = '') => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
        {label}
      </label>
      <input
        value={(form?.[key] as string) ?? ''}
        placeholder={placeholder}
        onChange={(e) => setForm({ ...form!, [key]: e.target.value })}
        style={key === 'plate'
          ? { ...inputStyle, direction: 'rtl', textAlign: 'center',
              fontFamily: "'Noto Sans Arabic', sans-serif", fontSize: 15,
              fontWeight: 700 }
          : inputStyle}
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
          <div style={{ fontWeight: 700, fontSize: 15 }}>Import the vehicle list</div>
          <div style={{
            fontSize: 13, color: 'var(--tx2)', margin: '2px 0 14px', maxWidth: 640,
          }}>
            Download the template, fill in a row per car, and upload it. Column
            headings work in English or Arabic, and either digit system is
            accepted — plates are normalised on the way in, so the same car
            typed two ways lands on one row.
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
              Download template
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
              {busy ? 'Loading…' : 'Upload Excel or CSV'}
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
                <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: 'var(--am)' }}>
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
            {CATEGORIES.map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setCategory(key)}
                style={{
                  padding: '9px 14px', borderRadius: 10, border: 'none',
                  fontSize: 13, fontWeight: 600, cursor: 'pointer',
                  background: category === key ? 'var(--chip)' : 'var(--bg)',
                  color: category === key ? 'var(--ac2)' : 'var(--tx3)',
                }}
              >
                {label}
              </button>
            ))}
          </div>
          {isAdmin && (
            <button
              type="button"
              onClick={() => { setForm({ ...EMPTY_FORM }); setEditing(null); }}
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

        {/* One form for add and edit. A second form for editing is a second
            thing to keep in step, and they drift. */}
        {form && (
          <div style={{
            padding: '22px 0', borderTop: '1px solid var(--line)',
            borderBottom: '1px solid var(--line)', marginBottom: 16,
          }}>
            <div style={{ fontWeight: 700, fontSize: 16 }}>
              {editing ? 'Editing this vehicle' : 'Add a vehicle'}
            </div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 16px' }}>
              {editing
                ? 'Changes apply from this car’s next pass. Its recorded passes are not altered.'
                : 'The plate is the only field that must be filled in. Everything else makes the log readable later.'}
            </div>

            <div style={{
              display: 'grid', gap: 12,
              gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))',
            }}>
              {field('plate', 'Plate', 'ب ج د ١٢٣٤',
                'Arabic or English digits both work — the plate is normalised on save.')}
              {field('owner', 'Owner', 'e.g. Tarek Nassar')}
              {field('phone', 'Phone', '01x xxx xxxx')}
              {field('unit', 'Unit or department', 'e.g. IT')}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <label style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--tx2)' }}>
                  Category
                </label>
                <Select
                  value={vehicleCategoryLabel(form.category ?? 'visitor')}
                  onChange={(label) => setForm({
                    ...form,
                    // `Select` renders its options verbatim, so it is fed the
                    // labels and the value is mapped back here. The engine
                    // rejects anything outside its four categories either way.
                    category: (['staff', 'visitor', 'vip', 'blacklist']
                      .find((c) => vehicleCategoryLabel(c) === label)) ?? 'visitor',
                  })}
                  options={['staff', 'visitor', 'vip', 'blacklist']
                    .map(vehicleCategoryLabel)}
                />
              </div>
              {field('validUntil', 'Permit valid until', 'YYYY-MM-DD',
                'Leave empty for no expiry. Visitors usually want a date.')}
              {field('carMake', 'Car make', 'e.g. Hyundai Elantra')}
              {field('carColour', 'Colour', 'e.g. grey')}
            </div>
            <div style={{ marginTop: 12 }}>
              {field('notes', 'Notes', 'Anything the guard should know')}
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
                {editing ? 'Save changes' : 'Add to the register'}
              </button>
              <button
                type="button"
                onClick={() => { setForm(null); setEditing(null); setProblem(null); }}
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
              ? 'Nothing matches that search.'
              : 'The register is empty. Every car that passes is recorded as '
                + 'not registered until it is on this list — import a '
                + 'spreadsheet, or press Register beside a car on the Live tab '
                + 'to add it with its plate already filled in.'}
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
              <Plate display={vehicle.plateDisplay} compact />
              <span style={{ minWidth: 0 }}>
                <span style={{ fontWeight: 600, fontSize: 14, display: 'block' }}>
                  {vehicle.owner ?? 'No owner recorded'}
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
                  {vehicleCategoryLabel(vehicle.category)}
                </Badge>
              </span>
              <span style={{
                fontSize: 13,
                color: vehicle.expired ? 'var(--am)' : 'var(--tx2)',
              }}>
                {vehicle.validUntil
                  ? `${vehicle.expired ? 'Expired' : 'Valid to'} ${vehicle.validUntil}`
                  : 'No expiry'}
              </span>
              <span style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
                {isAdmin && confirming !== vehicle.id && (
                  <>
                    <button
                      type="button"
                      className="linkbtn"
                      onClick={() => {
                        setEditing(vehicle.id);
                        setForm({
                          plate: vehicle.plateDisplay,
                          category: vehicle.category,
                          owner: vehicle.owner ?? '',
                          phone: vehicle.phone ?? '',
                          unit: vehicle.unit ?? '',
                          carMake: vehicle.carMake ?? '',
                          carColour: vehicle.carColour ?? '',
                          validUntil: vehicle.validUntil ?? '',
                          notes: vehicle.notes ?? '',
                        });
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
                  Remove from the register
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
