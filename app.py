from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import requests
import os
import subprocess
import sys
import re

import boto3
from botocore.exceptions import ClientError

app = Flask(__name__)

# =============================
# CONFIGURATION
# =============================

# Replace with your actual API Gateway invoke URL
API_GATEWAY_URL = os.environ.get("API_GATEWAY_URL", "https://jyrbsfxc67.execute-api.us-east-1.amazonaws.com/chat")
LAMBDA_FUNCTION_NAME = os.environ.get("LAMBDA_FUNCTION_NAME", "semantic-cache-handler")

# Base directory where setup scripts live (same folder as this file)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# =============================
# ROUTES
# =============================

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Gets or updates active backend configuration for UI display."""
    global API_GATEWAY_URL
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        new_url = data.get("api_gateway_url", "").strip()

        if not new_url:
            return jsonify({"error": "API Gateway URL cannot be empty"}), 400

        # Auto-sanitize URL to end with /chat
        clean_url = new_url.rstrip("/")
        if not clean_url.endswith("/chat"):
            clean_url = clean_url + "/chat"

        API_GATEWAY_URL = clean_url
        os.environ["API_GATEWAY_URL"] = clean_url

        # Persist to .env file if running locally
        if os.environ.get("VERCEL") != "1":
            env_path = os.path.join(BASE_DIR, ".env")
            lines = []
            found = False
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("API_GATEWAY_URL"):
                            lines.append(f"API_GATEWAY_URL={clean_url}\n")
                            found = True
                        else:
                            lines.append(line)
            if not found:
                lines.append(f"API_GATEWAY_URL={clean_url}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

        return jsonify({
            "message": "API Gateway URL updated successfully!",
            "api_gateway_url": API_GATEWAY_URL
        })

    return jsonify({
        "api_gateway_url": API_GATEWAY_URL,
        "embedding_model": "amazon.titan-embed-text-v2:0",
        "llm_model": "amazon.nova-pro-v1:0"
    })


@app.route("/lambda/threshold", methods=["GET", "POST"])
def lambda_threshold():
    """Reads or updates the SIMILARITY_THRESHOLD environment variable in AWS Lambda."""
    function_name = os.environ.get("LAMBDA_FUNCTION_NAME", "semantic-cache-handler")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    try:
        client = boto3.client("lambda", region_name=region)

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            val = float(data.get("threshold", 0.75))
            val = max(0.10, min(0.99, val))

            # Fetch current function configuration
            cfg = client.get_function_configuration(FunctionName=function_name)
            env_vars = cfg.get("Environment", {}).get("Variables", {})
            env_vars["SIMILARITY_THRESHOLD"] = str(val)

            # Update function configuration in AWS Lambda
            client.update_function_configuration(
                FunctionName=function_name,
                Environment={"Variables": env_vars}
            )
            return jsonify({
                "message": f"Similarity threshold updated to {int(val * 100)}%",
                "threshold": val,
                "function": function_name
            })

        else:
            # GET: return current threshold from AWS Lambda
            try:
                cfg = client.get_function_configuration(FunctionName=function_name)
                env_vars = cfg.get("Environment", {}).get("Variables", {})
                val = float(env_vars.get("SIMILARITY_THRESHOLD", "0.75"))
            except Exception:
                val = 0.75
            return jsonify({
                "threshold": val,
                "function": function_name
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/ask", methods=["POST"])
def ask():
    data = request.json
    prompt = data.get("prompt", "").strip()

    if not prompt:
        return jsonify({"error": "Prompt cannot be empty"}), 400

    try:
        response = requests.post(
            API_GATEWAY_URL,
            json={"prompt": prompt},
            timeout=30
        )

        cache_status = response.headers.get("X-Cache-Status", "UNKNOWN")
        body = response.json()

        return jsonify({
            "answer": body.get("response", ""),
            "cache_status": cache_status
        })

    except requests.exceptions.ConnectionError:
        return jsonify({
            "error": f"API Gateway endpoint ({API_GATEWAY_URL}) is unreachable or has been deleted. Please run 'Setup Full Stack' in Infrastructure or update the API Gateway URL in settings."
        }), 502
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


# =============================
# INFRASTRUCTURE CONTROL
# =============================

def _stream_script(args: list[str]):
    """
    Run a Python script as a subprocess and yield its output
    line-by-line as Server-Sent Events (SSE).
    Sends a final __EXIT_<code>__ event so the client knows when it's done.
    """
    def generate():
        process = subprocess.Popen(
            [sys.executable] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=BASE_DIR,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line-buffered
        )

        # Stream each line as an SSE data event
        for raw_line in iter(process.stdout.readline, ""):
            line = raw_line.rstrip("\r\n")
            if line:  # skip blank lines to keep stream tidy
                # Escape any SSE-breaking characters
                safe = line.replace("\n", " ").replace("\r", "")
                yield f"data: {safe}\n\n"

        process.wait()
        yield f"data: __EXIT_{process.returncode}__\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )


@app.route("/infra/setup")
def infra_setup():
    """Stream output of: python setup_all.py --no-serve"""
    return _stream_script(["setup_all.py", "--no-serve"])


@app.route("/infra/teardown")
def infra_teardown():
    """Stream output of: python setup_all.py --delete"""
    return _stream_script(["setup_all.py", "--delete"])


@app.route("/infra/update-lambda")
def infra_update_lambda():
    """Stream output of: python update_lambda.py"""
    return _stream_script(["update_lambda.py"])


@app.route("/infra/status", methods=["GET"])
def infra_status():
    """
    Quick check: can we reach the configured API Gateway endpoint?
    Returns { "reachable": bool, "url": str }
    """
    try:
        r = requests.post(
            API_GATEWAY_URL,
            json={"prompt": "__ping__"},
            timeout=8
        )
        reachable = r.status_code in (200, 400, 422)  # 400 = valid response (empty prompt)
    except Exception:
        reachable = False

    return jsonify({"reachable": reachable, "url": API_GATEWAY_URL})


# =============================
# MAIN
# =============================

if __name__ == "__main__":
    debug_mode = os.environ.get("VERCEL") != "1"
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)
