"""VisionGuard engine.

Layers, bottom to top. Each only knows about the one below it:

    ingest    RTSP/webcam capture, reconnect, last-good-frame cache
    infer     shared model runners (decode once, detect once)
    track     per-camera multi-object tracking, stable track ids
    features  one file per product feature, consuming tracked detections
    events    rules output -> database + clips + pub/sub
    api       FastAPI, shaped to match web/src/services/api.ts

The front end only ever talks to `api`.
"""

__version__ = "0.1.0"
