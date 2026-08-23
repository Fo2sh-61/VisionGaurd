"""Strip the CLIP text encoder out of a YOLO-World checkpoint.

A YOLO-World `.pt` saved straight from `set_classes()` still carries the CLIP
text encoder that turned the prompts into vectors. Loading such a file needs the
`clip` package installed, because the pickle references classes inside it - and
this project deliberately does not install anything at run time
(`YOLO_AUTOINSTALL=false`, see `vg/infer/bags.py`).

The encoder is not needed. `set_classes()` bakes the prompt vectors into
`txt_feats`, and inference reads those. So the encoder is 300 MB of weights that
exist only to make the file unloadable.

This tool loads the checkpoint once behind a stand-in `clip` module, drops the
encoder, and saves a clean file that loads with no stand-in and no dependency.
The owner's `bagbest.pt` had already had this done to it, which is why that one
loads and the search checkpoints do not.

Run it once per supplied checkpoint. The output is a build artifact of the input,
the same way a TensorRT engine is - the original stays the source of truth.

    python engine/tools/strip_clip.py "models/bag traker/models/yolov8m-worldv2-search-12ac1b92.pt" models/bagsearch.pt
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import types
from pathlib import Path

os.environ.setdefault("YOLO_AUTOINSTALL", "false")


def install_clip_stand_in() -> None:
    """Let the unpickler find `clip.*` without the package being installed.

    Every name it asks for comes back as an empty `nn.Module` subclass. Torch
    walks the model tree with `_apply` during load, so these have to be real
    modules rather than plain objects - and dunders have to be genuinely absent,
    because `inspect` reads `__file__` on the way past.
    """
    import torch.nn as nn

    class Absent(nn.Module):
        def __init__(self, *a, **k):
            super().__init__()

        def forward(self, *a, **k):
            raise RuntimeError("the CLIP text encoder was stripped")

    def stub(name: str) -> None:
        module = types.ModuleType(name)
        module.__path__ = []
        module.__file__ = f"<{name} stand-in>"

        def getattr_(attr: str, _n: str = name):
            if attr.startswith("__") and attr.endswith("__"):
                raise AttributeError(f"{_n} has no {attr}")
            return type(attr.lstrip("_") or "Absent", (Absent,), {})

        module.__getattr__ = getattr_
        sys.modules[name] = module

    for name in ("clip", "clip.model", "clip.clip", "clip.simple_tokenizer"):
        stub(name)


def strip(source: Path, target: Path) -> None:
    import torch
    from ultralytics import YOLO

    install_clip_stand_in()

    model = YOLO(str(source))
    inner = model.model
    print(f"  loaded   {type(inner).__name__}, task {model.task}")
    print(f"  classes  {inner.names}")
    feats = getattr(inner, "txt_feats", None)
    if feats is None:
        raise SystemExit(
            "this checkpoint has no baked `txt_feats`, so the prompts were "
            "never frozen into it and dropping the encoder would leave it "
            "unable to detect anything. Re-export it with set_classes() first."
        )
    print(f"  txt_feats {tuple(feats.shape)} - the prompts are baked in")

    dropped = []
    for attr in ("clip_model", "text_model", "txt_model"):
        if getattr(inner, attr, None) is not None:
            setattr(inner, attr, None)
            dropped.append(attr)
    for name, child in list(inner.named_children()):
        if "clip" in name.lower() or "text" in name.lower():
            setattr(inner, name, None)
            dropped.append(name)
    print(f"  dropped  {dropped or 'nothing (already clean)'}")

    target.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model": inner.half(), "date": None, "version": None}, target)
    size = target.stat().st_size / 1e6
    print(f"  wrote    {target} ({size:.0f} MB, was {source.stat().st_size / 1e6:.0f} MB)")


def verify(target: Path) -> int:
    """Load it in a fresh process with NO stand-in. That is the whole point."""
    code = (
        "import os;os.environ.setdefault('YOLO_AUTOINSTALL','false')\n"
        "from ultralytics import YOLO\n"
        f"m=YOLO(r'{target}')\n"
        "print('  names   ', m.names)\n"
        "import numpy as np\n"
        "r=m.predict(np.zeros((640,640,3),dtype=np.uint8),verbose=False)[0]\n"
        "print('  grey    ', len(r.boxes), 'boxes (expected 0)')\n"
    )
    print("\nverifying in a clean process, with no clip stand-in:")
    return subprocess.call([sys.executable, "-c", code])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)

    if not args.source.is_file():
        raise SystemExit(f"no such checkpoint: {args.source}")

    print(f"stripping {args.source}")
    strip(args.source, args.target)
    if verify(args.target) != 0:
        raise SystemExit("the stripped file still does not load on its own")
    print("\nok - it loads with no clip package present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
