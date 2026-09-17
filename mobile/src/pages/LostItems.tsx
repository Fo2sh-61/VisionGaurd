import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useCameras } from '@/app/CameraContext';
import { useCapability } from '@/app/CapabilityContext';
import { useT } from '@/app/LanguageContext';
import type { MessageKey } from '@/i18n';
import { CamGrid } from '@/components/CamGrid';
import { Icon } from '@/components/Icon';
import { Badge, DataNotice, Empty, PageHeader } from '@/components/ui';

/*  Lost bag, laid out for a phone (spec 015, P13-FR-lostbag).
 *
 *  Built from `web/src/pages/LostItems.tsx`: the same roster, the same
 *  colour palette, the same watching grid — nothing here searches, nothing
 *  here records. What changed is the shape: the console's table-like tick
 *  list becomes a real list of 44px rows, each area's checkbox now has the
 *  whole row as its target, and an area's cameras are revealed by their own
 *  44px button rather than a text arrow.
 *
 *  **Nothing is recorded.** No clip, no still, no history. A bag that was
 *  taken before this screen was opened cannot be found here.
 *
 *  **A box is a possible bag, never a found one.** That is why the box is
 *  amber and drawn over a live picture the guard can judge for themselves.
 *
 *  Fixed here: the empty-ticked sentence used to lower-case the colour's raw
 *  key (`lost.colour.blue`) instead of its wording. It now reads the same
 *  translated word the watching grid already uses. */

/** Sentinel for cameras with no area. The heading is wording and comes
 *  from the catalogue; the camera's own `area` is data. */
const UNASSIGNED = 'camera.unassignedArea';

/** The colour palette, and the only names the engine accepts.
 *
 *  Grey and white are one chip on purpose — they differ only in lightness,
 *  and lightness is exactly what lighting changes (research D3). `Any` is a
 *  gradient because it is not a colour: it is the absence of a filter. */
const COLOURS: { name: MessageKey; value?: string; dot: string }[] = [
  { name: 'lost.colour.any', dot: 'linear-gradient(135deg,#d7ded9,#8d9a95)' },
  { name: 'lost.colour.black', value: 'black', dot: '#2b2f2c' },
  { name: 'lost.colour.light', value: 'light', dot: 'linear-gradient(135deg,#f2f4f3,#9aa3a0)' },
  { name: 'lost.colour.red', value: 'red', dot: '#c0483f' },
  { name: 'lost.colour.blue', value: 'blue', dot: '#3f6fb5' },
  { name: 'lost.colour.green', value: 'green', dot: '#3e8c5c' },
  { name: 'lost.colour.yellow', value: 'yellow', dot: '#d8b038' },
];

