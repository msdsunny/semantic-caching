Create HTTP API

Amazon API Gateway is a fully managed AWS service that allows developers to create, deploy, maintain, and monitor APIs. API Gateway supports multiple API types, including HTTP, REST, and WebSocket APIs. API Gateway acts as a frontend service that routes requests to backend integrations such as AWS services, HTTP endpoints, or other backend services.

In this step, we’ll create an HTTP API using Amazon API Gateway to serve as the entry point for user queries. This API will be integrated with the Lambda function that implements semantic caching. When a client submits a query via the HTTP API, the request is forwarded to the Lambda function, which checks the S3 vector index for similar prompts, returns a cached response if available, or invokes the Bedrock LLM and updates the cache if no match is found.

After the completion of this task, the provisioned infrastructure will be similar to the one shown below:


Architecture diagram

Architecture diagram
Follow these steps to create the HTTP API:

On the AWS Management Console, search for “API” and select the “API Gateway” service.

On the API Gateway console, click the “Create an API” button.

Click the “Build” button in the “HTTP API” section.

Set “API name” to ChatAPI.

Click the “Add integration” button and select “Lambda” from the drop-down menu under the “Integration” section.

Select us-east-1 as “AWS Region,” and choose the ARN of the semantic-cache-handler as “Lambda function.”

Click the “Next” button, which takes us to the “Configure routes - optional” page.

Click the “Add route” button under the “Configure routes” section.

Select POST as “Method,” enter /chat in the “Resource path” field, and choose semantic-cache-handler as the “Integration target.”

Click the “Review and create” button, then click the “Create“ button on the “Review and create” page to create the API.

From the sidebar, select “Stages” under the “Deploy” section and select “$default” under the “Stages for ChatAPI” section.

Copy “Invoke URL” from the “Stage details” section and keep it safe, we’ll use it in the next task.

Note that auto-deploy is enabled by default for the HTTP API, so we don‘t need to explicitly deploy the API.

Note: Click the “Test” button below to verify that the HTTP API is successfully deployed.

Integrate the Agent with Flask Application

In this task, you will integrate the HTTP API with a Flask-based chat application that sends user prompts to the Lambda function through the API. The application allows users to submit chat queries and observe cache behavior (hit or miss) across repeated queries and queries with similar embeddings. Each user prompt is processed as a separate API request, allowing you to evaluate how embeddings, similarity thresholds, and S3 vector indexing affect cache hits and model invocations.

After completing this task, the provisioned infrastructure will look similar to the figure below:


Architecture diagram

Architecture diagram
Replace <Add-API-Invoke-URL> on line 12 with the ChatAPI invoke URL that we copied in the previous task.

Click the “Run” button to run the following Flask application:

app.py

from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

# =============================
# CONFIGURATION
# =============================

# Replace with your actual API Gateway invoke URL
API_GATEWAY_URL ="<Add-API-Invoke-URL>/chat"

# =============================
# ROUTES
# =============================

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


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
            timeout=20
        )

        cache_status = response.headers.get("X-Cache-Status", "UNKNOWN")
        body = response.json()

        return jsonify({
            "answer": body.get("response", ""),
            "cache_status": cache_status
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


# =============================
# MAIN
# =============================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)


template/index.html

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Semantic Cache Chatbot</title>

    <!-- Marked.js for Markdown rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>

    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: #e5e7eb;
            max-width: 800px;
            margin: 40px auto;
        }

        h2 {
            color: #38bdf8;
        }

        textarea {
            width: 100%;
            height: 80px;
            padding: 10px;
            font-size: 16px;
            background: #1e293b;
            color: #e5e7eb;
            border: 1px solid #334155;
            border-radius: 5px;
        }

        button {
            margin-top: 10px;
            padding: 10px 20px;
            font-size: 16px;
            cursor: pointer;
            background: #38bdf8;
            color: #0f172a;
            border: none;
            border-radius: 5px;
        }

        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .result {
            margin-top: 20px;
            padding: 15px;
            background: #020617;
            border-radius: 5px;
            overflow-wrap: break-word;
        }

        .hit {
            color: #22c55e;
            font-weight: bold;
        }

        .miss {
            color: #f97316;
            font-weight: bold;
        }

        /* Loading Spinner */
        .loader {
            border: 4px solid #1e293b;
            border-top: 4px solid #38bdf8;
            border-radius: 50%;
            width: 18px;
            height: 18px;
            display: inline-block;
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        #loading {
            margin-top: 15px;
            font-size: 15px;
        }

        /* Markdown Styling */
        .result h1, .result h2, .result h3, .result h4, .result h5, .result h6 {
            color: #38bdf8;
        }

        .result code {
            background: #1e293b;
            padding: 2px 4px;
            border-radius: 4px;
            font-family: monospace;
        }

        .result pre {
            background: #1e293b;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }

        .result a {
            color: #38bdf8;
        }

        .result ul, .result ol {
            padding-left: 20px;
        }

    </style>
</head>

<body>

<h2>Semantic Cache Q&A Chatbot</h2>

<p>
Ask the same question in different ways and observe
<strong>semantic cache HIT / MISS</strong>.
</p>

<textarea id="prompt" placeholder="Ask your question..."></textarea><br>

<button id="askBtn" onclick="ask()">Ask</button>

<div id="loading" style="display:none;">
    <span class="loader"></span> Thinking...
</div>

<div class="result" id="result" style="display:none;">
    <p>
        Cache Status:
        <span id="cache"></span>
    </p>
    <hr>
    <div id="answer"></div>
</div>

<script>
async function ask() {
    const prompt = document.getElementById("prompt").value.trim();
    if (!prompt) return;

    const btn = document.getElementById("askBtn");
    const loading = document.getElementById("loading");
    const result = document.getElementById("result");

    // Show loading state
    btn.disabled = true;
    loading.style.display = "block";
    result.style.display = "none";

    try {
        const res = await fetch("/ask", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ prompt })
        });

        const data = await res.json();

        if (data.error) {
            alert(data.error);
            return;
        }

        // Render Markdown properly
        document.getElementById("answer").innerHTML = marked.parse(data.answer);

        const cacheElem = document.getElementById("cache");
        cacheElem.textContent = data.cache_status;
        cacheElem.className =
            data.cache_status === "HIT" ? "hit" : "miss";

        result.style.display = "block";

    } catch (err) {
        alert("Something went wrong. Please try again.");
    } finally {
        // Hide loading state
        btn.disabled = false;
        loading.style.display = "none";
    }
}
</script>

</body>
</html>

