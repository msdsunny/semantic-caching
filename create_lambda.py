"""
create_lambda.py
----------------
Programmatically provisions the semantic-caching Lambda function on AWS:

  1. Creates the IAM execution role  (LambdaExecutionRole)
  2. Attaches inline policies        (Bedrock + S3 Vectors + CloudWatch)
  3. Zips lambda_function.py         (in-memory, no temp files)
  4. Creates the Lambda function     (semantic-cache-handler)
  5. Prints the function ARN

Run:  python create_lambda.py
Undo: python create_lambda.py --delete
"""

import argparse
import boto3
import io
import json
import os
import time
import zipfile
from pathlib import Path
from botocore.exceptions import ClientError

# Load AWS credentials from .env if present
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=_env_path, override=True)
        print(f"  [ENV]   Loaded credentials from {_env_path}")
except ImportError:
    pass  # fall back to system env / aws configure

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REGION        = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
FUNCTION_NAME = "semantic-cache-handler"
ROLE_NAME     = "LambdaExecutionRole"
RUNTIME       = "python3.13"
HANDLER       = "lambda_function.lambda_handler"
TIMEOUT       = 60     # seconds
MEMORY        = 256    # MB
SOURCE_FILE   = "lambda_function.py"

# IAM inline policy: exactly the permissions the Lambda needs
INLINE_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "BedrockInvoke",
            "Effect": "Allow",
            "Action": ["bedrock:InvokeModel"],
            "Resource": "*"
        },
        {
            "Sid": "S3VectorsAccess",
            "Effect": "Allow",
            "Action": [
                "s3vectors:QueryVectors",
                "s3vectors:PutVectors",
                "s3vectors:GetVectors",
                "s3vectors:DeleteVectors"
            ],
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}

# Trust policy: allows the Lambda service to assume this role
TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }
    ]
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TAGS = {
    "OK":   "[OK]   ",
    "SKIP": "[SKIP] ",
    "WAIT": "[WAIT] ",
    "PKG":  "[PKG]  ",
    "DEL":  "[DEL]  ",
    "ERR":  "[ERROR]",
}


def log(tag, msg):
    label = TAGS.get(tag.upper(), f"[{tag}]")
    print(f"  {label}  {msg}")


def zip_source(filepath: str) -> bytes:
    """Package a single .py file into an in-memory zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(filepath, arcname="lambda_function.py")
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# IAM
# ---------------------------------------------------------------------------

def create_role(iam) -> str:
    """Create the Lambda execution role, or reuse it if it already exists."""
    try:
        resp = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(TRUST_POLICY),
            Description="Execution role for semantic-cache-handler Lambda"
        )
        role_arn = resp["Role"]["Arn"]
        log("ok", f"IAM role created: {role_arn}")

        # Attach the least-privilege inline policy
        iam.put_role_policy(
            RoleName=ROLE_NAME,
            PolicyName="SemanticCachePolicy",
            PolicyDocument=json.dumps(INLINE_POLICY)
        )
        log("ok", "Inline policy attached (Bedrock + S3 Vectors + CloudWatch Logs)")

        # IAM propagation delay
        log("wait", "Waiting 12 s for IAM role propagation...")
        time.sleep(12)

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "EntityAlreadyExists":
            role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
            log("skip", f"IAM role already exists, reusing: {role_arn}")
        elif code == "AccessDenied":
            # Lab/course environments pre-create the role; just look it up
            try:
                role_arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
                log("skip", f"No IAM permissions — using pre-existing role: {role_arn}")
            except ClientError:
                raise RuntimeError(
                    f"Cannot create or find role '{ROLE_NAME}'. "
                    "Ensure the role exists or grant iam:CreateRole to your user."
                )
        else:
            raise

    return role_arn


def delete_role(iam):
    """Remove all inline policies then delete the role (skips if no permission)."""
    try:
        policies = iam.list_role_policies(RoleName=ROLE_NAME).get("PolicyNames", [])
        for p in policies:
            iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=p)
            log("del", f"Deleted inline policy: {p}")
        iam.delete_role(RoleName=ROLE_NAME)
        log("del", f"IAM role deleted: {ROLE_NAME}")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "NoSuchEntity":
            log("skip", f"IAM role '{ROLE_NAME}' not found, skipping")
        elif code == "AccessDenied":
            log("skip", f"No IAM delete permission — leaving role '{ROLE_NAME}' intact")
        else:
            raise


# ---------------------------------------------------------------------------
# Lambda
# ---------------------------------------------------------------------------

def create_function(lam, role_arn: str) -> str:
    """Zip lambda_function.py and deploy it; return the function ARN."""
    log("PKG", f"Zipping {SOURCE_FILE}...")
    zip_bytes = zip_source(SOURCE_FILE)
    log("OK", f"Zip ready ({len(zip_bytes):,} bytes)")

    try:
        resp = lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime=RUNTIME,
            Role=role_arn,
            Handler=HANDLER,
            Code={"ZipFile": zip_bytes},
            Timeout=TIMEOUT,
            MemorySize=MEMORY,
            Description="Semantic caching handler: checks S3 Vectors then calls Bedrock",
            Environment={
                "Variables": {
                    "BUCKET_NAME": "semantic-cache-app",
                    "INDEX_NAME":  "cache-index"
                }
            }
        )
        fn_arn = resp["FunctionArn"]
        log("OK", f"Lambda function created: {fn_arn}")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            # Function exists -> update code instead
            log("SKIP", "Function already exists, updating code...")
            resp = lam.update_function_code(
                FunctionName=FUNCTION_NAME,
                ZipFile=zip_bytes
            )
            fn_arn = resp["FunctionArn"]
            log("OK", f"Lambda function code updated: {fn_arn}")
        else:
            raise

    # Wait until function state is Active
    log("WAIT", "Waiting for function to become Active...")
    waiter = lam.get_waiter("function_active_v2")
    waiter.wait(FunctionName=FUNCTION_NAME)
    log("OK", "Function is Active and ready")

    return fn_arn


def delete_function(lam):
    try:
        lam.delete_function(FunctionName=FUNCTION_NAME)
        log("DEL", f"Lambda function deleted: {FUNCTION_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            log("SKIP", f"Function '{FUNCTION_NAME}' not found, skipping")
        else:
            raise


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def create():
    print("\n>>> Provisioning Lambda function")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    iam = session.client("iam")
    lam = session.client("lambda")

    role_arn = create_role(iam)
    fn_arn   = create_function(lam, role_arn)

    print("\n" + "-" * 52)
    print("[DONE] Lambda function deployed successfully!\n")
    print(f"   Function Name : {FUNCTION_NAME}")
    print(f"   Function ARN  : {fn_arn}")
    print(f"   Region        : {REGION}")
    print(f"   Runtime       : {RUNTIME}")
    print(f"   Timeout       : {TIMEOUT}s  |  Memory: {MEMORY} MB")
    print("\n   Next step -> run  python create_api.py  to create the HTTP API.\n")


def delete():
    print("\n[DELETE] Removing Lambda resources")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    iam = session.client("iam")
    lam = session.client("lambda")

    delete_function(lam)
    delete_role(iam)

    print("\n[OK] Cleanup complete.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create or delete the semantic-cache Lambda function"
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