export function LostItems() {
  const t = useT();
  const capability = useCapability('search_lost');
  // The live roster, which is where areas actually live. The engine is never
  // asked what an area contains — it already sent the answer with the cameras.
  const { cameras } = useCameras();

  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const [openAreas, setOpenAreas] = useState<Set<string>>(new Set());
  // Ask lands here with the question resolved.
  const [params] = useSearchParams();
  const [colour, setColour] = useState<string | undefined>(
    params.get('colour') ?? undefined);

  /** Areas in roster order, each with its cameras. `Unassigned` is a real
   *  group, not a leftover: today it is almost every camera, and hiding them
   *  would hide the whole school. */
  const areas = useMemo(() => {
    const groups: { name: string; cameras: typeof cameras }[] = [];
    for (const cam of cameras) {
      const name = cam.area || UNASSIGNED;
      const found = groups.find((g) => g.name === name);
      if (found) found.cameras.push(cam);
      else groups.push({ name, cameras: [cam] });
    }
    return groups;
  }, [cameras]);

  const watching = useMemo(
    () => cameras.filter((c) => ticked.has(c.id)),
    [cameras, ticked],
  );

  const toggleCamera = (id: string) =>
    setTicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const toggleArea = (name: string) => {
    const ids = areas.find((a) => a.name === name)?.cameras.map((c) => c.id) ?? [];
    setTicked((prev) => {
      const next = new Set(prev);
      const all = ids.every((id) => next.has(id));
      for (const id of ids) {
        if (all) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  };

  const toggleOpen = (name: string) =>
    setOpenAreas((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const chosen = COLOURS.find((c) => c.value === colour) ?? COLOURS[0];
  const offline = watching.filter((c) => c.offline);

  return (
    <>
      <DataNotice capability={capability} />
      <PageHeader title={t('lost.title')} lead={t('lost.lead')} />

      <section className="stack">
        <div className="sechead">
          <span className="sechead__title">{t('lost.whereToWatch')}</span>
        </div>
        {areas.length === 0 ? (
          <div className="card"><Empty>{t('lost.noCameras')}</Empty></div>
        ) : (
          <div className="list">
            {areas.map((area) => {
              const ids = area.cameras.map((c) => c.id);
              const on = ids.filter((id) => ticked.has(id)).length;
              const open = openAreas.has(area.name);
              const areaLabel = area.name === UNASSIGNED ? t(UNASSIGNED) : area.name;
              return (
                <div key={area.name}>
                  <div className="li">
                    {/* The label wraps the checkbox and the area's name and
                        count, so the whole row — not just the 22px box — is
                        the tap target. */}
                    <label className="hstack" style={{ flex: 1, minWidth: 0, minHeight: 44, cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={on > 0 && on === ids.length}
                        // Some but not all: the box says "partly", which is
                        // the truth and is not a state a checkbox has
                        // without being told.
                        ref={(el) => {
                          if (el) el.indeterminate = on > 0 && on < ids.length;
                        }}
                        onChange={() => toggleArea(area.name)}
                        aria-label={t('lost.watchEveryCameraIn', { area: areaLabel })}
                        style={{ width: 24, height: 24, flexShrink: 0, accentColor: 'var(--ac)' }}
                      />
                      <span className="li__main">
                        <span className="li__title">{areaLabel}</span>
                        <span className="li__sub">
                          {on > 0
                            ? `${on} of ${ids.length}`
                            : `${ids.length} camera${ids.length === 1 ? '' : 's'}`}
                        </span>
                      </span>
                    </label>
                    <button
                      type="button"
                      className="iconbtn"
                      aria-expanded={open}
                      aria-label={t(
                        open ? 'phone.lost.hideCameras' : 'phone.lost.showCameras',
                        { area: areaLabel },
                      )}
                      onClick={() => toggleOpen(area.name)}
                    >
                      <span style={{ display: 'inline-flex', transform: open ? 'rotate(90deg)' : undefined }}>
                        <Icon name="chevron" mirror />
                      </span>
                    </button>
                  </div>
                  {open && area.cameras.map((cam) => (
                    <label key={cam.id} className="li" style={{ paddingInlineStart: 40 }}>
                      <input
                        type="checkbox"
                        checked={ticked.has(cam.id)}
                        onChange={() => toggleCamera(cam.id)}
                        style={{ width: 22, height: 22, flexShrink: 0, accentColor: 'var(--ac)' }}
                      />
                      <span className="li__main">
                        <span className="li__title" style={{ fontWeight: 500 }}>{cam.name}</span>
                      </span>
                      {cam.offline && <Badge tone="neutral">offline</Badge>}
                    </label>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card stack">
        <div>
          <div className="card__title" style={{ fontSize: 15 }}>{t('lost.colour')}</div>
        </div>
        <div className="chips chips--wrap">
          {COLOURS.map((c) => (
            <button
              key={c.name}
              type="button"
              className={colour === c.value ? 'chip chip--on' : 'chip'}
              aria-pressed={colour === c.value}
              onClick={() => setColour(c.value)}
            >
              <span
                aria-hidden="true"
                style={{
                  width: 13, height: 13, borderRadius: '50%', flexShrink: 0,
                  background: c.dot, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.18)',
                }}
              />
              <span>{t(c.name)}</span>
            </button>
          ))}
        </div>
        <p className="note">
          Colour is judged from the camera picture and can be wrong in poor light.
          Pick Any if the bag is not outlined.
        </p>
      </section>

      {watching.length === 0 ? (
        <div className="card">
          <Empty>
            Nothing ticked yet. Tick an area or a camera above and it appears
            below, live, with any {colour ? t(chosen.name).toLowerCase() : ''} bag
            outlined in amber.
          </Empty>
        </div>
      ) : (
        <>
          {offline.length > 0 && (
            <div className="notice notice--amber" role="status">
              {t(offline.length === 1 ? 'lost.offlineOne' : 'lost.offlineMany', {
                cameras: offline.map((c) => c.name).join(', '),
              })}
            </div>
          )}
          <CamGrid
            title={t('lost.watchingNow')}
            note={
              (colour
                ? t('lost.colourOutlined', { colour: t(chosen.name).toLowerCase() })
                : t('lost.anyOutlined')) + t('lost.boxCaveat')
            }
            cameras={watching}
            only
            searchable={watching.length > 12}
            pageSize={12}
            feature="lost"
            colour={colour}
            tileOverlay
          />
        </>
      )}
    </>
  );
}
