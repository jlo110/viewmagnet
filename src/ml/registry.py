"""Model registry loader (Phase 3.4 / 6.8) — the single source of truth for
which ML artifact is live per task, with honest provenance.

Reads ``model_registry.json`` (committed alongside this module) so code can
resolve artifacts by *task name* instead of hardcoding `.joblib`/`.pkl` paths,
and so there's one durable record of what exists even though the artifacts
themselves are gitignored and local-only.

    from src.ml.registry import resolve_artifact, get_entry, live_models
    path = resolve_artifact("content_classifier")   # -> data/models/clean_predictor.pkl
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).with_name("model_registry.json")
_REPO_ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def load_registry() -> dict[str, Any]:
    """Parse and cache the registry JSON."""
    return json.loads(_REGISTRY_PATH.read_text())


def models() -> dict[str, Any]:
    """All registered entries keyed by task name."""
    return load_registry()["models"]


def get_entry(name: str) -> dict[str, Any]:
    """Return one registry entry. Raises KeyError for an unknown task."""
    try:
        return models()[name]
    except KeyError as e:
        raise KeyError(
            f"Unknown model '{name}'. Known: {sorted(models())}"
        ) from e


def resolve_artifact(name: str) -> Path:
    """Absolute path to a task's primary artifact (relative entries are resolved
    against the repo root). Does not check existence — use artifact_exists."""
    rel = get_entry(name).get("artifact")
    if not rel:
        raise ValueError(f"Model '{name}' has no 'artifact' path.")
    return (_REPO_ROOT / rel).resolve()


def artifact_exists(name: str) -> bool:
    """True if the task's artifact file is present on this machine."""
    try:
        return resolve_artifact(name).exists()
    except (KeyError, ValueError):
        return False


def live_models() -> dict[str, Any]:
    """Entries currently served by the API (status == 'live')."""
    return {k: v for k, v in models().items() if v.get("status") == "live"}


def load_model(name: str) -> Any:
    """Load a task's artifact by extension (.joblib -> joblib, .pkl -> pickle)."""
    path = resolve_artifact(name)
    if not path.exists():
        raise FileNotFoundError(f"Artifact for '{name}' not found at {path}")
    if path.suffix == ".joblib":
        import joblib

        return joblib.load(path)
    import pickle

    with open(path, "rb") as f:
        return pickle.load(f)
