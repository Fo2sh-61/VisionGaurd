import { useEffect, useState, type ChangeEvent, type ReactNode } from 'react';
import { useCameras } from '@/app/CameraContext';
import {
  addCamera,
  addCameras,
  connectDvr,
  editCamera,
  getAreaOptions,
  getCameraSources,
  removeCamera,
  scanNetwork,
  testConnection,
} from '@/services/api';
import type {
  AddCameraOutcome,
  Camera,
  CameraSource,
  DvrChannel,
  FeatureNote,
  FoundDevice,
  SourceMode,
} from '@/types';
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
  /** The path after the host, for IP-camera mode. Visible and editable
   *  because it CANNOT be guessed: every brand spells it differently.
   *  It used to be hardcoded to `/stream1` where nobody could see it, so
   *  a camera using anything else simply never streamed. */
  streamPath: string;
  area: string;
  /** What this camera is watched for. Each one loads models, so the choice
   *  has a real cost — an empty list means it streams but nothing analyses it. */
  features: string[];
  /** The identity tier. People pass close enough here to be recognised. */
  faces: boolean;
  /** Which gate this camera watches, and which way it looks. Both are needed
   *  for `vehicles`, and the engine refuses either half on its own. */
  gate: string;
  direction: string;
  /** How the recorder spells its channel URLs, and which channels to try.
   *  A template rather than a guess, because every brand differs — the same
   *  reason `archive.playback_url` in engine.yaml is a template. */
  template: string;
  channels: string;
  /** Edit-only. The analytics rate (how often models run), the picture
   *  rotation, and whether the camera is switched on. Kept as strings on
   *  the form and converted on save, like every other numeric field. */
  fps: string;
  rotate: string;
  enabled: boolean;
}

const EMPTY_FORM: ConnectForm = {
  name: '',
  host: '192.168.1.50',
  port: '554',
  username: 'admin',
  password: '',
  rtspUrl: 'rtsp://192.168.1.150:554/stream1',
  streamPath: '/Streaming/Channels/101',
  area: '',
  features: ['counting'],
  faces: false,
  gate: '',
  direction: 'entry',
  template: 'rtsp://{host}:{port}/Streaming/Channels/{channel}',
  channels: '101, 201, 301, 401',
  fps: '5',
  rotate: '0',
  enabled: true,
};

/** Fill-in helpers for the two commonest recorder brands.
 *
 *  Offered as editable text, never as detection: a pre-filled box makes no
 *  claim about what is on the network, which is the difference between this
 *  and the channel list the engine used to invent. */
const TEMPLATES: { label: MessageKey; template: string; channels: string }[] = [
  {
    label: 'source.template.hikvision',
    template: 'rtsp://{host}:{port}/Streaming/Channels/{channel}',
    channels: '101, 201, 301, 401',
  },
  {
    label: 'source.template.dahua',
    template: 'rtsp://{host}:{port}/cam/realmonitor?channel={channel}&subtype=0',
    channels: '1, 2, 3, 4',
  },
];

/** Stream paths that cover most cameras. Offered as editable text, never
 *  as detection - a pre-filled box makes no claim about what is there. */
const STREAM_PATHS: { label: MessageKey; path: string }[] = [
  { label: 'source.template.hikvision', path: '/Streaming/Channels/101' },
  { label: 'source.template.dahua', path: '/cam/realmonitor?channel=1&subtype=0' },
  { label: 'source.template.generic', path: '/stream1' },
  { label: 'source.template.onvif', path: '/onvif1' },
];

/** What a camera can be watched for, and what each costs to run.
 *
 *  All seven, not three. `track`, `vehicles`, `weapons` and `lostitems` could
 *  not be chosen here at all, so they could only ever be set by editing
 *  engine.yaml and restarting. */
