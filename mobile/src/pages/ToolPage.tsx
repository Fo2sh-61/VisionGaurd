import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { CamGrid } from '@/components/CamGrid';
import { Badge, Stats } from '@/components/ui';
import { runTool } from '@/services/api';
import { TOOL_DEFS, WEAPON_LIVE_CAMERA, WEAPON_STEPS, ZONES } from '@/services/mockData';
import type { MapArea, MapZone, ToolAnswer, ToolId, Tone, WeaponState, Zone } from '@/types';

/** Tools whose fields are filters rather than required inputs — the design
 *  runs these the moment the screen opens, from any entry point. */
const ALWAYS_AUTO_RUN: ToolId[] = ['count', 'weapon', 'intrude'];

export function ToolPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const requestedAutoRun = (location.state as { autoRun?: boolean } | null)?.autoRun === true;

  const def = id ? TOOL_DEFS[id] : undefined;
  const toolId = (def?.id ?? 'attend') as ToolId;

  const [values, setValues] = useState<Record<string, string>>({});
  const [searching, setSearching] = useState(false);
  const [answer, setAnswer] = useState<ToolAnswer | null>(null);
  const [weaponState, setWeaponState] = useState<WeaponState>('clear');
  const [zones, setZones] = useState<Zone[]>(ZONES);
  const ran = useRef<string | null>(null);

  useEffect(() => {
    setValues({});
    setAnswer(null);
    setWeaponState('clear');
    ran.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function fieldValue(key: string, fallback: string) {
    return values[key] ?? fallback;
  }

  async function run() {
    if (!def) return;
    if (toolId === 'lost') {
      setSearching(true);
      setAnswer(null);
    }
    const collected: Record<string, string> = {};
    for (const f of def.fields) collected[f.key] = fieldValue(f.key, f.options[0]);
    const result = await runTool(toolId, collected);
    setSearching(false);
    setAnswer(result);
  }

  useEffect(() => {
    if (!def || ran.current === toolId) return;
    if (requestedAutoRun || ALWAYS_AUTO_RUN.includes(toolId)) {
      ran.current = toolId;
      void run();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolId, requestedAutoRun]);

  if (!def) return null;

  const isTrack = toolId === 'track';
  const isIntrude = toolId === 'intrude';
  const isWeapon = toolId === 'weapon';
  const showEmpty = !answer && !searching && !!def.emptyText;
  const showSummary = !!answer && !(isWeapon && weaponState !== 'clear');

  function toggleZone(index: number) {
    setZones((current) => current.map((z, i) => (i === index ? { ...z, enabled: !z.enabled } : z)));
  }

  return (
    <div>
      <div className="tool-header" style={{ padding: '0 20px 14px' }}>
        <button type="button" className="tool-header__back" onClick={() => navigate(-1)}>
          ‹
        </button>
        <div className="tool-header__title">{def.title}</div>
      </div>
      <p style={{ padding: '0 20px 6px', fontSize: 13.5, color: 'var(--tx2)', lineHeight: 1.4 }}>{def.lead}</p>

      {isTrack && (
        <div className="notice notice--amber" style={{ margin: '12px 20px 0' }}>
          ⚑ Every tracking search is recorded in the audit log with your name.
        </div>
      )}

      <div className="card" style={{ margin: '14px 20px' }}>
        <div className="stack">
          {def.fields.map((f) => (
            <label className="field" key={f.key}>
              <span className="field__label">{f.label}</span>
              <select
                className="input"
                value={fieldValue(f.key, f.options[0])}
                onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
              >
                {f.options.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </label>
          ))}
          <button type="button" className="btn" onClick={() => void run()}>
            {def.runLabel}
          </button>
        </div>
      </div>

      {showEmpty && <div className="empty">{def.emptyText}</div>}

      {searching && (
        <div className="card" style={{ margin: '0 20px' }}>
          <div style={{ fontWeight: 700, fontSize: 15.5 }}>Searching footage…</div>
          <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '3px 0 14px', lineHeight: 1.4 }}>
            Checking 42 cameras across the selected area and time.
          </div>
          <div className="progress">
            <div className="progress__scanner" />
          </div>
        </div>
      )}

      {isWeapon && answer && <WeaponWorkflow state={weaponState} setState={setWeaponState} />}

      {showSummary && answer && (
        <>
          <div className="card" style={{ margin: '0 20px' }}>
            <div style={{ fontWeight: 700, fontSize: 21, letterSpacing: '-.02em', lineHeight: 1.2 }}>{answer.heading}</div>
            <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '4px 0 0', lineHeight: 1.4 }}>{answer.sub}</div>

            {answer.logged && (
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'var(--chip)', color: 'var(--ac2)', fontSize: 12, fontWeight: 600, padding: '5px 11px', borderRadius: 9, marginTop: 10 }}>
                ✓ Recorded in the audit log
              </div>
            )}

            {answer.stats.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <Stats items={answer.stats} />
              </div>
            )}

            {answer.rows && (
              <>
                <div style={{ fontWeight: 700, fontSize: 14.5, margin: '20px 0 4px' }}>{answer.rowsTitle}</div>
                {answer.rows.map((r) => (
                  <div key={r.name} className="row">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="row__name">{r.name}</div>
                      <div className="row__sub">{r.sub}</div>
                    </div>
                    <Badge tone={r.tone}>{r.badge}</Badge>
                  </div>
                ))}
              </>
            )}

            {answer.hasMap && answer.map && answer.areas && (
              <CountMap map={answer.map} areas={answer.areas} />
            )}

            {answer.bars && (
              <>
                <div style={{ fontWeight: 700, fontSize: 14.5, margin: '20px 0 10px' }}>{answer.barsTitle}</div>
                <div className="stack" style={{ gap: 9 }}>
                  {answer.bars.map((b) => (
                    <div key={b.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ width: 42, fontSize: 12.5, color: 'var(--tx2)', flexShrink: 0 }}>{b.label}</span>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${b.pct}%` }} />
                      </div>
                      <span style={{ width: 38, textAlign: 'right', fontSize: 12.5, fontWeight: 600, flexShrink: 0 }}>{b.value}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {answer.path && (
              <>
                <div style={{ fontWeight: 700, fontSize: 14.5, margin: '20px 0 12px' }}>Path through the day</div>
                <div style={{ position: 'relative', paddingLeft: 24 }}>
                  <div style={{ position: 'absolute', left: 6, top: 6, bottom: 6, width: 2, background: 'var(--line)' }} />
                  {answer.path.map((p) => (
                    <div key={p.time} style={{ position: 'relative', paddingBottom: 18 }}>
                      <span style={{ position: 'absolute', left: -23, top: 4, width: 11, height: 11, borderRadius: '50%', background: 'var(--ac)', border: '2.5px solid var(--card)' }} />
                      <div style={{ fontWeight: 600, fontSize: 14 }}>
                        {p.time} — {p.place}
                      </div>
                      <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 1, lineHeight: 1.35 }}>{p.detail}</div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {answer.cards && (
              <div className="stack" style={{ marginTop: 16 }}>
                {answer.cards.map((c) => (
                  <AnswerCard key={c.id} card={c} />
                ))}
              </div>
            )}

            {answer.foot && (
              <div style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--line)', fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4 }}>
                {answer.foot}
              </div>
            )}
          </div>

          <div className="screen" style={{ marginTop: 0 }}>
            <CamGrid title={def.camTitle} note={def.camNote} cameras={answer.cameras} />
          </div>
        </>
      )}

      {isIntrude && (
        <div className="card" style={{ margin: '14px 20px 0' }}>
          <div style={{ fontWeight: 700, fontSize: 14.5 }}>Protected areas</div>
          <div style={{ fontSize: 12.5, color: 'var(--tx2)', margin: '2px 0 4px', lineHeight: 1.4 }}>
            Pauses stay visible to everyone.
          </div>
          {zones.map((z, i) => (
            <div key={z.id} className="row">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row__name">{z.name}</div>
                <div className="row__sub">{z.hours}</div>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={z.enabled}
                className="toggle"
                style={{ background: z.enabled ? 'var(--ac)' : 'var(--toggle-off)' }}
                onClick={() => toggleZone(i)}
              >
                <span className="toggle__knob" style={{ left: z.enabled ? 20 : 2 }} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const TONE_COLOR: Record<Tone, string> = { good: 'var(--ac)', warn: 'var(--am)', bad: 'var(--rd)', neutral: 'var(--tx2)' };
const TONE_FILL: Record<Tone, string> = { good: 'var(--chip)', warn: 'var(--am-bg)', bad: 'var(--rd-bg)', neutral: 'var(--bg)' };
const TONE_TEXT: Record<Tone, string> = { good: 'var(--ac2)', warn: 'var(--am)', bad: 'var(--rd)', neutral: 'var(--tx2)' };

function CountMap({ map, areas }: { map: MapZone[]; areas: MapArea[] }) {
  const toneColor = TONE_COLOR;
  const toneFill = TONE_FILL;
  const toneText = TONE_TEXT;

  return (
    <>
      <div style={{ fontWeight: 700, fontSize: 14.5, margin: '20px 0 10px' }}>Where those people are right now</div>
      <div style={{ background: 'var(--bg)', borderRadius: 13, padding: 12 }}>
        <div style={{ position: 'relative', width: '100%', paddingTop: '72%' }}>
          <div style={{ position: 'absolute', inset: 0 }}>
            {map.map((z) => (
              <div
                key={z.label}
                style={{
                  position: 'absolute',
                  left: `${z.x}%`,
                  top: `${z.y}%`,
                  width: `${z.w}%`,
                  height: `${z.h}%`,
                  borderRadius: 8,
                  border: `1.5px solid ${toneColor[z.tone]}`,
                  background: toneFill[z.tone],
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 1,
                  padding: 3,
                  boxSizing: 'border-box',
                }}
              >
                <span style={{ fontSize: 14, fontWeight: 700, color: toneText[z.tone], lineHeight: 1 }}>{z.value}</span>
                <span style={{ fontSize: 8.5, fontWeight: 600, color: toneText[z.tone], textAlign: 'center', lineHeight: 1.15 }}>{z.label}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginTop: 10, fontSize: 11, color: 'var(--tx2)' }}>
        <Legend tone="good" label="Quiet" />
        <Legend tone="warn" label="Busy" />
        <Legend tone="bad" label="Over capacity" />
      </div>
      <div style={{ marginTop: 12 }}>
        {areas.map((a) => (
          <div key={a.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 0', borderBottom: '1px solid var(--line)' }}>
            <span style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 600 }}>{a.name}</span>
            <div className="bar-track" style={{ maxWidth: 70, height: 8 }}>
              <div className="bar-fill" style={{ width: `${a.pct}%`, background: toneColor[a.tone] }} />
            </div>
            <span style={{ width: 34, textAlign: 'right', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{a.value}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--tx3)', marginTop: 10, lineHeight: 1.4 }}>
        Overlapping cameras are de-duplicated — a person between two cameras is counted once.
      </div>
    </>
  );
}

function Legend({ tone, label }: { tone: Tone; label: string }) {
  const color = TONE_COLOR[tone];
  const bg = TONE_FILL[tone];
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 11, height: 11, borderRadius: 3, border: `1.5px solid ${color}`, background: bg }} />
      {label}
    </span>
  );
}

/** One result card. Named for fights once; it renders any tool's answer. */
function AnswerCard({ card }: { card: { title: string; meta: string; badge: string; tone: 'good' | 'warn' | 'bad' | 'neutral'; criticalUnacked: boolean; acked: boolean } }) {
  const toneColors = { good: { bg: 'var(--chip)', fg: 'var(--ac2)' }, warn: { bg: 'var(--am-bg)', fg: 'var(--am)' }, bad: { bg: 'var(--rd-bg)', fg: 'var(--rd)' }, neutral: { bg: 'var(--bg)', fg: 'var(--tx2)' } };
  const c = toneColors[card.tone];

  return (
    <div style={{ background: 'var(--bg)', borderRadius: 13, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>{card.title}</div>
        <span className="badge" style={{ background: c.bg, color: c.fg }}>
          {card.badge}
        </span>
      </div>
      <div style={{ fontSize: 12.5, color: 'var(--tx2)', marginTop: 4, lineHeight: 1.4 }}>{card.meta}</div>
      <div style={{ display: 'flex', gap: 14, alignItems: 'center', marginTop: 11 }}>
        <span style={{ color: 'var(--ac)', fontWeight: 600, fontSize: 13 }}>Watch clip</span>
      </div>
    </div>
  );
}

function WeaponWorkflow({ state, setState }: { state: WeaponState; setState: (s: WeaponState) => void }) {
  if (state === 'clear') {
    return (
      <div className="card" style={{ margin: '0 20px 12px', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--chip)', color: 'var(--ac)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 17, flexShrink: 0 }}>
          ✓
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14.5 }}>Nothing detected right now</div>
          <button type="button" className="linkbtn" style={{ fontSize: 12.5, marginTop: 2 }} onClick={() => setState('live')}>
            Show a live detection →
          </button>
        </div>
      </div>
    );
  }

  if (state === 'live') {
    return (
      <div className="card" style={{ margin: '0 20px 12px', border: '2px solid var(--rd)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <span style={{ width: 24, height: 24, borderRadius: '50%', background: 'var(--rd)', color: 'var(--card)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, flexShrink: 0 }}>
            !
          </span>
          <div style={{ fontWeight: 700, fontSize: 17, letterSpacing: '-.01em', color: 'var(--rd)', lineHeight: 1.25 }}>Possible knife — Main gate</div>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, marginBottom: 14 }}>
          14 seconds ago · knife-shaped object, 78% confidence · nobody has been alerted yet.
        </div>
        <CamGrid title="" cameras={[WEAPON_LIVE_CAMERA]} />
        <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.45, margin: '14px 0 12px' }}>
          The system will not call anyone or notify a parent on its own. Watch the clip and say what you see.
        </div>
        <div className="stack" style={{ gap: 9 }}>
          <button type="button" className="btn btn--danger" onClick={() => setState('confirmed')}>
            This is a knife — alert the team
          </button>
          <button type="button" className="btn btn--ghost" onClick={() => setState('dismissed')}>
            Not a knife — false alarm
          </button>
          <button type="button" className="btn btn--quiet" onClick={() => setState('dismissed')}>
            Not sure yet — keep watching
          </button>
        </div>
      </div>
    );
  }

  if (state === 'confirmed') {
    return (
      <div className="card" style={{ margin: '0 20px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ width: 22, height: 22, borderRadius: '50%', background: 'var(--rd)', color: 'var(--card)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 800, flexShrink: 0 }}>
            !
          </span>
          <div style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-.01em', lineHeight: 1.25 }}>Confirmed by you at 8:47am</div>
        </div>
        <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, margin: '4px 0 12px' }}>
          Mohamed Fouad confirmed this detection. Everything below is recorded against the incident.
        </div>
        {WEAPON_STEPS.map((step) => (
          <div key={step.title} className="row">
            <span
              style={{
                width: 20,
                height: 20,
                borderRadius: '50%',
                background: step.tone === 'bad' ? 'var(--rd)' : step.tone === 'warn' ? 'var(--am)' : 'var(--bg)',
                color: step.tone === 'neutral' ? 'var(--tx2)' : 'var(--card)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 11,
                fontWeight: 800,
                flexShrink: 0,
              }}
            >
              {step.icon}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 13.5 }}>{step.title}</div>
              <div className="row__sub">{step.sub}</div>
            </div>
          </div>
        ))}
        <button type="button" className="btn btn--ghost" style={{ marginTop: 14 }} onClick={() => setState('clear')}>
          Close incident
        </button>
      </div>
    );
  }

  return (
    <div className="card" style={{ margin: '0 20px 12px', display: 'flex', alignItems: 'center', gap: 12 }}>
      <div style={{ width: 38, height: 38, borderRadius: '50%', background: 'var(--chip)', color: 'var(--ac)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, flexShrink: 0 }}>
        ✓
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, fontSize: 14 }}>False alarm — nobody was alerted</div>
        <div className="row__sub">Recorded against your name, and added to the list below.</div>
      </div>
      <button type="button" className="linkbtn" onClick={() => setState('clear')}>
        Done
      </button>
    </div>
  );
}
