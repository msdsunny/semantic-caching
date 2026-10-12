# 🧠 Semantic Caching with Amazon S3 Vectors & AWS Bedrock

> Reduce LLM inference costs and latency by caching semantically similar queries — no exact match required.

---

## 📌 What is Semantic Caching?

In generative AI applications, users often phrase the same question in different ways:

- *"What is the pricing?"*
- *"How much does it cost?"*
- *"What's the price model?"*

Traditional caches fail here because these are not **exact string matches**. Semantic caching solves this by:

1. Converting every query into a **vector embedding** (a numerical fingerprint of meaning)
2. Storing embeddings alongside their LLM responses
3. On new queries, finding the **nearest cached embedding** using cosine distance
4. If close enough → return the cached answer (**no LLM call needed**)

This reduces unnecessary model invocations, improves response time, and lowers costs.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        User / Flask UI                       │
└────────────────────────┬────────────────────────────────────┘
                         │  POST /chat
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Amazon API Gateway  (HTTP API - ChatAPI)        │
└────────────────────────┬────────────────────────────────────┘
                         │  Invoke
                         ▼
┌─────────────────────────────────────────────────────────────┐
│           AWS Lambda  (semantic-cache-handler)               │
│                                                             │
│  1. Generate embedding  ──► Amazon Titan Embeddings v2      │
│  2. Query S3 Vector index                                   │
│     ├── HIT  (distance ≤ threshold) → return cached answer  │
│     └── MISS → invoke LLM → store result → return answer   │
│  3. Store new Q&A pair  ──► Amazon S3 Vectors               │
│  4. Generate LLM answer ──► Amazon Nova Pro (on MISS only)  │
└─────────────────────────────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          ▼                             ▼
┌─────────────────┐          ┌──────────────────────┐
│  Amazon S3      │          │  Amazon Bedrock        │
│  Vectors        │          │  - Titan Embeddings v2 │
│  (cache-index)  │          │  - Nova Pro LLM        │
└─────────────────┘          └──────────────────────┘
```

---

## 🛠️ Tech Stack

| Component | Service |
|---|---|
| **Embedding Model** | `amazon.titan-embed-text-v2:0` (1024-dim vectors) |
| **LLM** | `amazon.nova-pro-v1:0` via Amazon Bedrock |
| **Vector Store** | Amazon S3 Vectors (`semantic-cache-app` bucket) |
| **Compute** | AWS Lambda (`semantic-cache-handler`) |
| **API Layer** | Amazon API Gateway (HTTP API) |
| **Web UI** | Flask + HTML/CSS/JS |
| **Deployment** | Vercel (Flask frontend) |

---

## ⚙️ How It Works — Step by Step

```
User sends prompt
      │
      ▼
[1] Titan Embeddings converts prompt → 1024-dim float32 vector
      │
      ▼
[2] S3 Vectors: query_vectors(topK=1)
    → ANN search finds the nearest cached vector by cosine distance
      │
      ├── distance ≤ 0.25  (similarity ≥ 75%)
      │        │
      │        ▼
      │   ✅ CACHE HIT — return stored answer instantly
      │      (X-Cache-Status: HIT)
      │
      └── distance > 0.25  (similarity < 75%)
               │
               ▼
          ❌ CACHE MISS — call Amazon Nova Pro LLM
               │
               ▼
          Store {UUID key, vector, original_prompt, answer} in S3 Vectors
               │
               ▼
          Return fresh answer (X-Cache-Status: MISS)
