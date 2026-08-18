"""Layer 1 — getting frames off cameras and keeping them flowing.

Nothing above this layer knows whether a frame came from a webcam, an RTSP
stream or a file on disk, or how many times the connection dropped to get it.
"""

from vg.ingest.source import CameraSource, Frame, SourceHealth, SourceStatus, open_source

__all__ = ["CameraSource", "Frame", "SourceHealth", "SourceStatus", "open_source"]