const FEATURES: {
  key: string;
  label: MessageKey;
  cost: MessageKey;
  /** Needs the MOMENT rather than the minute, so it has to keep the higher
   *  rate. A body being followed has to be matched between frames, a knife
   *  is only in shot for a second, and a plate is only readable while the
   *  car is in front of the camera. Counting and zone-watching are the other
   *  kind of question — a person does not cross a room between two frames a
   *  second apart, so those cameras can run slower for nothing. */
  fast?: true;
}[] = [
  { key: 'counting', label: 'source.feature.counting', cost: 'source.feature.counting.cost' },
  { key: 'intrusion', label: 'source.feature.intrusion', cost: 'source.feature.intrusion.cost' },
  { key: 'attendance', label: 'source.feature.attendance', cost: 'source.feature.attendance.cost' },
  { key: 'track', label: 'source.feature.track', cost: 'source.feature.track.cost', fast: true },
  { key: 'vehicles', label: 'source.feature.vehicles', cost: 'source.feature.vehicles.cost', fast: true },
  { key: 'weapons', label: 'source.feature.weapons', cost: 'source.feature.weapons.cost', fast: true },
  { key: 'lostitems', label: 'source.feature.lostitems', cost: 'source.feature.lostitems.cost' },
];

/** The rate these features actually need, in frames a second.
 *
 *  A RECOMMENDATION shown beside the field, never a value written into it.
 *  The operator sets the rate; this only says what the jobs they have ticked
 *  need, at the moment they are ticking them — which is the difference
 *  between a habit and a note in a document nobody reads.
 *
 *  `null` for a camera with no features: it streams and nothing analyses it,
 *  so there is no rate to recommend. Saying "2" there would imply work that
 *  is not happening.
 */
function recommendedRate(features: string[]): number | null {
  if (features.length === 0) return null;
  return FEATURES.some((f) => f.fast && features.includes(f.key)) ? 5 : 2;
}

/** The full URL an IP camera form describes.
 *
 *  One function so Test and Add can never check different things - they
 *  did, and Test was checking a filename. */
function ipUrl(form: ConnectForm): string {
  const path = form.streamPath.startsWith('/') ? form.streamPath : `/${form.streamPath}`;
  return `rtsp://${form.host}:${form.port || 554}${path}`;
}

/** Split "101, 201" into channel ids. Whitespace and stray commas are the
 *  operator's, not an error. */
function parseChannels(raw: string): string[] {
  return raw.split(',').map((c) => c.trim()).filter(Boolean);
}

