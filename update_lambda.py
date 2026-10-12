"""
update_lambda.py
----------------
Quickly redeploys the Lambda function code and/or environment variables
without re-running the full setup. Use this after editing lambda_function.py
or tuning the SIMILARITY_THRESHOLD.

Usage:
  python update_lambda.py                     # redeploy code + env vars
  python update_lambda.py --threshold 0.80    # change threshold only (no redeploy)
"""

import argparse
import boto3
import io
import os
import time
import zipfile
from pathlib import Path
from botocore.exceptions import ClientError

try:
    from dotenv import load_dotenv
    _env = Path(__file__).parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=True)
except ImportError:
    pass

REGION        = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
FUNCTION_NAME = "semantic-cache-handler"
SOURCE_FILE   = "lambda_function.py"

TAGS = {
    "OK":   "[OK]   ",
    "SKIP": "[SKIP] ",
    "WAIT": "[WAIT] ",
    "PKG":  "[PKG]  ",
}

def log(tag, msg):
    print(f"  {TAGS.get(tag.upper(), '[?]')}  {msg}")


def zip_source() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(SOURCE_FILE, arcname="lambda_function.py")
    buf.seek(0)
    return buf.read()


def redeploy_code(lam):
    """Update function code from local lambda_function.py."""
    log("PKG", f"Zipping {SOURCE_FILE}...")
    zip_bytes = zip_source()
    log("OK", f"Zip ready ({len(zip_bytes):,} bytes)")

    lam.update_function_code(
        FunctionName=FUNCTION_NAME,
        ZipFile=zip_bytes
    )
    log("OK", "Function code updated")

    log("WAIT", "Waiting for update to complete...")
    waiter = lam.get_waiter("function_updated_v2")
    waiter.wait(FunctionName=FUNCTION_NAME)
    log("OK", "Code update complete")


def update_env(lam, threshold: float):
    """Update SIMILARITY_THRESHOLD env var on the deployed function."""
    # Fetch current env vars so we don't wipe existing ones
    cfg = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
    current_env = cfg.get("Environment", {}).get("Variables", {})

    current_env["SIMILARITY_THRESHOLD"] = str(threshold)

    lam.update_function_configuration(
        FunctionName=FUNCTION_NAME,
        Environment={"Variables": current_env}
    )
    log("OK", f"SIMILARITY_THRESHOLD set to {threshold} "
              f"(distance <= {1.0 - threshold:.2f})")

    log("WAIT", "Waiting for config update to complete...")
    waiter = lam.get_waiter("function_updated_v2")
    waiter.wait(FunctionName=FUNCTION_NAME)
    log("OK", "Config update complete")


def main():
    parser = argparse.ArgumentParser(
        description="Redeploy Lambda code and/or update the similarity threshold"
    )
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="Override SIMILARITY_THRESHOLD (0.0-1.0). Default: use value in lambda_function.py"
    )
    parser.add_argument(
        "--env-only", action="store_true",
        help="Only update the env var, skip code redeployment"
    )
    args = parser.parse_args()

    # Determine effective threshold
    if args.threshold is not None:
        threshold = args.threshold
    else:
        # Read from source file default
        threshold = 0.75

    print(f"\n>>> Updating Lambda: {FUNCTION_NAME}")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    lam = session.client("lambda")

    if not args.env_only:
        redeploy_code(lam)
        # Small gap between code and config updates to avoid conflicts
        time.sleep(2)

    update_env(lam, threshold)

    print("\n" + "-" * 52)
    print("[DONE] Lambda updated!\n")
    print(f"   Threshold : {threshold} (similarity >= {threshold*100:.0f}%)")
    print(f"   Max dist  : {1.0 - threshold:.2f}  (lower = stricter)")
    print()
    print("   Threshold guide:")
    print("     0.90 -> >= 90% similar  (near-identical phrasing)")
    print("     0.80 -> >= 80% similar  (same meaning, varied words)")
    print("     0.75 -> >= 75% similar  (paraphrases)          <-- current")
    print("     0.65 -> >= 65% similar  (same topic, loose)")
    print()


if __name__ == "__main__":
    main()
