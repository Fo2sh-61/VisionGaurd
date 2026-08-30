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
