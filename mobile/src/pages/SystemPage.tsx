import { useEffect, useState } from 'react';
import { CamGrid } from '@/components/CamGrid';
import { getAreaOptions, getCameraSources, getSystemSummary, scanNetwork, connectDvr, testConnection } from '@/services/api';
import type { Camera, CameraSource, DvrChannel, FoundDevice, SourceMode, SystemSummary } from '@/types';

const MODE_LABEL: Record<SourceMode, string> = {
  scan: 'Scan network',
  dvr: 'Add DVR / NVR',
  ip: 'Add IP camera',
  rtsp: 'Paste RTSP URL',
};

function badgeFor(status: CameraSource['status']) {
  if (status === 'ok') return { bg: 'var(--chip)', fg: 'var(--ac2)', label: '✓ Connected' };
  if (status === 'down') return { bg: 'var(--rd-bg)', fg: 'var(--rd)', label: '✕ Offline' };
  return { bg: 'var(--am-bg)', fg: 'var(--am)', label: '! Password' };
}

export function SystemPage() {
  const [summary, setSummary] = useState<SystemSummary | null>(null);
  const [sources, setSources] = useState<CameraSource[]>(getCameraSources());
  const [formOpen, setFormOpen] = useState(false);
  const [mode, setMode] = useState<SourceMode>('scan');

  const [scanState, setScanState] = useState<'idle' | 'run' | 'done'>('idle');
  const [found, setFound] = useState<FoundDevice[]>([]);

  const [dvrStep, setDvrStep] = useState<'form' | 'connecting' | 'channels'>('form');
  const [dvrChannels, setDvrChannels] = useState<DvrChannel[]>(
    Array.from({ length: 8 }, (_, i) => ({ channel: `CH ${i + 1}`, name: `Camera ${i + 1}`, enabled: true })),
  );

  const [test, setTest] = useState<'idle' | 'run' | 'ok'>('idle');
  const [testCam, setTestCam] = useState<Camera | null>(null);

  const areaOpts = getAreaOptions();

  useEffect(() => {
    void getSystemSummary().then(setSummary);
  }, [sources]);

  function openForm() {
    setFormOpen(true);
    setMode('scan');
    setScanState('idle');
    setFound([]);
    setDvrStep('form');
    setTest('idle');
    setTestCam(null);
  }

  function switchMode(m: SourceMode) {
    setMode(m);
    setScanState('idle');
    setFound([]);
    setDvrStep('form');
    setTest('idle');
    setTestCam(null);
  }

  function startScan() {
    setScanState('run');
    void scanNetwork().then((devices) => {
      setFound(devices);
      setScanState('done');
    });
  }

  function addFound(i: number) {
    const device = found[i];
    if (device.added || device.duplicate) return;
    setFound((c) => c.map((f, j) => (j === i ? { ...f, added: true } : f)));
    setSources((c) => [...c, { id: `found-${device.ip}`, name: device.name, type: device.channels > 1 ? 'NVR' : 'IP camera', ip: device.ip, channels: device.channels, status: 'ok' }]);
  }

  function startDvrConnect() {
    setDvrStep('connecting');
    void connectDvr().then(() => setDvrStep('channels'));
  }

  function toggleDvrChannel(i: number) {
    setDvrChannels((c) => c.map((ch, j) => (j === i ? { ...ch, enabled: !ch.enabled } : ch)));
  }

  function addDvr() {
    const count = dvrChannels.filter((c) => c.enabled).length;
    setSources((c) => [...c, { id: `dvr-${c.length}`, name: `DVR — 192.168.1.${50 + c.length}`, type: 'DVR', ip: `192.168.1.${50 + c.length}`, channels: count, status: 'ok' }]);
    setFormOpen(false);
  }

  function runTest() {
    setTest('run');
    void testConnection().then((cam) => {
      setTestCam(cam);
      setTest('ok');
    });
  }

  function addSingle() {
    setSources((c) => [...c, { id: `single-${c.length}`, name: mode === 'rtsp' ? 'RTSP stream — manual' : 'IP camera — 192.168.1.140', type: mode === 'rtsp' ? 'RTSP' : 'IP camera', ip: mode === 'rtsp' ? 'rtsp://…' : '192.168.1.140', channels: 1, status: 'ok' }]);
    setFormOpen(false);
  }

  if (!summary) return null;

  return (
    <div className="screen">
      <div className="screen__title">System</div>
      <p className="screen__lead">Cameras, recorders and the AI server.</p>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>
          {summary.camerasOnline === summary.camerasTotal ? `All ${summary.camerasTotal} cameras online` : `${summary.camerasOnline} of ${summary.camerasTotal} cameras online`}
        </div>
        <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '3px 0 14px', lineHeight: 1.4 }}>{summary.summary}</div>
        <div className="stats2">
          <div className="stat">
            <div className="stat__label">GPU</div>
            <div className="stat__value">{summary.gpu}</div>
          </div>
          <div className="stat">
            <div className="stat__label">Storage</div>
            <div className="stat__value">{summary.storage}</div>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ fontWeight: 700, fontSize: 15.5 }}>Camera sources</div>
        <div style={{ fontSize: 12.5, color: 'var(--tx2)', margin: '2px 0 4px' }}>Any DVR, NVR or IP camera that speaks ONVIF or RTSP.</div>

        {sources.map((s) => {
          const b = badgeFor(s.status);
          return (
            <div key={s.id} className="row">
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="row__name">{s.name}</div>
                <div className="row__sub">
                  {s.ip} · {s.channels} {s.channels === 1 ? 'channel' : 'channels'}
                </div>
              </div>
              <span className="badge" style={{ background: b.bg, color: b.fg }}>
                {b.label}
              </span>
            </div>
          );
        })}

        {!formOpen ? (
          <div style={{ padding: '14px 0 4px', textAlign: 'center' }}>
            <button type="button" className="linkbtn" onClick={openForm}>
              + Add a camera or recorder
            </button>
          </div>
        ) : (
          <div style={{ paddingTop: 14 }}>
            <div className="chip-row" style={{ marginBottom: 8 }}>
              {(Object.keys(MODE_LABEL) as SourceMode[]).map((m) => (
                <button key={m} type="button" className={`chip-btn ${mode === m ? 'chip-btn--brand' : 'chip-btn--off'}`} onClick={() => switchMode(m)}>
                  {MODE_LABEL[m]}
                </button>
              ))}
            </div>

            {mode === 'scan' && (
              <>
                {scanState === 'idle' && (
                  <>
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, margin: '8px 0 12px' }}>Looks for ONVIF cameras and recorders on the school network.</div>
                    <button type="button" className="btn" onClick={startScan}>
                      Start scan
                    </button>
                  </>
                )}
                {scanState === 'run' && (
                  <>
                    <div style={{ fontWeight: 600, fontSize: 14, marginTop: 8 }}>Scanning 192.168.1.0/24…</div>
                    <div className="progress" style={{ marginTop: 9 }}>
                      <div className="progress__scanner" />
                    </div>
                  </>
                )}
                {scanState === 'done' && (
                  <>
                    <div style={{ fontWeight: 600, fontSize: 14, margin: '8px 0 2px' }}>{found.length} devices found</div>
                    {found.map((f, i) => (
                      <div key={f.ip} className="row">
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: 13.5 }}>{f.name}</div>
                          <div style={{ fontSize: 11.5, color: 'var(--tx3)' }}>
                            {f.ip} · {f.channels} {f.channels === 1 ? 'channel' : 'channels'}
                          </div>
                        </div>
                        {!f.duplicate && !f.added ? (
                          <button type="button" className="chip-btn chip-btn--on" onClick={() => addFound(i)}>
                            Add
                          </button>
                        ) : (
                          <span style={{ fontSize: 12, color: 'var(--tx3)' }}>{f.duplicate ? 'Already added' : '✓ Added'}</span>
                        )}
                      </div>
                    ))}
                  </>
                )}
              </>
            )}

            {mode === 'dvr' && (
              <>
                {dvrStep === 'form' && (
                  <>
                    <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, margin: '8px 0 12px' }}>Connect a recorder and every camera plugged into it comes along.</div>
                    <div className="stack">
                      <div style={{ display: 'flex', gap: 10 }}>
                        <input className="input" placeholder="IP address" defaultValue="192.168.1.50" style={{ fontFamily: 'ui-monospace, Menlo, monospace' }} />
                        <input className="input" placeholder="Port" defaultValue="554" style={{ width: 80, fontFamily: 'ui-monospace, Menlo, monospace' }} />
                      </div>
                      <div style={{ display: 'flex', gap: 10 }}>
                        <input className="input" placeholder="Username" defaultValue="admin" />
                        <input className="input" type="password" placeholder="Password" defaultValue="password" />
                      </div>
                      <button type="button" className="btn" onClick={startDvrConnect}>
                        Connect &amp; pull channels
                      </button>
                    </div>
                  </>
                )}
                {dvrStep === 'connecting' && (
                  <>
                    <div style={{ fontWeight: 600, fontSize: 14, marginTop: 8 }}>Connecting to recorder…</div>
                    <div className="progress" style={{ marginTop: 9 }}>
                      <div className="progress__scanner" />
                    </div>
                  </>
                )}
                {dvrStep === 'channels' && (
                  <>
                    <div style={{ fontWeight: 600, fontSize: 14, margin: '8px 0 2px' }}>Connected · 8 channels found</div>
                    <div style={{ fontSize: 12, color: 'var(--tx3)', lineHeight: 1.4, marginBottom: 4 }}>Name each camera and say where it is.</div>
                    {dvrChannels.map((ch, i) => (
                      <div key={ch.channel} style={{ padding: '11px 0', borderBottom: '1px solid var(--line)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--tx3)', fontFamily: 'ui-monospace, Menlo, monospace', width: 38, flexShrink: 0 }}>{ch.channel}</span>
                          <input className="input" defaultValue={ch.name} style={{ height: 42 }} />
                          <button
                            type="button"
                            role="switch"
                            aria-checked={ch.enabled}
                            className="toggle"
                            style={{ background: ch.enabled ? 'var(--ac)' : 'var(--toggle-off)' }}
                            onClick={() => toggleDvrChannel(i)}
                          >
                            <span className="toggle__knob" style={{ left: ch.enabled ? 20 : 2 }} />
                          </button>
                        </div>
                        <select className="input" style={{ height: 42, marginTop: 8 }}>
                          {areaOpts.map((a) => (
                            <option key={a}>{a}</option>
                          ))}
                        </select>
                      </div>
                    ))}
                    <button type="button" className="btn" style={{ marginTop: 14 }} onClick={addDvr}>
                      Add {dvrChannels.filter((c) => c.enabled).length} cameras
                    </button>
                  </>
                )}
              </>
            )}

            {(mode === 'ip' || mode === 'rtsp') && (
              <>
                {test === 'idle' && (
                  <>
                    {mode === 'rtsp' && (
                      <div style={{ fontSize: 12.5, color: 'var(--tx2)', lineHeight: 1.4, margin: '8px 0 12px' }}>
                        The escape hatch — works with anything that produces a video stream, whatever the brand.
                      </div>
                    )}
                    <div className="stack">
                      {mode === 'ip' ? (
                        <input className="input" placeholder="IP address" defaultValue="192.168.1.140" style={{ fontFamily: 'ui-monospace, Menlo, monospace' }} />
                      ) : (
                        <input className="input" placeholder="RTSP URL" defaultValue="rtsp://user:pass@192.168.1.150:554/stream1" style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 13 }} />
                      )}
                      {mode === 'ip' && (
                        <div style={{ display: 'flex', gap: 10 }}>
                          <input className="input" placeholder="Username" defaultValue="admin" />
                          <input className="input" type="password" placeholder="Password" defaultValue="password" />
                        </div>
                      )}
                      <button type="button" className="btn" onClick={runTest}>
                        {mode === 'ip' ? 'Test connection' : 'Test stream'}
                      </button>
                    </div>
                  </>
                )}
                {test === 'run' && (
                  <>
                    <div style={{ fontWeight: 600, fontSize: 14, marginTop: 8 }}>{mode === 'ip' ? 'Fetching a test frame…' : 'Opening the stream…'}</div>
                    <div className="progress" style={{ marginTop: 9 }}>
                      <div className="progress__scanner" />
                    </div>
                  </>
                )}
                {test === 'ok' && testCam && (
                  <div style={{ marginTop: 4 }}>
                    <CamGrid title="" cameras={[testCam]} />
                    <div className="stack" style={{ marginTop: 12 }}>
                      <input className="input" placeholder="Camera name" defaultValue="New camera" />
                      <select className="input">
                        {areaOpts.map((a) => (
                          <option key={a}>{a}</option>
                        ))}
                      </select>
                      <button type="button" className="btn" onClick={addSingle}>
                        Add camera
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="card card--dashed">
        <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--tx2)' }}>Live video streaming — not connected yet</div>
        <div style={{ fontSize: 12.5, color: 'var(--tx3)', marginTop: 3, lineHeight: 1.4 }}>This prototype shows detection frames, not real streams.</div>
      </div>
    </div>
  );
}
