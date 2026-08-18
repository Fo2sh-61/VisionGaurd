"""Audit every weight file in models/ and write down what it actually is.

The models folder arrived with 1.3 GB of binaries and no documentation: no class
lists, no record of what the YOLO-World variants were prompted with, no note of
which GPU or TensorRT version built the .engine files. This script reads that
information back out of the files themselves and writes:

    models/MODELS.md          human-readable inventory
    models/<name>.yaml        one sidecar per weight file

Run it from the repo root:  python engine/tools/audit_models.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import pickle
import struct
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

# Unpickling a YOLO-World checkpoint imports ultralytics' WorldModel, which
# runs a dependency check and will try to `pip install git+.../CLIP.git` on the
# spot. We are auditing files, not installing packages — turn that off before
# anything touches ultralytics.
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_OFFLINE", "true")

REPO = Path(__file__).resolve().parents[2]
MODELS = REPO / "models"


def sha256_head(path: Path, limit: int = 64 * 1024 * 1024) -> str:
    """Hash the first 64 MB. Enough to identify a file, fast on 343 MB checkpoints."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        h.update(fh.read(limit))
    return h.hexdigest()[:16]


def human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GB"


# --------------------------------------------------------------------------
# .pt  — ultralytics/torch checkpoints
# --------------------------------------------------------------------------


class _Stub:
    """Stand-in for a class we deliberately refuse to import.

    Auditing must never execute third-party model code or trigger a dependency
    install. Anything unimportable becomes one of these; pickle still restores
    the instance __dict__ onto it, which is where `names`, `yaml` and the other
    metadata we actually want are stored.
    """

    def __init__(self, *args, **kwargs):
        pass

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)

    def __setitem__(self, key, value):
        pass

    def append(self, value):
        pass


def _stub_pickle_module(record: dict):
    """A pickle-module shim for torch.load that stubs unimportable classes."""
    stubbed: set[str] = set()

    class StubUnpickler(pickle.Unpickler):
        def find_class(self, module, name):
            try:
                return super().find_class(module, name)
            except Exception:
                stubbed.add(f"{module}.{name}")
                return type(name, (_Stub,), {})

    class Shim:
        Unpickler = StubUnpickler
        UnpicklingError = pickle.UnpicklingError

        @staticmethod
        def load(f, **kwargs):
            return StubUnpickler(f, **kwargs).load()

        @staticmethod
        def loads(data, **kwargs):
            return StubUnpickler(io.BytesIO(data), **kwargs).load()

    return Shim, stubbed


def _load_checkpoint(path: Path, record: dict):
    """torch.load, falling back to stubbed unpickling if imports fail."""
    import torch

    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:
        record["load_fallback"] = (
            f"direct load failed ({type(exc).__name__}), retried with stubbed classes"
        )
        shim, stubbed = _stub_pickle_module(record)
        ckpt = torch.load(
            path, map_location="cpu", weights_only=False, pickle_module=shim
        )
        if stubbed:
            record["stubbed_classes"] = sorted(stubbed)[:12]
        return ckpt


def inspect_pt(path: Path) -> dict:
    out: dict = {"format": "pytorch"}
    ckpt = _load_checkpoint(path, out)

    if not isinstance(ckpt, dict):
        out["note"] = f"checkpoint is a bare {type(ckpt).__name__}, not a dict"
        return out

    out["checkpoint_keys"] = sorted(k for k in ckpt if not k.startswith("_"))

    model = ckpt.get("model")
    names = getattr(model, "names", None) or ckpt.get("names")
    if isinstance(names, dict):
        names = [names[k] for k in sorted(names)]
    if names:
        out["num_classes"] = len(names)
        out["classes"] = list(names)

    for key in ("date", "version", "license", "docs", "task"):
        if ckpt.get(key):
            out[key] = str(ckpt[key])

    args = ckpt.get("train_args") or ckpt.get("args") or {}
    if isinstance(args, dict) and args:
        keep = ("data", "epochs", "imgsz", "batch", "model", "task", "mode", "device")
        picked = {k: args[k] for k in keep if args.get(k) is not None}
        if picked:
            out["train_args"] = {k: str(v) for k, v in picked.items()}

    metrics = ckpt.get("train_metrics") or {}
    if isinstance(metrics, dict) and metrics:
        out["train_metrics"] = {
            k: round(float(v), 4)
            for k, v in metrics.items()
            if isinstance(v, (int, float))
        }

    if model is not None:
        try:
            out["parameters"] = sum(p.numel() for p in model.parameters())
        except Exception:
            pass
        out["architecture"] = type(model).__name__

        # YOLO-World keeps its prompt vocabulary as a text-embedding buffer.
        # If the class list is not the stock COCO 80, the prompts were customised.
        for attr in ("txt_feats", "text_feats", "clip_model"):
            if hasattr(model, attr):
                val = getattr(model, attr)
                shape = getattr(val, "shape", None)
                out.setdefault("open_vocab", {})[attr] = (
                    str(tuple(shape)) if shape is not None else type(val).__name__
                )

    return out


