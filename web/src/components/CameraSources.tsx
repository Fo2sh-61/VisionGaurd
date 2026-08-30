import { useEffect, useState, type ChangeEvent, type ReactNode } from 'react';
import { useCameras } from '@/app/CameraContext';
import { addCamera, connectDvr, getAreaOptions, getCameraSources, removeCamera, scanNetwork, testConnection } from '@/services/api';
import type { Camera, CameraSource, DvrChannel, FoundDevice, SourceMode } from '@/types';
import { CamGrid } from './CamGrid';
import { useLanguage, useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';
import { Badge } from './ui';

const MODE_LABEL: Record<SourceMode, MessageKey> = {
  scan: 'source.mode.scan',
  dvr: 'source.mode.dvr',
  ip: 'source.mode.ip',
  rtsp: 'source.mode.rtsp',
};

function badgeFor(status: CameraSource['status']) {
  if (status === 'ok') return { tone: 'good' as const, label: 'source.status.connected' as MessageKey };
  if (status === 'down') return { tone: 'bad' as const, label: 'source.status.offline' as MessageKey };
  return { tone: 'warn' as const, label: 'source.status.wrongPassword' as MessageKey };
}

/** The connection form.
 *
 *  These used to be uncontrolled inputs with `defaultValue`, because
 *  `connectDvr()` and `testConnection()` took no arguments and nothing the
 *  operator typed ever left the component. The engine needs them, so they are
 *  controlled now. */
interface ConnectForm {
  name: string;
  host: string;
  port: string;
  username: string;
  password: string;
  rtspUrl: string;
  area: string;
  /** What this camera is watched for. Each one loads models, so the choice
   *  has a real cost — an empty list means it streams but nothing analyses it. */
  features: string[];
}

const EMPTY_FORM: ConnectForm = {
  name: '',
  host: '192.168.1.50',
  port: '554',
  username: 'admin',
  password: '',
  rtspUrl: 'rtsp://192.168.1.150:554/stream1',
  area: '',
  features: ['counting'],
};

/** What a camera can be watched for, and what each costs to run. */
const FEATURES: { key: string; label: MessageKey; cost: MessageKey }[] = [
  { key: 'counting', label: 'source.feature.counting', cost: 'source.feature.counting.cost' },
  { key: 'intrusion', label: 'source.feature.intrusion', cost: 'source.feature.intrusion.cost' },
  { key: 'attendance', label: 'source.feature.attendance', cost: 'source.feature.attendance.cost' },
];

export function CameraSources() {
  const t = useT();
  const { language } = useLanguage();
  const [sources, setSources] = useState<CameraSource[]>([]);
  const [mode, setMode] = useState<SourceMode | null>(null);
  const [areaOpts, setAreaOpts] = useState<string[]>([]);
  const [form, setForm] = useState<ConnectForm>(EMPTY_FORM);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { refresh: refreshRoster } = useCameras();

  const field = (key: keyof ConnectForm) => ({
    value: form[key],
    onChange: (e: ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [key]: e.target.value })),
  });

  const [scanState, setScanState] = useState<'idle' | 'run' | 'done'>('idle');
  const [found, setFound] = useState<FoundDevice[]>([]);

  const [dvrStep, setDvrStep] = useState<'form' | 'connecting' | 'channels'>('form');
  const [dvrChannels, setDvrChannels] = useState<DvrChannel[]>(
    Array.from({ length: 8 }, (_, i) => ({ channel: `CH ${i + 1}`, name: `Camera ${i + 1}`, enabled: true })),
  );

  const [test, setTest] = useState<'idle' | 'run' | 'ok'>('idle');
  const [testCam, setTestCam] = useState<Camera | null>(null);

  useEffect(() => {
    void getCameraSources().then(setSources);
    void getAreaOptions().then(setAreaOpts);
  }, []);

  function openMode(m: SourceMode) {
    setMode((current) => (current === m ? null : m));
    setScanState('idle');
    setFound([]);
    setDvrStep('form');
    setTest('idle');
    setTestCam(null);
    setConnectError(null);
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
    setFound((current) => current.map((f, j) => (j === i ? { ...f, added: true } : f)));
    setSources((current) => [
      ...current,
      {
        id: `found-${device.ip}`,
        name: device.name,
        type: device.channels > 1 ? 'NVR' : 'IP camera',
        ip: device.ip,
        channels: device.channels,
        status: 'ok',
      },
    ]);
  }

  function startDvrConnect() {
    setDvrStep('connecting');
    setConnectError(null);
    void connectDvr({
      host: form.host,
      port: Number(form.port) || 554,
      username: form.username,
      password: form.password,
    })
      .then((result) => {
        // Show the channels the recorder actually reported, not a fixed eight.
        setDvrChannels(
          Array.from({ length: result.channels }, (_, i) => ({
            channel: `CH ${i + 1}`,
            name: `Camera ${i + 1}`,
            enabled: true,
          })),
        );
        setDvrStep('channels');
      })
      .catch((error: Error) => {
        setConnectError(error.message);
        setDvrStep('form');
      });
  }

  function toggleDvrChannel(i: number) {
    setDvrChannels((current) => current.map((c, j) => (j === i ? { ...c, enabled: !c.enabled } : c)));
  }

  function addDvr() {
    const count = dvrChannels.filter((c) => c.enabled).length;
    setSources((current) => [
      ...current,
      {
        id: `dvr-${current.length}`,
        name: `DVR — 192.168.1.${50 + current.length}`,
        type: 'DVR',
        ip: `192.168.1.${50 + current.length}`,
        channels: count,
        status: 'ok',
      },
    ]);
    setMode(null);
  }

  function runTest() {
    setTest('run');
    setConnectError(null);
    // A failed test comes back as a camera with `offline: true` and a reason,
    // so it renders inline instead of throwing.
    void testConnection(
      mode === 'rtsp'
        ? { source: form.rtspUrl }
        : { source: form.host, username: form.username, password: form.password },
      language,
    )
      .then((cam) => {
        setTestCam(cam);
        setTest('ok');
      })
      .catch((error: Error) => {
        setConnectError(error.message);
        setTest('idle');
      });
  }

  function addSingle() {
    setBusy(true);
    setConnectError(null);

    // The engine speaks one source vocabulary — the same strings engine.yaml
    // uses — so what is typed here is exactly what a config file would hold.
    const source =
      mode === 'rtsp' ? form.rtspUrl : `rtsp://${form.host}:${form.port || 554}/stream1`;

    void addCamera({
      name: form.name || (mode === 'rtsp' ? 'RTSP stream' : `Camera ${form.host}`),
      source,
      kind: mode === 'rtsp' ? 'RTSP' : 'IP camera',
      // Empty, not the word "Unassigned": absence is absence, and CamGrid
      // supplies the heading. Storing the English word would put cameras in
      // two different groups meaning the same thing.
      area: form.area,
      features: form.features,
      username: mode === 'ip' ? form.username : undefined,
      password: mode === 'ip' ? form.password : undefined,
    })
      .then((added) => {
        setSources((current) => [...current.filter((s) => s.id !== added.id), added]);
        // Tell the roster so the new camera appears on every other page
        // immediately, rather than after the next 5s poll.
        refreshRoster();
        setMode(null);
        setTest('idle');
        setTestCam(null);
        setForm(EMPTY_FORM);
      })
      .catch((error: Error) => setConnectError(error.message))
      .finally(() => setBusy(false));
  }

  function removeSource(id: string) {
    // Optimistic: the row goes immediately, and comes back if the engine
    // refuses. Waiting on a round trip to remove a row feels broken.
    const previous = sources;
    setSources((current) => current.filter((s) => s.id !== id));

    void removeCamera(id)
      .then(refreshRoster)
      .catch((error: Error) => {
        setSources(previous);
        setConnectError(`Could not remove: ${error.message}`);
      });
  }

  const total = sources.reduce((sum, s) => sum + s.channels, 0);

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 19, letterSpacing: '-.01em' }}>{t('source.title')}</div>
          <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginTop: 2 }}>
            {t('source.subtitle', { cameras: total, sources: sources.length })}
          </div>
        </div>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          background: 'var(--bg)',
          borderRadius: 11,
          padding: '12px 14px',
          margin: '14px 0',
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 15,
            height: 15,
            borderRadius: '50%',
            background: 'var(--ac)',
            color: 'var(--bg)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 10,
            fontWeight: 800,
            flexShrink: 0,
          }}
        >
          ✓
        </span>
        <span style={{ fontSize: 13, color: 'var(--tx2)' }}>
          <b style={{ color: 'var(--tx)' }}>{t('source.captureService')}</b> · 192.168.1.10
          · {t('source.captureServiceLead')}
        </span>
      </div>

      {sources.map((src) => {
        const badge = badgeFor(src.status);
        return (
          <div
            key={src.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 12,
              padding: '12px 0',
              borderBottom: '1px solid var(--line)',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{src.name}</div>
              <div style={{ fontSize: 12.5, color: 'var(--tx3)' }}>
                {src.type} · {src.ip} · {src.channels === 1
                  ? t('source.channelCountOne')
                  : t('source.channelCount', { count: src.channels })}
              </div>
            </div>
            <Badge tone={badge.tone}>{t(badge.label)}</Badge>
            {src.status !== 'ok' && (
              // Reconnection is the engine's job — it retries with backoff on
              // its own. A "Retry" button that only flipped a local flag to
              // green was worse than no button: it made a broken camera look
              // fixed. Show the reason instead.
              <span style={{ fontSize: 12.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
                {t(src.status === 'down' ? 'source.status.retrying' : 'source.status.checkPassword')}
              </span>
            )}
            <button type="button" className="linkbtn linkbtn--quiet" onClick={() => removeSource(src.id)}>
              {t('source.remove')}
            </button>
          </div>
        );
      })}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
        {(Object.keys(MODE_LABEL) as SourceMode[]).map((m) => (
          <button
            key={m}
            type="button"
            className={`chip-btn ${mode === m ? 'chip-btn--brand' : 'chip-btn--off'}`}
            style={{ height: 38, padding: '0 16px' }}
            onClick={() => openMode(m)}
          >
            {t(MODE_LABEL[m])}
          </button>
        ))}
      </div>

      {mode === 'scan' && (
        <div style={{ background: 'var(--bg)', borderRadius: 12, padding: '16px 18px', marginTop: 14 }}>
          {scanState === 'idle' && (
            <>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginBottom: 12 }}>
                {t('source.scanLead')}
              </div>
              <button type="button" className="btn" onClick={startScan}>
                {t('source.startScan')}
              </button>
            </>
          )}
          {scanState === 'run' && (
            <>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{t('source.scanning', { range: '192.168.1.0/24' })}</div>
              <div className="progress" style={{ marginTop: 10 }}>
                <div className="progress__scanner" />
              </div>
            </>
          )}
          {scanState === 'done' && (
            <>
              <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>{t('source.devicesFound', { count: found.length })}</div>
              {found.map((f, i) => (
                <div
                  key={f.ip}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '10px 0', borderBottom: '1px solid var(--line)' }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13.5 }}>{f.name}</div>
                    <div style={{ fontSize: 12, color: 'var(--tx3)' }}>
                      {f.ip} · {f.channels === 1
                        ? t('source.channelCountOne')
                        : t('source.channelCount', { count: f.channels })}
                    </div>
                  </div>
                  {!f.duplicate && !f.added ? (
                    <button type="button" className="btn btn--ghost" style={{ height: 32, padding: '0 14px', fontSize: 12.5 }} onClick={() => addFound(i)}>
                      {t('source.add')}
                    </button>
                  ) : (
                    <span style={{ fontSize: 12.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
                      {t(f.duplicate ? 'source.alreadyAdded' : 'source.added')}
                    </span>
                  )}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {mode === 'dvr' && (
        <div style={{ background: 'var(--bg)', borderRadius: 12, padding: '16px 18px', marginTop: 14 }}>
          {dvrStep === 'form' && (
            <>
              <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginBottom: 12 }}>
                {t('source.dvrLead')}
              </div>
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                <Labeled label={t('source.field.ip')}>
                  <input className="input" style={{ width: 150, fontFamily: 'ui-monospace, Menlo, monospace' }} {...field('host')} />
                </Labeled>
                <Labeled label={t('source.field.port')}>
                  <input className="input" style={{ width: 70, fontFamily: 'ui-monospace, Menlo, monospace' }} {...field('port')} />
                </Labeled>
                <Labeled label={t('source.field.username')}>
                  <input className="input" style={{ width: 120 }} {...field('username')} />
                </Labeled>
                <Labeled label={t('source.field.password')}>
                  <input className="input" type="password" style={{ width: 120 }} {...field('password')} />
                </Labeled>
                <button type="button" className="btn" style={{ whiteSpace: 'nowrap' }} onClick={startDvrConnect}>
                  {t('source.connectAndPull')}
                </button>
              </div>
              {connectError && <ConnectError message={connectError} />}
            </>
          )}
          {dvrStep === 'connecting' && (
            <>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{t('source.connecting')}</div>
              <div className="progress" style={{ marginTop: 10 }}>
                <div className="progress__scanner" />
              </div>
            </>
          )}
          {dvrStep === 'channels' && (
            <>
              <div style={{ fontWeight: 600, fontSize: 14 }}>{t('source.recorderConnected', { channels: dvrChannels.length })}</div>
              <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 8px' }}>
                {t('source.nameEachCamera')}
              </div>
              {dvrChannels.map((ch, i) => (
                <div key={ch.channel} style={{ display: 'grid', gridTemplateColumns: '52px 1fr 1fr 44px', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--tx3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>{ch.channel}</span>
                  <input className="input" style={{ height: 36, fontSize: 13 }} defaultValue={ch.name} />
                  <select className="input" style={{ height: 36, fontSize: 13, minWidth: 0 }}>
                    {areaOpts.map((a) => (
                      <option key={a}>{a}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="toggle"
                    role="switch"
                    aria-checked={ch.enabled}
                    style={{ background: ch.enabled ? 'var(--ac)' : 'var(--toggle-off)' }}
                    onClick={() => toggleDvrChannel(i)}
                  >
                    <span className="toggle__knob" style={{ left: ch.enabled ? 18 : 2 }} />
                  </button>
                </div>
              ))}
              <button type="button" className="btn" style={{ marginTop: 14 }} onClick={addDvr}>
                {t('source.addNCameras', { count: dvrChannels.filter((c) => c.enabled).length })}
              </button>
            </>
          )}
        </div>
      )}

      {(mode === 'ip' || mode === 'rtsp') && (
        <div style={{ background: 'var(--bg)', borderRadius: 12, padding: '16px 18px', marginTop: 14 }}>
          {test === 'idle' && (
            <>
              {mode === 'rtsp' && (
                <div style={{ fontSize: 13.5, color: 'var(--tx2)', marginBottom: 12 }}>
                  {t('source.rtspLead')}
                </div>
              )}
              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                {mode === 'ip' ? (
                  <>
                    <Labeled label={t('source.field.ip')}>
                      <input className="input" style={{ width: 150, fontFamily: 'ui-monospace, Menlo, monospace' }} {...field('host')} />
                    </Labeled>
                    <Labeled label={t('source.field.username')}>
                      <input className="input" style={{ width: 120 }} {...field('username')} />
                    </Labeled>
                    <Labeled label={t('source.field.password')}>
                      <input className="input" type="password" style={{ width: 120 }} {...field('password')} />
                    </Labeled>
                  </>
                ) : (
                  <Labeled label={t('source.field.rtspUrl')}>
                    <input
                      className="input"
                      style={{ minWidth: 280, flex: 1, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 13 }}
                      {...field('rtspUrl')}
                    />
                  </Labeled>
                )}
                <button type="button" className="btn" style={{ whiteSpace: 'nowrap' }} onClick={runTest}>
                  {t(mode === 'ip' ? 'source.testConnection' : 'source.testStream')}
                </button>
              </div>
              {connectError && <ConnectError message={connectError} />}
            </>
          )}
          {test === 'run' && (
            <>
              <div style={{ fontWeight: 600, fontSize: 14 }}>
                {t(mode === 'ip' ? 'source.fetchingFrame' : 'source.openingStream')}
              </div>
              <div className="progress" style={{ marginTop: 10 }}>
                <div className="progress__scanner" />
              </div>
            </>
          )}
          {test === 'ok' && testCam && (
            <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 16, alignItems: 'start' }}>
              <CamGrid title="" cameras={[testCam]} only />
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 20 }}>
                <Labeled label={t('source.field.cameraName')}>
                  <input
                    className="input"
                    style={{ maxWidth: 280 }}
                    placeholder={t('source.placeholder.mainEntrance')}
                    {...field('name')}
                  />
                </Labeled>
                <Labeled label={t('source.field.whereIsIt')}>
                  <select
                    className="input"
                    style={{ maxWidth: 280 }}
                    value={form.area}
                    onChange={(e) => setForm((c) => ({ ...c, area: e.target.value }))}
                  >
                    <option value="">{t('camera.unassignedArea')}</option>
                    {areaOpts.map((a) => (
                      <option key={a}>{a}</option>
                    ))}
                  </select>
                </Labeled>

                <Labeled label={t('source.field.watchFor')}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 2 }}>
                    {FEATURES.map((f) => (
                      <label
                        key={f.key}
                        style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13 }}
                      >
                        <input
                          type="checkbox"
                          checked={form.features.includes(f.key)}
                          onChange={(e) =>
                            setForm((c) => ({
                              ...c,
                              features: e.target.checked
                                ? [...c.features, f.key]
                                : c.features.filter((k) => k !== f.key),
                            }))
                          }
                        />
                        <span>
                          {t(f.label)}
                          {/* Every feature loads models and costs GPU. Saying
                              so here stops "tick everything" being the
                              default, which is how a 208-camera site becomes
                              unaffordable one checkbox at a time. */}
                          <span style={{ color: 'var(--tx3)' }}> · {t(f.cost)}</span>
                        </span>
                      </label>
                    ))}
                  </div>
                </Labeled>

                <button
                  type="button"
                  className="btn"
                  style={{ alignSelf: 'flex-start' }}
                  onClick={addSingle}
                  disabled={busy}
                >
                  {t(busy ? 'source.adding' : 'source.addCamera')}
                </button>
                {connectError && <ConnectError message={connectError} />}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** A connection failure, shown next to the form rather than thrown away.
 *
 *  Wrong password and unreachable host are the two things that actually go
 *  wrong during onboarding, and both are recoverable — the operator needs to
 *  see what happened without losing what they typed. */
function ConnectError({ message }: { message: string }) {
  return (
    <div
      role="alert"
      style={{
        marginTop: 10,
        padding: '8px 12px',
        borderRadius: 8,
        fontSize: 13,
        background: 'color-mix(in srgb, var(--bad) 12%, transparent)',
        color: 'var(--bad)',
      }}
    >
      {message}
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--tx2)' }}>{label}</label>
      {children}
    </div>
  );
}
