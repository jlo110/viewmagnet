"""Off-machine backup of the irreplaceable ML artifacts to Cloudflare R2.

The trained model artifacts + the surviving feature/label caches are gitignored
and (until this script runs) exist on exactly one machine. A disk failure = the
product's models are gone for good (the historical training data is already lost;
see memory/ml-data-disconnected.md). This tars the critical set and uploads it to
R2 under a date-stamped key so there's a durable off-machine copy.

What's backed up (the genuinely irreplaceable set, ~204MB):
    models/                         trained velocity + legacy joblib artifacts
    data/models/                    served .pkl predictors (clean/lean/reach)
    data/cache/exp_features.pkl     144k content-classifier feature cache
    data/reach/                     40k-row reach dataset + labels + raw.json

NOT backed up: data/thumbnails/ (646MB, re-fetchable / already archived to R2).
Add paths to CRITICAL_PATHS if that changes.

Usage:
    python -m scripts.backup_ml_artifacts                 # backup to default bucket
    python -m scripts.backup_ml_artifacts --dry-run       # tar + size only, no upload
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

CRITICAL_PATHS = [
    "models",
    "data/models",
    "data/cache/exp_features.pkl",
    "data/reach",
]

R2_PREFIX = "ml-artifact-backups"


def build_archive(dest: Path) -> Path:
    """Tar.gz the critical set into ``dest``; skip paths that don't exist."""
    included, missing = [], []
    with tarfile.open(dest, "w:gz") as tar:
        for rel in CRITICAL_PATHS:
            src = REPO_ROOT / rel
            if src.exists():
                tar.add(src, arcname=rel)
                included.append(rel)
            else:
                missing.append(rel)
    print(f"  archived: {', '.join(included)}")
    if missing:
        print(f"  skipped (not found): {', '.join(missing)}")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build the archive but don't upload")
    ap.add_argument("--bucket", default=None, help="override R2 bucket (default: $R2_BUCKET_NAME)")
    args = ap.parse_args()

    load_dotenv(REPO_ROOT / ".env")

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    archive_name = f"ml-artifacts-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = Path(tmp) / archive_name
        print(f"Building archive {archive_name} ...")
        build_archive(archive_path)
        size_mb = archive_path.stat().st_size / 1e6
        print(f"  archive size: {size_mb:.1f} MB")

        if args.dry_run:
            print("--dry-run: skipping upload.")
            return 0

        acct = os.getenv("R2_ACCOUNT_ID")
        ak = os.getenv("R2_ACCESS_KEY_ID")
        sk = os.getenv("R2_SECRET_ACCESS_KEY")
        bucket = args.bucket or os.getenv("R2_BUCKET_NAME")
        if not all([acct, ak, sk, bucket]):
            print("ERROR: R2 credentials/bucket not configured in .env", file=sys.stderr)
            return 1

        client = boto3.client(
            "s3",
            endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
            aws_access_key_id=ak,
            aws_secret_access_key=sk,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        key = f"{R2_PREFIX}/{stamp}/{archive_name}"
        print(f"Uploading to r2://{bucket}/{key} ...")
        client.upload_file(str(archive_path), bucket, key)

        head = client.head_object(Bucket=bucket, Key=key)
        remote_mb = head["ContentLength"] / 1e6
        print(f"  uploaded OK: {remote_mb:.1f} MB at r2://{bucket}/{key}")
        if abs(remote_mb - size_mb) > 1.0:
            print("  WARNING: remote size differs from local archive", file=sys.stderr)
            return 1

    print("Backup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