export function CameraSources() {
  const t = useT();
  const { language } = useLanguage();
  const [sources, setSources] = useState<CameraSource[]>([]);
  const [mode, setMode] = useState<SourceMode | null>(null);
  const [areaOpts, setAreaOpts] = useState<string[]>([]);
  const [form, setForm] = useState<ConnectForm>(EMPTY_FORM);
  const [connectError, setConnectError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState<FeatureNote[]>([]);
  const [outcomes, setOutcomes] = useState<AddCameraOutcome[] | null>(null);
  const { refresh: refreshRoster } = useCameras();

  /** Which camera is open for editing, and what has been typed into it. */
  const [editing, setEditing] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<ConnectForm>(EMPTY_FORM);
  const [shadows, setShadows] = useState(false);

  /** Find one camera among many. No pagination and no camera-count claim —
   *  that is P8 — just a way to stop scrolling. */
  const [filter, setFilter] = useState('');

  const field = (key: keyof ConnectForm) => ({
    value: String(form[key]),
    onChange: (e: ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [key]: e.target.value })),
  });

  const [scanState, setScanState] = useState<'idle' | 'run' | 'done'>('idle');
  const [found, setFound] = useState<FoundDevice[]>([]);
  const [scanReason, setScanReason] = useState<string | null>(null);

  const [dvrStep, setDvrStep] = useState<'form' | 'connecting' | 'channels'>('form');
  // Empty. It used to start as eight invented rows, before any recorder had
  // been contacted at all.
  const [dvrChannels, setDvrChannels] = useState<DvrChannel[]>([]);
  const [dvrReason, setDvrReason] = useState<string | null>(null);
  /** Per channel, what the operator wants it called and where it is. Held
   *  here because the inputs used to be uncontrolled, so what was typed
   *  against a channel was discarded before it could be sent. */
  const [channelNames, setChannelNames] = useState<Record<string, string>>({});
  const [channelAreas, setChannelAreas] = useState<Record<string, string>>({});

  const [test, setTest] = useState<'idle' | 'run' | 'ok'>('idle');
  const [testCam, setTestCam] = useState<Camera | null>(null);

  function reload() {
    void getCameraSources().then(setSources);
  }

  useEffect(() => {
    void getCameraSources().then(setSources);
    void getAreaOptions().then(setAreaOpts);
  }, []);

  function openMode(m: SourceMode) {
    setMode((current) => (current === m ? null : m));
    setEditing(null);
    setScanState('idle');
    setFound([]);
    setScanReason(null);
    setDvrStep('form');
    setDvrChannels([]);
    setDvrReason(null);
    setTest('idle');
    setTestCam(null);
    setConnectError(null);
    setNotes([]);
    setOutcomes(null);
  }

  function startScan() {
    setScanState('run');
    setScanReason(null);
    void scanNetwork()
      .then((result) => {
        setFound(result.devices);
        // "We cannot look" and "your network is empty" are different answers.
        setScanReason(result.available ? null : result.reason ?? null);
        setScanState('done');
      })
      .catch((error: Error) => {
        setScanReason(error.message);
        setScanState('done');
      });
  }

  /** Add a discovered device. It used to push a made-up row into local state
   *  and call nothing at all, so the camera vanished on the next refresh. */
  function addFound(index: number) {
    const device = found[index];
    if (device.added || device.duplicate) return;

    setBusy(true);
    void addCamera({
      name: device.name,
      source: `rtsp://${device.ip}:554/stream1`,
      kind: device.channels > 1 ? 'NVR' : 'IP camera',
      area: form.area,
      features: ['counting'],
    })
      .then(() => {
        setFound((current) =>
          current.map((f, i) => (i === index ? { ...f, added: true } : f)));
        reload();
        refreshRoster();
      })
      .catch((error: Error) => setConnectError(error.message))
      .finally(() => setBusy(false));
  }

  function startDvrConnect() {
    setDvrStep('connecting');
    setConnectError(null);
    setDvrReason(null);
    void connectDvr({
      host: form.host,
      port: Number(form.port) || 554,
      username: form.username,
      password: form.password,
      name: form.name || undefined,
      template: form.template,
      channels: parseChannels(form.channels),
    })
      .then((result) => {
        // The channels the recorder actually answered on. Not a count turned
        // back into `CH 1…N`, which is what this did while the engine was
        // returning a fixture nobody could see through.
        setDvrChannels(result.channels);
        setChannelNames(Object.fromEntries(result.channels.map((c) => [c.channel, c.name])));
        setChannelAreas(Object.fromEntries(result.channels.map((c) => [c.channel, form.area])));
        setDvrReason(result.reachable ? null : result.reason ?? null);
        setDvrStep('channels');
      })
      .catch((error: Error) => {
        setConnectError(error.message);
        setDvrStep('form');
      });
  }

  function toggleDvrChannel(index: number) {
    setDvrChannels((current) =>
      current.map((c, i) =>
        // Only a channel that returned a picture can be ticked. A channel
        // that did not answer is shown so the operator can see WHICH one is
        // wrong, never as something to add.
        i === index && c.status === 'ok' ? { ...c, enabled: !c.enabled } : c));
  }

  /** Add every ticked channel, in one act, and report what happened to each.
   *
   *  It used to push a single invented row — `DVR — 192.168.1.5X`, with an
   *  address made up from a counter — and call nothing. */
  function addDvr() {
    const chosen = dvrChannels.filter((c) => c.enabled && c.status === 'ok');
    if (!chosen.length) return;

    setBusy(true);
    setConnectError(null);
    void addCameras(
      chosen.map((c) => ({
        name: channelNames[c.channel] || c.name,
        source: form.template
          .replace('{channel}', c.channel)
          .replace('{host}', form.host)
          .replace('{port}', form.port || '554'),
        kind: 'DVR' as const,
        area: channelAreas[c.channel] ?? form.area,
        features: form.features,
        // Sent, not left to the engine's default. Adding sixteen channels at
        // 5/sec when 2 would do is the single largest way to fill a machine
        // in one click, and the form now asks.
        fps: Number(form.fps) || undefined,
        faces: form.faces,
        username: form.username,
        password: form.password,
      })),
    )
      .then((results) => {
        setOutcomes(results);
        reload();
        refreshRoster();
        if (results.every((r) => r.ok)) {
          setMode(null);
          setDvrStep('form');
          setDvrChannels([]);
        }
      })
      .catch((error: Error) => setConnectError(error.message))
      .finally(() => setBusy(false));
  }

  function runTest() {
    setTest('run');
    setConnectError(null);
    // A failed test comes back as a camera with `offline: true` and a reason,
    // so it renders inline instead of throwing.
    // The SAME url `addSingle` would use. It used to send the bare host,
    // which the engine could only read as a filename - so Test failed with
    // "no such file" on a camera that was merely unreachable.
    void testConnection(
      mode === 'rtsp'
        ? { source: form.rtspUrl }
        : { source: ipUrl(form), username: form.username, password: form.password },
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
    const source = mode === 'rtsp' ? form.rtspUrl : ipUrl(form);

    void addCamera({
      name: form.name || (mode === 'rtsp' ? 'RTSP stream' : `Camera ${form.host}`),
      source,
      kind: mode === 'rtsp' ? 'RTSP' : 'IP camera',
      // Empty, not the word "Unassigned": absence is absence, and CamGrid
      // supplies the heading. Storing the English word would put cameras in
      // two different groups meaning the same thing.
      area: form.area,
      features: form.features,
      fps: Number(form.fps) || undefined,
      faces: form.faces,
      gate: form.gate ? Number(form.gate) : undefined,
      direction: form.gate ? form.direction : undefined,
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

  function openEdit(source: CameraSource) {
    setMode(null);
    setEditing(source.id);
    setShadows(false);
    setNotes([]);
    setConnectError(null);
    setEditForm({
      ...EMPTY_FORM,
      name: source.name,
      area: source.area ?? '',
      features: source.features,
      faces: source.faces,
      gate: source.gate ? String(source.gate) : '',
      direction: source.direction ?? 'entry',
      fps: String(source.fps),
      rotate: String(source.rotate),
      enabled: source.enabled,
      // Address and credentials start BLANK on the edit form: the stored
      // password is masked, so there is nothing to prefill, and a blank
      // address means "leave it alone". Typing one replaces the source.
      rtspUrl: '',
      username: '',
      password: '',
    });
  }

  function saveEdit() {
    if (!editing) return;
    setBusy(true);
    setConnectError(null);
    // A blank address means "leave the source alone"; a typed one replaces
    // it, with any separate credentials folded in by the engine.
    const changingAddress = editForm.rtspUrl.trim().length > 0;
    void editCamera(editing, {
      name: editForm.name,
      area: editForm.area,
      features: editForm.features,
      faces: editForm.faces,
      gate: editForm.gate ? Number(editForm.gate) : undefined,
      direction: editForm.gate ? editForm.direction : undefined,
      fps: Number(editForm.fps) || undefined,
      rotate: Number(editForm.rotate),
      enabled: editForm.enabled,
      source: changingAddress ? editForm.rtspUrl.trim() : undefined,
      username: changingAddress && editForm.username ? editForm.username : undefined,
      password: changingAddress && editForm.username ? editForm.password : undefined,
    })
      .then((result) => {
        setSources((current) =>
          current.map((s) => (s.id === result.camera.id ? result.camera : s)));
        setNotes(result.featureNotes.filter((n) => !n.running));
        setShadows(result.shadowsConfig);
        refreshRoster();
        if (!result.shadowsConfig) setEditing(null);
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

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? sources.filter((s) =>
        [s.name, s.area ?? '', s.ip, s.features.join(' ')]
          .join(' ')
          .toLowerCase()
          .includes(needle))
    : sources;
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
        {sources.length > 6 && (
          <input
            className="input"
            style={{ maxWidth: 220 }}
            placeholder={t('source.findCamera')}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        )}
      </div>

      {shown.map((src) => {
        const badge = badgeFor(src.status);
        return (
          <div key={src.id}>
            <div
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
                  {src.type} · {src.ip}
                  {src.features.length > 0 && ` · ${src.features.join(', ')}`}
                  {src.faces && ` · ${t('source.identityTier')}`}
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
              <button type="button" className="linkbtn linkbtn--quiet" onClick={() => openEdit(src)}>
                {t('source.edit')}
              </button>
              <button type="button" className="linkbtn linkbtn--quiet" onClick={() => removeSource(src.id)}>
                {t('source.remove')}
              </button>
            </div>

            {editing === src.id && (
              <div style={{ background: 'var(--bg)', borderRadius: 12, padding: '16px 18px', margin: '10px 0' }}>
                {/* The raw stream, no features applied. CamGrid without
                    tileOverlay polls only the snapshot, so there are no
                    boxes, no names and no counting line - just the picture
                    the camera is sending, for confirming it is the right one
                    and pointed the right way while you configure it. */}
                {src.status === 'ok' && (
                  <div style={{ maxWidth: 360, marginBottom: 14 }}>
                    <CamGrid
                      title=""
                      only
                      cameras={[{
                        id: src.id,
                        name: src.name,
                        status: '',
                        offline: false,
                        boxes: [],
                        snapshotUrl: `/cameras/${encodeURIComponent(src.id)}/snapshot`,
                      }]}
                    />
                  </div>
                )}
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                  <Labeled label={t('source.field.cameraName')}>
                    <input
                      className="input"
                      style={{ maxWidth: 240 }}
                      value={editForm.name}
                      onChange={(e) => setEditForm((c) => ({ ...c, name: e.target.value }))}
                    />
                  </Labeled>
                  <Labeled label={t('source.field.whereIsIt')}>
                    <select
                      className="input"
                      style={{ maxWidth: 200 }}
                      value={editForm.area}
                      onChange={(e) => setEditForm((c) => ({ ...c, area: e.target.value }))}
                    >
                      <option value="">{t('camera.unassignedArea')}</option>
                      {areaOpts.map((a) => (
                        <option key={a}>{a}</option>
                      ))}
                    </select>
                  </Labeled>
                </div>

                {/* Address. The stored password is masked, so the field starts
                    empty and a blank one means "keep the current address".
                    Typing a new URL replaces the source; the current one is
                    shown (redacted) as the placeholder so the operator knows
                    what they are changing. Changing it reopens the stream. */}
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 12 }}>
                  <Labeled label={t('source.field.changeAddress')}>
                    <input
                      className="input"
                      style={{ minWidth: 300, flex: 1, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12.5 }}
                      placeholder={src.ip}
                      value={editForm.rtspUrl}
                      onChange={(e) => setEditForm((c) => ({ ...c, rtspUrl: e.target.value }))}
                    />
                  </Labeled>
                </div>
                {editForm.rtspUrl.trim() !== '' && !editForm.rtspUrl.includes('@') && (
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 8 }}>
                    <Labeled label={t('source.field.username')}>
                      <input className="input" style={{ width: 120 }}
                        value={editForm.username}
                        onChange={(e) => setEditForm((c) => ({ ...c, username: e.target.value }))} />
                    </Labeled>
                    <Labeled label={t('source.field.password')}>
                      <input className="input" type="password" style={{ width: 120 }}
                        value={editForm.password}
                        onChange={(e) => setEditForm((c) => ({ ...c, password: e.target.value }))} />
                    </Labeled>
                  </div>
                )}

                {/* Rotation and whether the camera is on. The analytics rate
                    moved into FeaturePicker below, beside the features it
                    multiplies — it was here and nowhere else, so it could be
                    corrected on an existing camera but never set on a new
                    one. Two copies of the same input on one panel is how the
                    add and edit paths drift apart. */}
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 12 }}>
                  <Labeled label={t('source.field.rotation')}>
                    <select
                      className="input" style={{ width: 100 }}
                      value={editForm.rotate}
                      onChange={(e) => setEditForm((c) => ({ ...c, rotate: e.target.value }))}>
                      <option value="0">0&deg;</option>
                      <option value="90">90&deg;</option>
                      <option value="180">180&deg;</option>
                      <option value="270">270&deg;</option>
                    </select>
                  </Labeled>
                  <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, paddingTop: 18 }}>
                    <input
                      type="checkbox"
                      checked={editForm.enabled}
                      onChange={(e) => setEditForm((c) => ({ ...c, enabled: e.target.checked }))} />
                    <span>{t('source.field.enabled')}</span>
                  </label>
                </div>

                <div style={{ marginTop: 12 }}>
                  <FeaturePicker
                    form={editForm}
                    setForm={setEditForm}
                    t={t}
                  />
                </div>

                {src.fromConfig && (
                  <Notice message={t('source.fromConfigWarning')} />
                )}
                {shadows && <Notice message={t('source.nowShadowsConfig')} />}
                {notes.map((n) => (
                  <Notice
                    key={n.feature}
                    message={t('source.featureNotRunning', { feature: n.feature }) +
                      (n.reason ? ` ${n.reason}` : '')}
                  />
                ))}
                {connectError && <ConnectError message={connectError} />}

                <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
                  <button type="button" className="btn" onClick={saveEdit} disabled={busy}>
                    {t(busy ? 'source.saving' : 'source.save')}
                  </button>
                  <button type="button" className="linkbtn" onClick={() => setEditing(null)}>
                    {t('source.cancel')}
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {sources.length > 0 && shown.length === 0 && (
        <div style={{ padding: '16px 0', fontSize: 13.5, color: 'var(--tx2)' }}>
          {t('source.noneMatch')}
        </div>
      )}

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
              <div style={{ fontWeight: 600, fontSize: 14 }}>{t('source.scanningNetwork')}</div>
              <div className="progress" style={{ marginTop: 10 }}>
                <div className="progress__scanner" />
              </div>
            </>
          )}
          {scanState === 'done' && (
            <>
              {/* "We cannot look" is not "your network is empty". The engine
                  sends which one it is, with a reason. */}
              {scanReason ? (
                <Notice message={scanReason} />
              ) : (
                <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
                  {t('source.devicesFound', { count: found.length })}
                </div>
              )}
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
                    <button type="button" className="btn btn--ghost" style={{ height: 32, padding: '0 14px', fontSize: 12.5 }} onClick={() => addFound(i)} disabled={busy}>
                      {t('source.add')}
                    </button>
                  ) : (
                    <span style={{ fontSize: 12.5, color: 'var(--tx3)', whiteSpace: 'nowrap' }}>
                      {t(f.duplicate ? 'source.alreadyAdded' : 'source.added')}
                    </span>
                  )}
                </div>
              ))}
              {connectError && <ConnectError message={connectError} />}
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
              </div>

              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginTop: 10 }}>
                <Labeled label={t('source.field.template')}>
                  <input
                    className="input"
                    style={{ minWidth: 340, flex: 1, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12.5 }}
                    {...field('template')}
                  />
                </Labeled>
                <Labeled label={t('source.field.channels')}>
                  <input className="input" style={{ width: 180, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12.5 }} {...field('channels')} />
                </Labeled>
                <button type="button" className="btn" style={{ whiteSpace: 'nowrap' }} onClick={startDvrConnect}>
                  {t('source.connectAndPull')}
                </button>
              </div>

              <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>{t('source.templateHelp')}</span>
                {TEMPLATES.map((preset) => (
                  <button
                    key={preset.template}
                    type="button"
                    className="chip-btn chip-btn--off"
                    style={{ height: 28, padding: '0 12px', fontSize: 12 }}
                    onClick={() =>
                      setForm((c) => ({ ...c, template: preset.template, channels: preset.channels }))
                    }
                  >
                    {t(preset.label)}
                  </button>
                ))}
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
              {dvrReason ? (
                <Notice message={dvrReason} />
              ) : (
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {t('source.channelsAnswered', {
                    answered: dvrChannels.filter((c) => c.status === 'ok').length,
                    total: dvrChannels.length,
                  })}
                </div>
              )}
              <div style={{ fontSize: 13, color: 'var(--tx2)', margin: '2px 0 8px' }}>
                {t('source.nameEachCamera')}
              </div>
              {dvrChannels.map((ch, i) => (
                <div key={ch.channel} style={{ display: 'grid', gridTemplateColumns: '64px 1fr 1fr 44px', alignItems: 'center', gap: 10, padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--tx3)', fontFamily: 'ui-monospace, Menlo, monospace' }}>{ch.channel}</span>
                  {ch.status === 'ok' ? (
                    <>
                      {/* Controlled. These were `defaultValue` with no handler,
                          so what an operator typed against a channel was
                          discarded before it could be sent anywhere. */}
                      <input
                        className="input"
                        style={{ height: 36, fontSize: 13 }}
                        value={channelNames[ch.channel] ?? ch.name}
                        onChange={(e) =>
                          setChannelNames((c) => ({ ...c, [ch.channel]: e.target.value }))}
                      />
                      <select
                        className="input"
                        style={{ height: 36, fontSize: 13, minWidth: 0 }}
                        value={channelAreas[ch.channel] ?? ''}
                        onChange={(e) =>
                          setChannelAreas((c) => ({ ...c, [ch.channel]: e.target.value }))}
                      >
                        <option value="">{t('camera.unassignedArea')}</option>
                        {areaOpts.map((a) => (
                          <option key={a}>{a}</option>
                        ))}
                      </select>
                    </>
                  ) : (
                    // Listed, never offered. Three states, and they must not
                    // read alike: answered, asked-and-silent, never-asked.
                    <div style={{ gridColumn: 'span 2', fontSize: 12.5, color: 'var(--tx3)' }}>
                      {ch.checked
                        ? t('source.channelNoPicture') + (ch.error ? ` — ${ch.error}` : '')
                        : t('source.channelNotChecked')}
                    </div>
                  )}
                  {ch.status === 'ok' ? (
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
                  ) : (
                    <span />
                  )}
                  {ch.resolution && (
                    <span style={{ gridColumn: '2 / span 3', fontSize: 11.5, color: 'var(--tx3)' }}>
                      {ch.resolution}
                      {ch.latencyMs != null && ` · ${Math.round(ch.latencyMs)} ms`}
                    </span>
                  )}
                </div>
              ))}

              {dvrChannels.some((c) => c.status === 'ok') && (
                <div style={{ marginTop: 12 }}>
                  <FeaturePicker form={form} setForm={setForm} t={t} />
                </div>
              )}

              {outcomes && <Outcomes outcomes={outcomes} t={t} />}
              {connectError && <ConnectError message={connectError} />}

              <button
                type="button"
                className="btn"
                style={{ marginTop: 14 }}
                onClick={addDvr}
                disabled={busy || !dvrChannels.some((c) => c.enabled && c.status === 'ok')}
              >
                {t('source.addNCameras', {
                  count: dvrChannels.filter((c) => c.enabled && c.status === 'ok').length,
                })}
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
                    {/* Visible, because it cannot be guessed. This was
                        hardcoded to `/stream1` inside the component, so a
                        camera using any other path was added and never
                        streamed, with nothing on screen to say why. */}
                    <Labeled label={t('source.field.streamPath')}>
                      <input className="input" style={{ width: 220, fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12.5 }} {...field('streamPath')} />
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
              {mode === 'ip' && (
                <>
                  <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 12.5, color: 'var(--tx3)' }}>{t('source.templateHelp')}</span>
                    {STREAM_PATHS.map((preset) => (
                      <button
                        key={preset.path}
                        type="button"
                        className="chip-btn chip-btn--off"
                        style={{ height: 28, padding: '0 12px', fontSize: 12 }}
                        onClick={() => setForm((c) => ({ ...c, streamPath: preset.path }))}
                      >
                        {t(preset.label)}
                      </button>
                    ))}
                  </div>
                  {/* Exactly what will be opened. No hidden guess. */}
                  <div style={{ fontSize: 12, color: 'var(--tx3)', marginTop: 8, fontFamily: 'ui-monospace, Menlo, monospace' }}>
                    {ipUrl(form)}
                  </div>
                </>
              )}
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

                <FeaturePicker form={form} setForm={setForm} t={t} />

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