# --------------------------------------------------------------------------
# .onnx — read the graph metadata without onnxruntime
# --------------------------------------------------------------------------

def inspect_onnx(path: Path) -> dict:
    out: dict = {"format": "onnx"}
    try:
        import onnx
    except ImportError:
        out["note"] = "onnx package not installed; header not parsed"
        return out

    model = onnx.load(str(path), load_external_data=False)
    out["ir_version"] = model.ir_version
    out["producer"] = f"{model.producer_name} {model.producer_version}".strip()
    if model.opset_import:
        out["opset"] = max(o.version for o in model.opset_import)

    meta = {p.key: p.value for p in model.metadata_props}
    if meta:
        out["metadata"] = meta
        # ultralytics stores its class map here as a stringified dict
        if "names" in meta:
            try:
                import ast

                names = ast.literal_eval(meta["names"])
                if isinstance(names, dict):
                    out["num_classes"] = len(names)
                    out["classes"] = [names[k] for k in sorted(names)]
            except Exception:
                pass

    def shape_of(t) -> list:
        return [
            d.dim_value if d.HasField("dim_value") else (d.dim_param or "?")
            for d in t.type.tensor_type.shape.dim
        ]

    out["inputs"] = {t.name: shape_of(t) for t in model.graph.input}
    out["outputs"] = {t.name: shape_of(t) for t in model.graph.output}
    return out


# --------------------------------------------------------------------------
# .engine — TensorRT serialised plan
# --------------------------------------------------------------------------

def inspect_engine(path: Path) -> dict:
    """Ultralytics prefixes its engines with a JSON metadata block:
    [4-byte little-endian length][utf-8 JSON][raw TensorRT plan]
    That block records the build config, which is otherwise unrecoverable.
    """
    out: dict = {"format": "tensorrt"}
    with path.open("rb") as fh:
        head = fh.read(4)
        if len(head) < 4:
            out["note"] = "file too short"
            return out
        (meta_len,) = struct.unpack("<I", head)
        if 0 < meta_len < 100_000:
            try:
                meta = json.loads(fh.read(meta_len).decode("utf-8"))
                out["build_metadata"] = {
                    k: v for k, v in meta.items() if k != "names"
                }
                names = meta.get("names")
                if isinstance(names, dict):
                    out["num_classes"] = len(names)
                    out["classes"] = [names[k] for k in sorted(names, key=str)]
            except Exception as exc:
                out["note"] = f"metadata block unreadable: {exc}"
        else:
            out["note"] = "no ultralytics metadata header (raw TensorRT plan)"

    out["portability_warning"] = (
        "TensorRT plans are locked to the GPU architecture and TensorRT version "
        "that built them. This will not load on the target workstation - rebuild "
        "from the .pt there."
    )
    return out


# --------------------------------------------------------------------------
# .pth — plain torch state dict (OSNet re-ID)
# --------------------------------------------------------------------------

def inspect_pth(path: Path) -> dict:
    out: dict = {"format": "pytorch-state-dict"}
    ckpt = _load_checkpoint(path, out)
    state = ckpt.get("state_dict", ckpt) if isinstance(ckpt, dict) else ckpt

    if isinstance(ckpt, dict):
        out["checkpoint_keys"] = sorted(k for k in ckpt if k != "state_dict")
        if "epoch" in ckpt:
            out["epoch"] = ckpt["epoch"]

    if hasattr(state, "items"):
        keys = list(state.keys())
        out["num_tensors"] = len(keys)
        out["first_tensors"] = keys[:5]
        out["last_tensors"] = keys[-5:]
        try:
            out["parameters"] = sum(v.numel() for v in state.values() if hasattr(v, "numel"))
        except Exception:
            pass
        # The classifier head width tells you which dataset it was trained on.
        for k in keys:
            if "classifier" in k and k.endswith("weight"):
                out["classifier_shape"] = str(tuple(state[k].shape))
                break
    return out


DISPATCH = {
    ".pt": inspect_pt,
    ".onnx": inspect_onnx,
    ".engine": inspect_engine,
    ".pth": inspect_pth,
}


