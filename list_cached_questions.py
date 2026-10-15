"""
list_cached_questions.py
------------------------
Lists all vectors (cached questions) stored in the S3 Vector index.
Each vector's metadata contains the original question text and cached answer.

Run:  python list_cached_questions.py
"""

import boto3
import json
import os
from pathlib import Path

# Load credentials from .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

REGION      = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
BUCKET_NAME = "semantic-cache-app"
INDEX_NAME  = "cache-index"

def main():
    client = boto3.client("s3vectors", region_name=REGION)

    print(f"\n{'='*70}")
    print(f"  S3 Vector Index: {BUCKET_NAME} / {INDEX_NAME}")
    print(f"{'='*70}\n")

    try:
        paginator = client.get_paginator("list_vectors")
        pages = paginator.paginate(
            vectorBucketName=BUCKET_NAME,
            indexName=INDEX_NAME,
            returnData=False,       # we only need metadata, not raw float vectors
            returnMetadata=True,
        )

        total = 0
        for page in pages:
            for vec in page.get("vectors", []):
                total += 1
                key      = vec.get("key", "N/A")
                metadata = vec.get("metadata", {})
                question = metadata.get("question", metadata.get("prompt", "<no question stored>"))
                answer   = metadata.get("answer",   metadata.get("response", "<no answer stored>"))

                # Truncate long answers for display
                answer_preview = (answer[:120] + "...") if len(answer) > 120 else answer

                print(f"  [{total:>3}]  Key     : {key}")
                print(f"        Question: {question}")
                print(f"        Answer  : {answer_preview}")
                print()

        if total == 0:
            print("  No vectors found in the index.")
            print("  The cache is empty - no questions have been asked and cached yet.")
        else:
            print(f"{'='*70}")
            print(f"  Total cached entries: {total}")
            print(f"{'='*70}\n")

    except client.exceptions.NotFoundException:
        print(f"  Index '{INDEX_NAME}' not found in bucket '{BUCKET_NAME}'.")
        print("  Run: python create_s3_vectors.py  to provision it first.")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    main()