/** What a camera is watched for, and the settings each feature needs.
 *
 *  Shared by the add form and the edit form so the two cannot drift — a
 *  camera that can be created one way and corrected another is how a setting
 *  ends up reachable in only half the product. */
function FeaturePicker({
  form,
  setForm,
  t,
}: {
  form: ConnectForm;
  setForm: (update: (current: ConnectForm) => ConnectForm) => void;
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}) {
  const has = (key: string) => form.features.includes(key);
  const recommended = recommendedRate(form.features);

  return (
    <Labeled label={t('source.field.watchFor')}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 2 }}>
        {FEATURES.map((f) => (
          <label
            key={f.key}
            style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13 }}
          >
            <input
              type="checkbox"
              checked={has(f.key)}
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
              {/* Every feature loads models and costs GPU. Saying so here
                  stops "tick everything" being the default, which is how a
                  208-camera site becomes unaffordable one checkbox at a time. */}
              <span style={{ color: 'var(--tx3)' }}> · {t(f.cost)}</span>
            </span>
          </label>
        ))}
      </div>

      {/* The identity tier. Only worth asking about when this camera is doing
          attendance at all. */}
      {has('attendance') && (
        <label style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 13, marginTop: 8 }}>
          <input
            type="checkbox"
            checked={form.faces}
            onChange={(e) => setForm((c) => ({ ...c, faces: e.target.checked }))}
          />
          <span>
            {t('source.identityTier')}
            <span style={{ color: 'var(--tx3)' }}> · {t('source.identityTier.help')}</span>
          </span>
        </label>
      )}

      {/* A gate camera needs both, and the engine refuses either half on its
          own — a gate number with nothing reading plates, or plate reading
          that cannot say which gate a car passed. */}
      {has('vehicles') && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginTop: 8 }}>
          <Labeled label={t('source.field.gate')}>
            <input
              className="input"
              style={{ width: 80 }}
              value={form.gate}
              onChange={(e) => setForm((c) => ({ ...c, gate: e.target.value }))}
            />
          </Labeled>
          <Labeled label={t('source.field.direction')}>
            <select
              className="input"
              style={{ width: 120 }}
              value={form.direction}
              onChange={(e) => setForm((c) => ({ ...c, direction: e.target.value }))}
            >
              <option value="entry">{t('source.direction.entry')}</option>
              <option value="exit">{t('source.direction.exit')}</option>
            </select>
          </Labeled>
          <span style={{ fontSize: 12, color: 'var(--tx3)', paddingBottom: 8 }}>
            {t('source.direction.help')}
          </span>
        </div>
      )}

      {/* The analytics rate, beside the features it multiplies — because it
          IS a multiplier, and it was previously only reachable by adding a
          camera and then reopening it to edit. A camera at 5/sec costs five
          times what one frame costs; turning a plain counting camera down to
          2 is the cheapest room this product has, and nothing on the form
          used to say so. */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', marginTop: 12 }}>
        <Labeled label={t('source.field.analyticsRate')}>
          <input
            className="input"
            type="number"
            min={1}
            max={60}
            style={{ width: 90 }}
            value={form.fps}
            onChange={(e) => setForm((c) => ({ ...c, fps: e.target.value }))}
          />
        </Labeled>
        <span style={{ fontSize: 12, color: 'var(--tx3)', paddingBottom: 8, maxWidth: 460 }}>
          {t('source.field.analyticsRate.help')}
        </span>
      </div>

      {/* What the ticked features actually need, said at the moment they are
          ticked. Shown, never written into the field: the operator sets the
          rate, and a form that silently changes a number somebody typed is
          how a setting stops being trusted. It only appears when it
          disagrees with what is in the box, so it is advice at the one
          moment advice is useful rather than a permanent label. */}
      {recommended !== null && Number(form.fps) !== recommended && (
        <div style={{ fontSize: 12, color: 'var(--tx2)', marginTop: 6 }}>
          {t(
            Number(form.fps) > recommended
              ? 'source.field.analyticsRate.lower'
              : 'source.field.analyticsRate.raise',
            { rate: recommended },
          )}{' '}
          <button
            type="button"
            className="linkbtn"
            onClick={() => setForm((c) => ({ ...c, fps: String(recommended) }))}
          >
            {t('source.field.analyticsRate.use', { rate: recommended })}
          </button>
        </div>
      )}
    </Labeled>
  );
}

/** One outcome per camera from a bulk add.
 *
 *  Sixteen channels used to be sixteen calls, and the fourth failing said
 *  nothing about the other twelve. */
function Outcomes({
  outcomes,
  t,
}: {
  outcomes: AddCameraOutcome[];
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
}) {
  const failed = outcomes.filter((o) => !o.ok);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 600 }}>
        {t('source.addedCount', {
          added: outcomes.length - failed.length,
          total: outcomes.length,
        })}
      </div>
      {failed.map((o) => (
        <div key={o.index} style={{ fontSize: 12.5, color: 'var(--bad)', marginTop: 4 }}>
          {o.source} — {o.error}
        </div>
      ))}
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

/** Something true the operator needs to know, which is not an error.
 *
 *  "This engine cannot search the network", "the recorder answered nothing",
 *  "this camera came from the config file". Each is a fact with a
 *  consequence, and none of them is a failure of what they just did. */
function Notice({ message }: { message: string }) {
  return (
    <div
      style={{
        marginTop: 10,
        padding: '8px 12px',
        borderRadius: 8,
        fontSize: 13,
        background: 'color-mix(in srgb, var(--warn) 12%, transparent)',
        color: 'var(--tx)',
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
