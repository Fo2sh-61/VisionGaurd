import pytest


@pytest.fixture(autouse=True)
def no_installed_rule_calibration(monkeypatch, tmp_path):
    """Keep tests hermetic: ignore checkpoints/rule_based.json installed by train.compare."""
    import detectors.rule_based as rule_based
    monkeypatch.setattr(rule_based, "CALIBRATION", tmp_path / "no_rule_based.json")
