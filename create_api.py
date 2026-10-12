"""
create_api.py
-------------
Programmatically provisions the API Gateway HTTP API and wires it to Lambda:

  1. Gets the Lambda function ARN   (semantic-cache-handler)
  2. Creates the HTTP API           (ChatAPI)
  3. Creates a Lambda integration   (AWS_PROXY, payload v2.0)
  4. Creates the route              (POST /chat -> integration)
  5. Grants API Gateway permission  (lambda:InvokeFunction)
  6. Retrieves the $default invoke URL
  7. Patches app.py                 (replaces <Add-API-Invoke-URL> placeholder)

Run:  python create_api.py
Undo: python create_api.py --delete
"""

import argparse
import boto3
import os
import re
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
REGION        = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
FUNCTION_NAME = "semantic-cache-handler"
API_NAME      = "ChatAPI"
ROUTE_KEY     = "POST /chat"
APP_PY_PATH   = Path(__file__).parent / "app.py"

TAGS = {
    "OK":   "[OK]   ",
    "SKIP": "[SKIP] ",
    "WAIT": "[WAIT] ",
    "DEL":  "[DEL]  ",
    "PATCH":"[PATCH]",
    "ERR":  "[ERROR]",
}


def log(tag, msg):
    label = TAGS.get(tag.upper(), f"[{tag}]")
    print(f"  {label}  {msg}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_function_arn(lam) -> str:
    """Fetch the ARN of the already-deployed Lambda function."""
    resp = lam.get_function(FunctionName=FUNCTION_NAME)
    arn = resp["Configuration"]["FunctionArn"]
    log("OK", f"Found Lambda function: {arn}")
    return arn


def get_account_id(sts) -> str:
    return sts.get_caller_identity()["Account"]


def find_existing_api(apigw) -> str | None:
    """Return the ApiId of ChatAPI if it already exists, else None."""
    paginator = apigw.get_paginator("get_apis")
    for page in paginator.paginate():
        for api in page.get("Items", []):
            if api["Name"] == API_NAME:
                return api["ApiId"]
    return None


# ---------------------------------------------------------------------------
# Create path
# ---------------------------------------------------------------------------

def create_api_resources(apigw, lam, sts, fn_arn) -> str:
    """Create API, integration, route, and permission. Return invoke URL."""

    account_id = get_account_id(sts)

    # 1. Create HTTP API
    existing_id = find_existing_api(apigw)
    if existing_id:
        api_id = existing_id
        log("SKIP", f"HTTP API already exists: {API_NAME} (id={api_id})")
    else:
        resp = apigw.create_api(
            Name=API_NAME,
            ProtocolType="HTTP",
            Description="Frontend for the semantic caching Lambda function",
            Tags={"Project": "semantic-caching", "ManagedBy": "create_api.py"}
        )
        api_id = resp["ApiId"]
        log("OK", f"HTTP API created: {API_NAME} (id={api_id})")

    # 2. Create Lambda integration (AWS_PROXY)
    integration_id = None
    existing_integrations = apigw.get_integrations(ApiId=api_id).get("Items", [])
    for integ in existing_integrations:
        if fn_arn in integ.get("IntegrationUri", ""):
            integration_id = integ["IntegrationId"]
            log("SKIP", f"Integration already exists (id={integration_id})")
            break

    if not integration_id:
        resp = apigw.create_integration(
            ApiId=api_id,
            IntegrationType="AWS_PROXY",
            IntegrationUri=fn_arn,
            PayloadFormatVersion="2.0",
            TimeoutInMillis=29000
        )
        integration_id = resp["IntegrationId"]
        log("OK", f"Lambda integration created (id={integration_id})")

    # 3. Create POST /chat route
    target = f"integrations/{integration_id}"
    existing_routes = apigw.get_routes(ApiId=api_id).get("Items", [])
    route_exists = any(r.get("RouteKey") == ROUTE_KEY for r in existing_routes)

    if route_exists:
        log("SKIP", f"Route already exists: {ROUTE_KEY}")
    else:
        apigw.create_route(
            ApiId=api_id,
            RouteKey=ROUTE_KEY,
            Target=target
        )
        log("OK", f"Route created: {ROUTE_KEY} -> {target}")

    # 4. Auto-deploy stage ($default is created automatically for HTTP APIs)
    #    Just make sure it exists and auto-deploy is on.
    try:
        apigw.update_stage(
            ApiId=api_id,
            StageName="$default",
            AutoDeploy=True
        )
        log("OK", "Auto-deploy enabled on $default stage")
    except ClientError as e:
        if "NotFoundException" in str(e):
            apigw.create_stage(
                ApiId=api_id,
                StageName="$default",
                AutoDeploy=True
            )
            log("OK", "$default stage created with auto-deploy")
        else:
            raise

    # 5. Grant API Gateway permission to invoke Lambda
    #    Use a stable StatementId so re-runs are idempotent.
    statement_id = f"{API_NAME}-invoke-permission"
    source_arn = (
        f"arn:aws:execute-api:{REGION}:{account_id}:{api_id}/*/*/chat"
    )
    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=source_arn
        )
        log("OK", f"Lambda invoke permission granted (source={source_arn})")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            log("SKIP", "Lambda permission already exists")
        else:
            raise

    # 6. Retrieve invoke URL from $default stage
    log("WAIT", "Waiting 3 s for deployment to propagate...")
    time.sleep(3)

    stage_info = apigw.get_stage(ApiId=api_id, StageName="$default")
    invoke_url = stage_info.get("InvokeUrl", "").rstrip("/")

    if not invoke_url:
        # Construct it manually if not returned yet
        invoke_url = f"https://{api_id}.execute-api.{REGION}.amazonaws.com"

    log("OK", f"Invoke URL: {invoke_url}")

    return invoke_url, api_id


