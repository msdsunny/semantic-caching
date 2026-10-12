# Semantic Caching with Amazon S3 — Project Summary

---

## 🎯 What Is It?

A **serverless AI chat application** that uses **semantic caching** to dramatically reduce LLM inference costs and latency. Instead of calling an expensive LLM every time a user asks a similar question, the system intelligently reuses previously generated answers by comparing the *meaning* (semantics) of queries — not just exact text.

> **Key Insight**: Users often phrase the same question differently.  
> *"What is the pricing?"* and *"How much does it cost?"* mean the same thing.  
> Semantic caching catches this and returns the cached answer instantly.

---

## 💡 Core Problem It Solves

| Without Semantic Caching | With Semantic Caching |
|--------------------------|----------------------|
| Every query hits the LLM | Similar queries served from cache |
| High inference costs | Dramatically reduced API costs |
| Higher latency (2–10s) | Near-instant responses for cache hits |
| No reuse of prior answers | Reuses semantically equivalent answers |

---

## 🏗️ Architecture

```
User Browser
     │
     ▼
Flask Web App (app.py)  ←── Vercel / Local
     │
     ▼
Amazon API Gateway  (HTTP API — POST /chat)
     │
     ▼
AWS Lambda Function  (semantic-cache-handler)
     │
     ├──[1] Generate Embedding ──► Amazon Bedrock (Titan Embed v2)
     │                                  │ 1024-dim float32 vector
     │                                  ▼
     ├──[2] Query Vector Cache ──► Amazon S3 Vectors (semantic-cache-app)
     │                                  │
     │            ┌─────── Cache HIT ───┤ distance ≤ threshold
     │            │         (fast)      └─────── Cache MISS
     │            ▼                                  │
     │      Return cached answer              [3] Invoke LLM
     │                                ► Amazon Bedrock (Nova Pro v1)
     │                                              │
     │                                [4] Save to S3 Vector Cache
     │                                              │
     └◄─────────────────── Return answer ◄──────────┘
```

---

## 🔧 Technology Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | HTML + Vanilla JS + Flask Templates |
| **Backend / API** | Python Flask (app.py) |
| **Serverless Compute** | AWS Lambda (Python) |
| **API Gateway** | Amazon API Gateway — HTTP API |
| **Vector Store / Cache** | Amazon S3 Vectors (new service) |
| **Embedding Model** | Amazon Titan Embed Text v2 (`amazon.titan-embed-text-v2:0`) |
| **LLM** | Amazon Nova Pro v1 (`amazon.nova-pro-v1:0`) |
| **Cloud SDK** | boto3 (AWS SDK for Python) |
| **Deployment** | Vercel (frontend) + AWS (backend) |
| **IaC / Automation** | Custom Python provisioner scripts |

---

## ⚙️ How Semantic Caching Works (Step by Step)

1. **User submits a query** via the chat UI
2. **Embedding generated**: The Lambda converts the query into a **1024-dimensional vector** using Amazon Titan Embeddings v2
3. **Cache lookup**: The vector is compared against all stored vectors in **Amazon S3 Vectors** using **cosine distance**
   - Cosine distance `0.0` = perfect match
   - Cosine distance `1.0` = completely different
4. **Cache HIT** (distance ≤ threshold): Return stored answer immediately — no LLM call needed
5. **Cache MISS** (distance > threshold): Call **Amazon Nova Pro** (LLM), store the new Q&A pair in the vector cache, return response
6. **Response tagged** with `X-Cache-Status: HIT` or `MISS` header for observability

---

## 🎛️ Configurable Similarity Threshold

The threshold controls how strict the cache match must be:

| Threshold | Distance Limit | Behavior |
|-----------|---------------|----------|
| `0.90` | ≤ 0.10 | Very strict — near-identical phrasing only |
| `0.80` | ≤ 0.20 | Similar meaning, some word variation |
| **`0.75`** (default) | **≤ 0.25** | **Paraphrases, different wording, same intent** |

The threshold is **dynamically adjustable** from the web UI — it updates the Lambda environment variable live via AWS API.

---

## 📁 Project Structure

```
semantic-caching/
│
├── app.py                  # Flask web server — main application
├── lambda_function.py      # AWS Lambda — semantic cache logic
│
├── templates/
│   └── index.html          # Chat UI with cache status display
│
├── create_s3_vectors.py    # Provisions S3 Vector Bucket + Index
├── create_lambda.py        # Provisions IAM Role + Lambda Function
├── create_api.py           # Provisions API Gateway + Route
├── setup_all.py            # One-command full stack provisioner/teardown
├── update_lambda.py        # Hot-deploys updated Lambda code
│
├── check_similarity.py     # Utility: test cosine distance between prompts
├── requirements.txt        # Python dependencies
├── vercel.json             # Vercel deployment config
└── .env                    # Environment config (API URLs, region, etc.)
```

---

## 🚀 Key Features

- ✅ **Semantic similarity** — catches paraphrased/reworded queries
- ✅ **Real-time cache status** — UI shows HIT 🟢 or MISS 🟠 per query
- ✅ **Adjustable threshold** — tune strictness from the web UI without redeploying
- ✅ **One-command setup & teardown** — `python setup_all.py` provisions everything
- ✅ **Auto-teardown** — Ctrl+C stops server AND deletes all AWS resources
- ✅ **Serverless** — zero server management, pay-per-use pricing
- ✅ **Vercel deployable** — frontend can be deployed with zero config

---

## 📊 AWS Infrastructure Provisioned

| Resource | Name | Purpose |
|----------|------|---------|
| S3 Vector Bucket | `semantic-cache-app` | Stores query embeddings + answers |
| S3 Vector Index | `cache-index` | Cosine similarity search index (1024-dim) |
| Lambda Function | `semantic-cache-handler` | Core caching + LLM invocation logic |
| IAM Role | `LambdaExecutionRole` | Permissions for Bedrock, S3 Vectors, CloudWatch |
| API Gateway | `ChatAPI` | HTTP POST `/chat` endpoint |

---

## 💰 Cost Impact

- **Cache HIT**: ~0 LLM cost, ~milliseconds latency
- **Cache MISS**: Standard Bedrock inference cost + embedding cost
- As cache grows, **hit rate increases**, and costs decrease over time
- S3 Vectors is designed for **scalable, low-cost** vector storage

---

## 🔑 Use Cases

This pattern is ideal for:

- 📚 **FAQ / Knowledge Base Systems** — same questions in many forms
- 🤝 **Customer Support Chatbots** — repetitive support queries
- 🔎 **Search & Discovery Apps** — semantically similar searches
- 📖 **Documentation Assistants** — coding questions, how-to queries
- 🏢 **Enterprise Q&A** — internal knowledge retrieval at scale
