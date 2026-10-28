"""Fetch ML model artifacts from R2 at container startup (plan 8.9).

The Docker image ships only ``src/`` — every model artifact (content
classifier, velocity models, breakout calibrators, reach predictor) is
gitignored and, before this, existed only on one laptop + the R2 backups.
Production ``/health`` showed ``model_loaded: false`` and all "AI analysis"
silently ran on fallbacks.

This pulls the pinned backup tarball (the same artifact
``scripts/backup_ml_artifacts.py`` produces — backup and delivery are one
artifact) and extracts ``models/`` + ``data/models/`` + the caches when
they're missing. Best-effort by design: any failure logs and exits 0 so a
fetch problem can never block startup (the app already degrades gracefully).

Env:
  ML_ARTIFACTS_VERSION  date pin, e.g. ``2026-06-12`` (no pin = skip fetch —
                        deploys stay reproducible; promotion = bump the pin)
  R2_* credentials      same as the rest of the app

Usage: python -m scripts.fetch_ml_artifacts   (called by docker_entrypoint.sh)
"""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
R2_PREFIX = "ml-artifact-backups"

# If this exists, artifacts are present and the fetch is skipped (cheap probe —
# the registry's primary live model).
SENTINEL = REPO_ROOT / "data" / "models" / "clean_predictor.pkl"


def should_fetch(version: str | None, sentinel: Path = SENTINEL) -> bool:
    """Fetch only when a version is pinned and artifacts are absent."""
    return bool(version) and not sentinel.exists()


def safe_extract(tar_path: Path, dest: Path) -> int:
    """Extract the tarball, refusing path-traversal members. Returns count."""
    n = 0
    with tarfile.open(tar_path, "r:gz") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest.resolve())):
                continue  # path traversal — skip
            tar.extract(member, dest)
            n += 1
    return n


def main() -> int:
    version = os.getenv("ML_ARTIFACTS_VERSION")
    if not should_fetch(version):
        print(f"[ml-artifacts] skip (version={version!r}, present={SENTINEL.exists()})")
        return 0

    acct = os.getenv("R2_ACCOUNT_ID")
    ak = os.getenv("R2_ACCESS_KEY_ID")
    sk = os.getenv("R2_SECRET_ACCESS_KEY")
    bucket = os.getenv("R2_BUCKET_NAME")
    if not all([acct, ak, sk, bucket]):
        print("[ml-artifacts] R2 credentials missing - skipping (app will run degraded)")
        return 0

    key = f"{R2_PREFIX}/{version}/ml-artifacts-{version}.tar.gz"
    try:
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
        )
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        print(f"[ml-artifacts] downloading r2://{bucket}/{key} ...")
        client.download_file(bucket, key, str(tmp_path))
        n = safe_extract(tmp_path, REPO_ROOT)
        tmp_path.unlink(missing_ok=True)
        print(f"[ml-artifacts] extracted {n} members; model present: {SENTINEL.exists()}")
    except Exception as e:  # never block startup on artifact problems
        print(f"[ml-artifacts] WARNING: fetch failed ({e}); app will run degraded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
