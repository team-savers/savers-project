"""Backend image keeps the optional real-send dependency installed."""

from pathlib import Path


def test_backend_dockerfile_installs_fcm_extra() -> None:
    dockerfile = Path(__file__).parents[1] / "Dockerfile"

    assert 'pip install --no-cache-dir ".[fcm]"' in dockerfile.read_text(encoding="utf-8")
