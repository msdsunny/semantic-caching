"""
setup_all.py
------------
One-command provisioner that runs the full stack in order:

  Step 1 -> create_s3_vectors.py  (S3 Vector Bucket + Index)
  Step 2 -> create_lambda.py      (IAM Role + Lambda Function)
  Step 3 -> create_api.py         (HTTP API + Route + Permission)
  Step 4 -> Runs Flask server (app.py)

When you press Ctrl+C to stop the server, it AUTOMATICALLY tears down all AWS resources!

Run:      python setup_all.py
No-Serve: python setup_all.py --no-serve
Teardown: python setup_all.py --delete
"""

import argparse
import sys
import subprocess
from pathlib import Path

# ---------------------------------------------------------------------------
# Import the three provisioner modules directly so we get proper tracebacks
# ---------------------------------------------------------------------------
import importlib.util


def _load(name: str):
    """Load a sibling .py file as a module without running __main__ block."""
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_create():
    print("=" * 60)
    print("  SEMANTIC CACHING STACK - FULL SETUP")
    print("=" * 60)

    # ---- Step 1: S3 Vectors ------------------------------------------------
    print("\n[STEP 1/3] S3 Vector Bucket & Index")
    s3v = _load("create_s3_vectors")
    s3v.create()

    # ---- Step 2: Lambda ----------------------------------------------------
    print("\n[STEP 2/3] IAM Role & Lambda Function")
    lmb = _load("create_lambda")
    lmb.create()

    # ---- Step 3: API Gateway -----------------------------------------------
    print("\n[STEP 3/3] HTTP API Gateway")
    api = _load("create_api")
    api.create()

    print("=" * 60)
    print("  ALL DONE!  Full stack is live.")
    print("=" * 60)
    print()


def run_delete():
    print("=" * 60)
    print("  SEMANTIC CACHING STACK - FULL TEARDOWN")
    print("=" * 60)

    # Delete in reverse order: API -> Lambda -> S3 Vectors

    print("\n[STEP 1/3] Delete HTTP API Gateway")
    api = _load("create_api")
    api.delete()

    print("\n[STEP 2/3] Delete Lambda Function & IAM Role")
    lmb = _load("create_lambda")
    lmb.delete()

    print("\n[STEP 3/3] Delete S3 Vector Index & Bucket")
    s3v = _load("create_s3_vectors")
    s3v.delete()

    print("=" * 60)
    print("  TEARDOWN COMPLETE.  All AWS resources removed.")
    print("=" * 60)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Provision, run, and auto-teardown the full semantic caching stack"
    )
    parser.add_argument(
        "--delete", action="store_true",
        help="Tear down all AWS resources instead of creating them"
    )
    parser.add_argument(
        "--no-serve", action="store_true",
        help="Provision resources without starting the Flask server"
    )
    args = parser.parse_args()

    if args.delete:
        run_delete()
    else:
        run_create()
        if not args.no_serve:
            print("=" * 60)
            print("  STARTING FLASK SERVER")
            print("  Open in browser: http://localhost:5000")
            print("  Press Ctrl+C to stop server & AUTO-TEARDOWN AWS resources")
            print("=" * 60)
            print()
            try:
                subprocess.run([sys.executable, "app.py"], cwd=Path(__file__).parent)
            except KeyboardInterrupt:
                print("\n\n" + "=" * 60)
                print("  CTRL+C DETECTED! Initiating automatic AWS teardown...")
                print("=" * 60)
            finally:
                run_delete()