def to_yaml(data: dict, indent: int = 0) -> str:
    """Minimal YAML writer - avoids a pyyaml dependency for this one script."""
    pad = "  " * indent
    lines = []
    for key, val in data.items():
        if isinstance(val, dict):
            if not val:
                lines.append(f"{pad}{key}: {{}}")
                continue
            lines.append(f"{pad}{key}:")
            lines.append(to_yaml(val, indent + 1))
        elif isinstance(val, list):
            if not val:
                lines.append(f"{pad}{key}: []")
                continue
            lines.append(f"{pad}{key}:")
            for item in val:
                lines.append(f"{pad}  - {json.dumps(item) if isinstance(item, str) else item}")
        elif isinstance(val, str) and ("\n" in val or ": " in val or val.startswith(" ")):
            lines.append(f"{pad}{key}: {json.dumps(val)}")
        else:
            lines.append(f"{pad}{key}: {val}")
    return "\n".join(lines)


def main() -> int:
    if not MODELS.is_dir():
        print(f"no models directory at {MODELS}", file=sys.stderr)
        return 1

    files = sorted(
        (p for p in MODELS.iterdir() if p.suffix in DISPATCH),
        key=lambda p: (p.suffix, p.name),
    )
    print(f"auditing {len(files)} weight files in {MODELS}\n")

    results = []
    for path in files:
        size = path.stat().st_size
        print(f"  {path.name} ({human(size)}) ... ", end="", flush=True)
        record = {
            "file": path.name,
            "size_bytes": size,
            "size_human": human(size),
            "modified": datetime.fromtimestamp(
                path.stat().st_mtime, timezone.utc
            ).isoformat(timespec="seconds"),
            "sha256_head": sha256_head(path),
        }
        try:
            record.update(DISPATCH[path.suffix](path))
            print("ok")
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            print(f"FAILED ({type(exc).__name__})")
        results.append(record)

        sidecar = MODELS / f"{path.stem}{path.suffix.replace('.', '_')}.yaml"
        header = (
            "# Generated by engine/tools/audit_models.py - do not hand-edit.\n"
            "# Regenerate after adding or replacing a weight file.\n"
        )
        sidecar.write_text(header + to_yaml(record) + "\n", encoding="utf-8")

    write_inventory(results)
    print(f"\nwrote {MODELS / 'MODELS.md'} and {len(results)} sidecar yaml files")
    return 0


def write_inventory(results: list[dict]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    total = sum(r["size_bytes"] for r in results)

    md = [
        "# Model inventory",
        "",
        f"Generated {now} by `engine/tools/audit_models.py`. Do not hand-edit — "
        "regenerate after adding or replacing a weight file.",
        "",
        f"{len(results)} files, {human(total)} total.",
        "",
        "## Summary",
        "",
        "| File | Size | Format | Classes | Notes |",
        "|---|---|---|---|---|",
    ]

    for r in results:
        classes = r.get("num_classes", "—")
        note = r.get("error") or r.get("note") or ""
        if r.get("format") == "tensorrt" and not note:
            note = "GPU/TRT-locked — rebuild on target"
        md.append(
            f"| `{r['file']}` | {r['size_human']} | {r.get('format', '?')} "
            f"| {classes} | {note} |"
        )

    md += ["", "## Detail", ""]
    for r in results:
        md += [f"### `{r['file']}`", ""]
        md += [f"- **size** {r['size_human']} ({r['size_bytes']:,} bytes)"]
        md += [f"- **modified** {r['modified']}"]
        md += [f"- **sha256 (first 64 MB)** `{r['sha256_head']}`"]
        for key in ("format", "architecture", "parameters", "task", "date", "version"):
            if r.get(key) is not None:
                val = f"{r[key]:,}" if key == "parameters" else r[key]
                md.append(f"- **{key}** {val}")
        if r.get("train_args"):
            md.append(f"- **train args** `{r['train_args']}`")
        if r.get("train_metrics"):
            md.append(f"- **train metrics** `{r['train_metrics']}`")
        if r.get("build_metadata"):
            md.append(f"- **build metadata** `{r['build_metadata']}`")
        if r.get("open_vocab"):
            md.append(f"- **open-vocab buffers** `{r['open_vocab']}`")
        if r.get("inputs"):
            md.append(f"- **inputs** `{r['inputs']}`")
        if r.get("outputs"):
            md.append(f"- **outputs** `{r['outputs']}`")
        if r.get("classifier_shape"):
            md.append(f"- **classifier head** `{r['classifier_shape']}`")
        if r.get("error"):
            md.append(f"- **ERROR** {r['error']}")
        if r.get("note"):
            md.append(f"- **note** {r['note']}")

        if r.get("classes"):
            names = r["classes"]
            md += ["", f"<details><summary>{len(names)} classes</summary>", ""]
            md += ["```", ", ".join(str(n) for n in names), "```", "", "</details>"]
        md.append("")

    (MODELS / "MODELS.md").write_text("\n".join(md), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