# ---------------------------------------------------------------------------
# Patch app.py
# ---------------------------------------------------------------------------

def patch_app_py(invoke_url: str):
    """Replace the API_GATEWAY_URL placeholder in app.py."""
    if not APP_PY_PATH.exists():
        log("ERR", f"app.py not found at {APP_PY_PATH}")
        return

    content = APP_PY_PATH.read_text(encoding="utf-8")

    # Match any API_GATEWAY_URL assignment line
    pattern = r'API_GATEWAY_URL\s*=\s*.*$'
    replacement = f'API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "{invoke_url}/chat")'

    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        try:
            APP_PY_PATH.write_text(new_content, encoding="utf-8")
            log("PATCH", f'app.py updated -> API_GATEWAY_URL = "{invoke_url}/chat"')
        except OSError:
            log("SKIP", f'Read-only filesystem (Vercel). API Gateway URL: {invoke_url}/chat')
    else:
        log("ERR", "Could not find API_GATEWAY_URL line in app.py")


# ---------------------------------------------------------------------------
# Delete path
# ---------------------------------------------------------------------------

def delete_api(apigw, lam):
    # Remove Lambda permission
    try:
        lam.remove_permission(
            FunctionName=FUNCTION_NAME,
            StatementId=f"{API_NAME}-invoke-permission"
        )
        log("DEL", "Lambda invoke permission removed")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("ResourceNotFoundException", "NoSuchEntity"):
            log("SKIP", "Lambda permission not found, skipping")
        else:
            raise

    # Delete the HTTP API (deletes routes and integrations automatically)
    api_id = find_existing_api(apigw)
    if api_id:
        apigw.delete_api(ApiId=api_id)
        log("DEL", f"HTTP API deleted: {API_NAME} (id={api_id})")
    else:
        log("SKIP", f"HTTP API '{API_NAME}' not found, skipping")

    # Restore placeholder in app.py
    if APP_PY_PATH.exists():
        try:
            content = APP_PY_PATH.read_text(encoding="utf-8")
            pattern = r'API_GATEWAY_URL\s*=\s*.*$'
            restored = re.sub(
                pattern,
                'API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "<Add-API-Invoke-URL>/chat")',
                content,
                flags=re.MULTILINE
            )
            APP_PY_PATH.write_text(restored, encoding="utf-8")
            log("PATCH", "app.py restored to placeholder URL")
        except OSError:
            log("SKIP", "Read-only filesystem (Vercel), skipped app.py file update")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def create():
    print("\n>>> Provisioning API Gateway HTTP API")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    lam    = session.client("lambda")
    apigw  = session.client("apigatewayv2")
    sts    = session.client("sts")

    fn_arn = get_function_arn(lam)
    invoke_url, api_id = create_api_resources(apigw, lam, sts, fn_arn)

    patch_app_py(invoke_url)

    print("\n" + "-" * 52)
    print("[DONE] HTTP API provisioned!\n")
    print(f"   API Name   : {API_NAME}")
    print(f"   API ID     : {api_id}")
    print(f"   Route      : {ROUTE_KEY}")
    print(f"   Invoke URL : {invoke_url}")
    print(f"   Chat URL   : {invoke_url}/chat")
    print(f"   Region     : {REGION}")
    print("\n   Start the app -> python app.py  then open http://localhost:5000\n")


def delete():
    print("\n[DELETE] Removing API Gateway resources")
    print("-" * 52)

    session = boto3.session.Session(region_name=REGION)
    lam   = session.client("lambda")
    apigw = session.client("apigatewayv2")

    delete_api(apigw, lam)

    print("\n[OK] API Gateway cleanup complete.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create or delete the ChatAPI HTTP API Gateway"
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
