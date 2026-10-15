/** Where the picture actually is, inside the frame that holds it.
 *
 *  A camera tile is a fixed rectangle chosen by the page. The picture inside
 *  it is whatever shape the camera happens to be. Those two only agree by
 *  accident, and every overlay the engine sends — boxes, zones, the counting
 *  line — is a fraction of the PICTURE.
 *
 *  Positioning an overlay as a percentage of the tile is therefore only
 *  correct when the tile and the picture are the same shape. On the people
 *  counting page the tile is about 360x380 and the camera is 16:9, so the
 *  picture occupies a band across the middle and every box was drawn tens of
 *  percent away from the person it belonged to. The engine's geometry was
 *  right the whole time; it was being read in the wrong frame of reference.
 *
 *  This returns the rectangle the picture is really drawn in, in CSS pixels
 *  relative to the tile's top-left corner, for `object-fit: contain`. Overlays
 *  are then positioned inside that rectangle and land on people.
 */

export type PictureRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

/** The picture's rectangle within a `frameWidth` x `frameHeight` tile.
 *
 *  `aspect` is the picture's width divided by its height. Until the first
 *  frame has loaded there is nothing to know, so the whole tile is returned —
 *  which is what the overlays used to assume, and the only honest answer while
 *  the shape is still unknown.
 */
export function pictureRect(
  frameWidth: number,
  frameHeight: number,
  aspect: number | null,
): PictureRect {
  const whole = { left: 0, top: 0, width: frameWidth, height: frameHeight };
  if (frameWidth <= 0 || frameHeight <= 0) return whole;
  if (aspect === null || !Number.isFinite(aspect) || aspect <= 0) return whole;

  if (aspect > frameWidth / frameHeight) {
    // Wider than the tile: it spans the full width, with bars above and below.
    const height = frameWidth / aspect;
    return { left: 0, top: (frameHeight - height) / 2, width: frameWidth, height };
  }

  // Taller than the tile: it spans the full height, with bars either side.
  const width = frameHeight * aspect;
  return { left: (frameWidth - width) / 2, top: 0, width, height: frameHeight };
}

/** The most pictures a second one tile asks for. 15 reads as video, and it is
 *  the engine's own ceiling (`MAX_TILE_FPS` in `ingest/source.py`): asking
 *  for more would fetch the same picture twice. */
export const TILE_MAX_FPS = 15;

/** The fewest. A screen full of tiles still moves. */
export const TILE_MIN_FPS = 2;

/** Pictures a second for the whole screen, shared by the tiles on it.
 *
 *  Every tile is its own request, and the browser runs only a handful of
 *  requests to one host at a time, so the total is what has to be kept in
 *  hand, not the rate of any one tile. 120 lets eight tiles run at the full
 *  15 — more than a phone screen holds — and a desktop wall shares it out:
 *  twelve at 10 a second, twenty-four at 5. */
export const SCREEN_PICTURES_PER_SECOND = 120;

/** How often a camera tile asks for a new picture, given how many tiles are
 *  on screen right now.
 *
 *  ON SCREEN, not on the page. Until 28 Sep 2026 this was given the number
 *  of tiles the page had drawn, so ten cameras on the phone's Cameras page
 *  ran at 5 a second each even when only two were in view, and the eight
 *  scrolled out of sight kept asking for pictures nobody saw. A tile off
 *  screen now asks for nothing, and the tiles that are left share the
 *  screen's budget. The phone's Home camera, alone on its screen, runs at
 *  the full 15; it had been left at the component's old default of one
 *  picture a second, which is what made it look like a slide show.
 *
 *  Pictures rather than a stream. MJPEG would be smoother per tile, but it
 *  holds a connection for as long as the tile is up, and a few of them would
 *  take every connection the browser allows and stall the page. A polled
 *  picture lets go of its connection between pictures, and the engine keeps
 *  one encoded copy per frame and size, so tiles showing the same camera
 *  share it. The stream stays where it belongs: the enlarged view, one at a
 *  time.
 *
 *  What makes 15 a second affordable (11 Sep 2026): each tile asks for a
 *  picture the size it shows, not the full 1280 px, and tells the engine its
 *  rate, so the camera prepares pictures that fast only while a tile is
 *  asking. Measured at 1080p on the dev laptop, one tile at 15 a second costs
 *  about what one at 5 had. The AI runs no faster for it; models keep their
 *  own rate. */
export function tileRefreshMs(onScreen: number): number {
  const fps = SCREEN_PICTURES_PER_SECOND / Math.max(1, onScreen);
  return 1_000 / Math.min(TILE_MAX_FPS, Math.max(TILE_MIN_FPS, fps));
}

/** How often a tile's OVERLAY re-fetches, on the pages that draw one.
 *
 *  Deliberately slower than the picture. An overlay poll is its own request
 *  and renews a worker's boost, and its boxes only change when the model
 *  runs; making the picture smoother was never a reason to poll the knife
 *  worker harder. Counted by tiles on screen, like the picture. */
export function tileBoxRefreshMs(onScreen: number): number {
  if (onScreen <= 4) return 200;
  if (onScreen <= 12) return 500;
  return 1_500;
}
