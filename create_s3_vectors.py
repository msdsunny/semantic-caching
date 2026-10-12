"""
create_s3_vectors.py
--------------------
Programmatically provisions the S3 Vectors resources:

  1. Creates the S3 Vector Bucket  (semantic-cache-app)
  2. Creates the Vector Index      (cache-index, 1024 dims, Cosine metric)

Run:  python create_s3_vectors.py
Undo: python create_s3_vectors.py --delete
"""

import argparse
import boto3
import os
import time
from pathlib import Path
from botocore.exceptions import ClientError

# Load credentials from .env if present
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=True)
        print(f"  [ENV]   Loaded credentials from {_env_path}")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REGION      = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET_NAME = "semantic-cache-app"
INDEX_NAME  = "cache-index"
DIMENSION   = 1024          # Amazon Titan Embed Text v2 output size
METRIC      = "cosine"      # cosine distance for semantic similarity

TAGS = {
    "OK":   "[OK]   ",
    "SKIP": "[SKIP] ",
    "WAIT": "[WAIT] ",
    "DEL":  "[DEL]  ",
    "ERR":  "[ERROR]",
}


def log(tag, msg):
    label = TAGS.get(tag.upper(), f"[{tag}]")
    print(f"  {label}  {msg}")


# ---------------------------------------------------------------------------
# S3 Vector Bucket
# ---------------------------------------------------------------------------

def create_bucket(client):
    """Create the S3 Vector Bucket; skip if it already exists."""
    try:
        client.create_vector_bucket(vectorBucketName=BUCKET_NAME)
        log("OK", f"Vector bucket created: {BUCKET_NAME}")
    except client.exceptions.ConflictException:
        log("SKIP", f"Vector bucket already exists: {BUCKET_NAME}")


def create_index(client):
    """Create the Vector Index inside the bucket."""
    try:
        client.create_index(
            vectorBucketName=BUCKET_NAME,
            indexName=INDEX_NAME,
            dataType="float32",
            dimension=DIMENSION,
            distanceMetric=METRIC
        )
        log("OK", f"Vector index created: {INDEX_NAME}  "
                  f"(dim={DIMENSION}, metric={METRIC})")
    except client.exceptions.ConflictException:
            log("SKIP", f"Vector index already exists: {INDEX_NAME}")


def delete_index(client):
    try:
        client.delete_index(
            vectorBucketName=BUCKET_NAME,
            indexName=INDEX_NAME
        )
        log("DEL", f"Vector index deleted: {INDEX_NAME}")
    except client.exceptions.NotFoundException:
            log("SKIP", f"Vector index '{INDEX_NAME}' not found, skipping")


def delete_bucket(client):
    try:
        client.delete_vector_bucket(vectorBucketName=BUCKET_NAME)
        log("DEL", f"Vector bucket deleted: {BUCKET_NAME}")
    except client.exceptions.NotFoundException:
        log("SKIP", f"Vector bucket '{BUCKET_NAME}' not found, skipping")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def create():
    print("\n>>> Provisioning S3 Vector resources")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    client = session.client("s3vectors")

    create_bucket(client)

    # Brief pause: bucket must be fully ready before index creation
    log("WAIT", "Waiting 3 s for bucket to become available...")
    time.sleep(3)

    create_index(client)

    print("\n" + "-" * 52)
    print("[DONE] S3 Vector resources provisioned!\n")
    print(f"   Bucket : {BUCKET_NAME}")
    print(f"   Index  : {INDEX_NAME}  (dim={DIMENSION}, metric={METRIC})")
    print(f"   Region : {REGION}")
    print("\n   Next step -> run  python create_lambda.py\n")


def delete():
    print("\n[DELETE] Removing S3 Vector resources")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    client = session.client("s3vectors")

    delete_index(client)

    # Short pause between index and bucket deletion
    time.sleep(2)

    delete_bucket(client)

    print("\n[OK] S3 Vector cleanup complete.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create or delete S3 Vector Bucket and Index"
    )
    parser.add_argument(
        "--delete", action="store_true",
        help="Delete all provisioned resources instead of creating them"
    )
    args = parser.parse_args()

    if args.delete:
        delete()
    else:
        create()
