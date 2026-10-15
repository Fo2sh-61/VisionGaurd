"""Model architectures and checkpoint round trip (train/model.py)."""

import pytest
import torch

from core.features import FEATURE_VERSION, LABELS
from train.model import build_model, load_checkpoint, save_checkpoint


@pytest.mark.parametrize("arch,kwargs", [("cnn", {"channels": 16, "num_layers": 2}),
                                         ("lstm", {"hidden": 16, "num_layers": 2})])
def test_forward_shape(arch, kwargs):
    model = build_model(arch, **kwargs).eval()
    assert model(torch.randn(4, 30, 51)).shape == (4, len(LABELS))
    assert model(torch.randn(1, 45, 51)).shape == (1, len(LABELS))   # any window length
    assert sum(p.numel() for p in model.parameters()) < 200_000


def test_unknown_arch_and_even_kernel():
    with pytest.raises(ValueError):
        build_model("transformer")
    with pytest.raises(ValueError):
        build_model("cnn", kernel_size=4)


@pytest.mark.parametrize("arch", ["cnn", "lstm"])
def test_checkpoint_round_trip(tmp_path, arch):
    model = build_model(arch).eval()
    path = tmp_path / "m.pt"
    save_checkpoint(path, model, arch, {}, {"window": 30, "max_gap": 5, "conf_min": 0.3})
    loaded, meta = load_checkpoint(path)
    x = torch.randn(3, 30, 51)
    torch.testing.assert_close(loaded(x), model(x))
    assert meta["arch"] == arch and meta["feature_version"] == FEATURE_VERSION and "state_dict" not in meta


def test_checkpoint_from_other_feature_version_is_refused(tmp_path):
    path = tmp_path / "m.pt"
    save_checkpoint(path, build_model("cnn"), "cnn", {}, {"feature_version": FEATURE_VERSION + 1})
    with pytest.raises(ValueError, match="feature version"):
        load_checkpoint(path)
