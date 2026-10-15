"""Dataset loaders and annotation parsing (train/datasets.py)."""

import numpy as np
import pytest

from core.features import FALLEN, FALLING, NORMAL, UNKNOWN
from train.datasets import (
    LOADERS, VideoRecord, load_dataset, parse_le2i_annotation, parse_urfd_csv, register_loader,
    runs_to_segments,
)


def touch(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def le2i_root(tmp_path):
    scene = tmp_path / "Coffee_room_01" / "Coffee_room_01"    # the doubly nested download layout
    touch(scene / "Videos" / "video (1).avi")
    touch(scene / "Annotation_files" / "video (1).txt", "48\n80\n1,1,10,20,30,40\n2,1,10,20,30,40\n")
    touch(scene / "Videos" / "video (2).avi")
    touch(scene / "Annotation_files" / "video (2).txt", "0\n0\n")
    home = tmp_path / "Home_01"
    touch(home / "Videos" / "video (5).avi")
    touch(home / "Annotations_files" / "video (5).txt", "10\n20\n")
    touch(home / "Videos" / "video (6).avi")                      # no annotation -> skipped
    touch(home / "Videos" / "video (7).avi")
    touch(home / "Annotations_files" / "video (7).txt", "1,1,10,20,30,40\n")   # no header -> skipped
    return tmp_path


def test_le2i_annotation_header(tmp_path):
    assert parse_le2i_annotation(touch(tmp_path / "a.txt", "48\n80\n1,1,2,3,4,5\n")) == (48, 80)
    assert parse_le2i_annotation(touch(tmp_path / "b.txt", "0\n0\n")) == (0, 0)
    assert parse_le2i_annotation(touch(tmp_path / "c.txt", "1,1,2,3,4,5\n")) is None
    assert parse_le2i_annotation(touch(tmp_path / "d.txt", "")) is None


def test_le2i_loader_labels_and_groups(le2i_root):
    records = {r.video_id: r for r in load_dataset("le2i", le2i_root)}
    assert set(records) == {"le2i/Coffee_room_01/video (1)", "le2i/Coffee_room_01/video (2)",
                            "le2i/Home_01/video (5)"}
    fall = records["le2i/Coffee_room_01/video (1)"]
    labels = fall.labels_for(100)
    # 1-based frames 48..80 falling -> 0-based 47..79
    assert (labels[:47] == NORMAL).all()
    assert (labels[47:80] == FALLING).all()
    assert (labels[80:] == FALLEN).all()
    assert fall.has_fall and fall.group_id == fall.video_id

    no_fall = records["le2i/Coffee_room_01/video (2)"]
    assert (no_fall.labels_for(50) == NORMAL).all() and not no_fall.has_fall


def test_le2i_group_by_scene(le2i_root):
    groups = {r.group_id for r in load_dataset("le2i", le2i_root, group_by="scene")}
    assert groups == {"le2i/Coffee_room_01", "le2i/Home_01"}


@pytest.fixture
def urfd_root(tmp_path):
    rows = ["fall-01,1,-1,0.1", "fall-01,2,-1,0.1", "fall-01,3,0,0.1", "fall-01,4,1,0.1", "fall-01,5,1,0.1",
            "fall-02,1,-1,0.1", "fall-02,2,1,0.1", "adl-01,1,1,0.1"]
    touch(tmp_path / "urfall-cam0-falls.csv", "\n".join(rows) + "\n")
    for name in ("fall-01-cam0-rgb", "fall-01-cam1-rgb", "adl-01-cam0-rgb", "fall-01-cam0-d"):
        touch(tmp_path / name / f"{name}-001.png")
    touch(tmp_path / "videos" / "fall-02-cam0.mp4")
    touch(tmp_path / "videos" / "fall-01-cam0.mp4")              # rgb folder wins for fall-01
    touch(tmp_path / "videos" / "fall-03-cam0.mp4")              # unlabelled -> skipped
    return tmp_path


def test_urfd_csv(urfd_root):
    labels = parse_urfd_csv(urfd_root / "urfall-cam0-falls.csv")
    assert labels[("fall", 1)] == {0: NORMAL, 1: NORMAL, 2: FALLING, 3: FALLEN, 4: FALLEN}


def test_urfd_loader(urfd_root):
    records = {r.video_id: r for r in load_dataset("urfd", urfd_root)}
    assert set(records) == {"urfd/fall-01-cam0", "urfd/fall-02-cam0", "urfd/adl-01-cam0"}
    fall = records["urfd/fall-01-cam0"]
    assert fall.source.is_dir() and fall.source.name == "fall-01-cam0-rgb"
    np.testing.assert_array_equal(fall.labels_for(7), [NORMAL, NORMAL, FALLING, FALLEN, FALLEN,
                                                       UNKNOWN, UNKNOWN])
    # ADL lying (label 1 in the CSV) is not a fall
    assert (records["urfd/adl-01-cam0"].labels_for(5) == NORMAL).all()
    assert records["urfd/fall-02-cam0"].source.suffix == ".mp4"
    # The .mp4 previews are depth | RGB side by side; image folders are RGB only.
    assert records["urfd/fall-02-cam0"].crop == "right_half" and fall.crop is None


def test_urfd_cameras_share_a_group(urfd_root):
    records = {r.video_id: r for r in load_dataset("urfd", urfd_root, cams=[0, 1])}
    assert records["urfd/fall-01-cam0"].group_id == records["urfd/fall-01-cam1"].group_id == "urfd/fall-01"


def test_manifest_loader(tmp_path):
    touch(tmp_path / "manifest.csv", "video,group,fall_start,fall_end\n"
                                     "a.mp4,subj1,10,19\nb.mp4,subj1,,\nc.mp4,,-1,-1\n")
    records = {r.video_id: r for r in load_dataset("manifest", tmp_path)}
    a = records["manifest/a.mp4"].labels_for(25)
    assert (a[:10] == NORMAL).all() and (a[10:20] == FALLING).all() and (a[20:] == FALLEN).all()
    assert records["manifest/b.mp4"].group_id == "subj1"
    assert not records["manifest/c.mp4"].has_fall
    assert records["manifest/c.mp4"].group_id == "manifest/c.mp4"


def test_custom_loader_registration(tmp_path):
    @register_loader("toy")
    def load_toy(root, n=2):
        return [VideoRecord("toy", f"toy/{i}", f"toy/{i}", root / f"{i}.mp4") for i in range(n)]
    try:
        assert [r.video_id for r in load_dataset("toy", tmp_path, n=3)] == ["toy/0", "toy/1", "toy/2"]
    finally:
        del LOADERS["toy"]
    with pytest.raises(ValueError):
        load_dataset("nope", tmp_path)


def test_runs_to_segments():
    assert runs_to_segments({0: 0, 1: 0, 2: 1, 4: 1}) == [(0, 1, 0), (2, 2, 1), (4, 4, 1)]