```

### Key Insight: No Key-Value Lookup
The `UUID` key stored in S3 Vectors is just an internal row ID — **retrieval is done entirely by vector proximity**, not by key. Similar questions produce numerically close vectors, so no exact text match is ever needed.

---

## 📁 Project Structure

```
semantic-caching/
├── app.py                 # Flask web server (UI + infra control routes)
├── lambda_function.py     # Core semantic cache logic (deployed to AWS Lambda)
├── create_s3_vectors.py   # Script to provision S3 Vector bucket + index
├── create_lambda.py       # Script to create and deploy Lambda function
├── create_api.py          # Script to create API Gateway + integrate Lambda
├── setup_all.py           # One-shot full-stack setup / teardown script
├── update_lambda.py       # Redeploys Lambda code from local changes
├── check_similarity.py    # Benchmark cosine distances between phrase pairs
├── requirements.txt       # Python dependencies
├── templates/
│   └── index.html         # Chat UI (dark mode, cache HIT/MISS indicator)
├── api/
│   └── index.py           # Vercel serverless entry point
├── steps.md               # Lab guide: S3 Vectors + Lambda setup
├── steps2.md              # Lab guide: API Gateway + Flask integration
├── session_notes.md       # Learning session Q&A notes
├── vercel.json            # Vercel deployment config
└── .env                   # Local environment variables (not committed)
```

---

## 🚀 Setup & Deployment

### Prerequisites
- AWS account with Bedrock model access enabled for:
  - `amazon.titan-embed-text-v2:0`
  - `amazon.nova-pro-v1:0`
- AWS CLI configured (`aws configure`)
- Python 3.11+

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Create a `.env` file:
```env
AWS_DEFAULT_REGION=us-east-1
BUCKET_NAME=semantic-cache-app
INDEX_NAME=cache-index
LAMBDA_FUNCTION_NAME=semantic-cache-handler
API_GATEWAY_URL=https://<your-api-id>.execute-api.us-east-1.amazonaws.com/chat
```

### 3. One-Shot Infrastructure Setup
```bash
python setup_all.py
```
This will:
- Create the S3 Vector bucket and index (`cache-index`, 1024-dim, cosine distance)
- Package and deploy the Lambda function
- Create the API Gateway HTTP API with a `POST /chat` route
- Print the API invoke URL

### 4. Run Locally
```bash
python app.py
```
Open `http://localhost:5000` in your browser.

### 5. Update Lambda After Code Changes
```bash
python update_lambda.py
```

### 6. Teardown All Infrastructure
```bash
python setup_all.py --delete
```

---

## 🎛️ Configuration

### Similarity Threshold

Controlled via the `SIMILARITY_THRESHOLD` Lambda environment variable. Can be updated **live** without redeployment via the UI or API:

```
POST /lambda/threshold
{ "threshold": 0.80 }
```

| Threshold | Distance Limit | Behaviour |
|---|---|---|
| `0.90` | ≤ 0.10 | Very strict — near-identical phrasing only |
| `0.80` | ≤ 0.20 | Similar meaning, some word variation |
| `0.75` *(default)* | ≤ 0.25 | Paraphrases, different wording, same intent |
| `0.50` | ≤ 0.50 | Loose — loosely related questions may hit |

### Tuning & Benchmarking

Use `check_similarity.py` to benchmark cosine distances between phrase pairs before tuning the threshold:

```bash
python check_similarity.py
```

Sample output:
```
Query A                                       | Query B                                       | Dist   | Sim    | @ 0.90 | @ 0.80 | @ 0.75
What is the pricing for this service?         | what pricing model this service uses          | 0.0821 | 0.9179 | HIT    | HIT    | HIT
What is the pricing for this service?         | How much does it cost?                        | 0.1543 | 0.8457 | MISS   | HIT    | HIT
```

---

## 🔑 Key Concepts

### topK vs Similarity Threshold
| | `topK` | `SIMILARITY_THRESHOLD` |
|---|---|---|
| **Controls** | How many candidates to fetch | How good the match must be |
| **Type** | Quantity | Quality gate |
| **Current value** | `1` | `0.75` |

### This is NOT RAG
| | This Project (Semantic Cache) | RAG |
|---|---|---|
| Vector search? | ✅ | ✅ |
| LLM always called? | ❌ (skipped on HIT) | ✅ |
| Retrieved content role | **IS** the final answer | **Context** for LLM |
| Goal | Reduce cost & latency | Improve LLM accuracy |

### Two AI Models
| Model | Role | Called when |
|---|---|---|
| **Titan Embeddings v2** | Text → 1024-dim vector | Every request |
| **Nova Pro (LLM)** | Generate answer | Cache MISS only |

---

## 📊 Cache Response Headers

The Lambda returns an `X-Cache-Status` header on every response:

| Header Value | Meaning |
|---|---|
| `HIT` | Answer served from cache — LLM was NOT called |
| `MISS` | No similar query found — LLM was called, result now cached |

---

## 💡 Use Cases

Semantic caching is particularly effective for:

- **FAQ systems** — "What are your hours?" / "When are you open?"
- **Customer support chatbots** — repeated policy/product questions
- **Knowledge base search** — paraphrased documentation queries
- **Cost reduction** — any high-volume LLM application with repetitive query patterns

---

## 📦 Dependencies

```
Flask==3.1.1
requests==2.32.3
boto3>=1.38.0
python-dotenv>=1.0.0
```

---

## 📄 License

This project is for educational purposes as part of an AWS Bedrock lab on semantic caching.
