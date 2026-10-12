# Semantic Caching Project — Learning Session Notes

> **Date:** September–October 2026  
> **Project:** Semantic Caching with AWS Bedrock + S3 Vectors  
> **Stack:** Python · AWS Lambda · Amazon Titan Embeddings · Amazon Nova Pro · S3 Vectors

---

## 1. How Does Top-K Ranking Work in This Project?

### The Core Call
In [`lambda_function.py`](./lambda_function.py), the `check_cache()` function queries S3 Vectors with `topK=1`:

```python
response = s3_vectors.query_vectors(
    vectorBucketName=BUCKET_NAME,
    indexName=INDEX_NAME,
    queryVector={'float32': vector},
    topK=1,             # fetch only the single nearest neighbour
    returnMetadata=True,
    returnDistance=True
)
```

S3 Vectors performs an **Approximate Nearest Neighbor (ANN)** search across all stored embeddings, ranks them by cosine distance, and returns only the **top-1 closest result**.

### Full Flow
```
User Prompt
    │
    ▼
[Amazon Titan Embeddings]  →  1024-dim vector
    │
    ▼
[S3 Vectors: topK=1 ANN search]  →  nearest stored vector
    │
    ▼
[Threshold check]  distance ≤ 0.25 → CACHE HIT / else → CACHE MISS
    │
    └── MISS → [Amazon Nova Pro LLM] → answer → stored back in cache
```

### Why topK=1?
Only the single best candidate is needed. If it doesn't clear the threshold, lower-ranked results wouldn't help either.

---

## 2. topK vs Similarity Threshold — They Are NOT the Same

| Concept | What it controls | Analogy |
|---|---|---|
| `topK=1` | **How many** candidates to fetch | "Invite top 1 candidate to interview" |
| `SIMILARITY_THRESHOLD=0.75` | **How good** the match must be | "Only hire if they score ≥ 75%" |

You can fetch the top result (`topK=1`) and still **reject** it if it doesn't meet the quality bar (threshold). These are independent controls.

```python
cache_threshold = 1.0 - SIMILARITY_THRESHOLD  # 1.0 - 0.75 = 0.25
if distance <= cache_threshold:
    return cached_answer   # CACHE HIT
```

---

## 3. Do We Need Quantization?

**No — not for this project's scale.**

| Type | Precision | Size/vector | Trade-off |
|---|---|---|---|
| `float32` *(current)* | 32-bit | 4 KB (1024 dims) | Full accuracy |
| `int8` | 8-bit | 1 KB | Small accuracy loss |
| Binary | 1-bit | 0.125 KB | Significant loss |

### Why quantization is overkill here:
- Cache stores **hundreds to low-thousands** of vectors — not millions
- S3 Vectors manages the ANN index internally
- False positives (wrong cached answer) are worse than a cache miss
- Vector search is already sub-millisecond at this scale

> **Quantization pays off at millions of vectors in self-hosted indexes (FAISS/Weaviate).**

---

## 4. How Storage and Retrieval Work — The Key-Value Question

### Writing to Cache (Cache Miss)
```python
def save_to_cache(prompt, vector, answer):
    unique_key = str(uuid.uuid4())   # random UUID — just an internal ID
    s3_vectors.put_vectors(vectors=[{
        "key":      unique_key,
        "data":     {"float32": vector},   # the 1024-dim vector
        "metadata": {
            "original_prompt": prompt,     # original text
            "answer":          answer      # LLM's response
        }
    }])
```

**One stored entry:**
```
key:      "a3f9c2d1-84bb-4e2a-..."    ← internal UUID (not used for search)
vector:   [0.023, -0.411, 0.187, ...]  ← 1024 floats (the "address")
metadata: { prompt: "...", answer: "..." }  ← the payload
```

### Reading from Cache (Next Query)
The UUID key is **NOT used for lookup**. S3 Vectors searches by **vector proximity** — similar questions produce numerically close vectors.

```
Traditional cache:  "exact question" → hash → key → answer  (exact match only)
Semantic cache:     "similar question" → close vector → nearest neighbor → answer ✅
```

### The Insight
> **Meaning is encoded in geometry.** Similar questions live close together in 1024-dimensional space, so no exact key match is ever needed.

---

## 5. Is This Project RAG-Based?

**No.** They share vector search technology but are architecturally different.

### RAG (Retrieval-Augmented Generation)
```
Query → retrieve relevant DOCUMENTS → inject into LLM prompt → LLM generates answer
```
- LLM is **always** called
- Retrieved content is **context** for the LLM
- Goal: improve LLM accuracy with external knowledge

### This Project (Semantic Cache)
```
Query → find similar PAST QUESTION → if close enough, return stored answer (skip LLM)
                                   → if not, call LLM with raw prompt only
```
- LLM is **skipped** on cache hits
- Retrieved content **IS** the answer, not input to the LLM
- Goal: reduce cost & latency

### Side-by-Side

| Aspect | This Project | RAG |
|---|---|---|
| Vector search? | ✅ | ✅ |
| LLM always called? | ❌ (skipped on HIT) | ✅ |
| Retrieved content role | **IS** the final answer | **Context** for LLM |
| Goal | Save cost & latency | Improve LLM accuracy |
| Knowledge base | Past Q&A pairs | Domain documents |

### Interview-ready definition of RAG:
> *"RAG is enriching an LLM with external context at query time so it can answer beyond its training data. The three components are: **R**etrieval (fetch docs), **A**ugmented (inject into prompt), **G**eneration (LLM answers using that context)."*

---

## 6. Two AI Models Used in This Project

```python
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"   # always called
LLM_MODEL_ID       = "amazon.nova-pro-v1:0"           # only on cache MISS
```

| Model | Role | When called |
|---|---|---|
| **Amazon Titan Embeddings v2** | Converts text → 1024-dim vector | **Every request** |
| **Amazon Nova Pro (LLM)** | Generates the actual answer | **Only on cache MISS** |

Using an LLM does not make a project RAG. What makes it RAG is **injecting retrieved content into the LLM's prompt** — which this project does not do.

---

## 7. Temperature vs Similarity — Completely Different Things

| | Temperature | Similarity Threshold |
|---|---|---|
| **What it controls** | Randomness of LLM output | How close two vectors must be for a cache hit |
| **Affects** | Quality/style of generated text | HIT or MISS decision |
| **Stage** | Text generation (inside LLM) | Vector search (S3 Vectors) |
| **In this project** | Not explicitly set (LLM default) | `SIMILARITY_THRESHOLD = 0.75` |

---

## 8. What Temperature Actually Does

When an LLM generates text, it produces a **probability distribution** over its vocabulary for every next token:

```
Next word after "The capital of France is..."
  Paris  → 78%
  Lyon   →  9%
  a      →  6%
  ...
```

**Temperature reshapes this distribution:**
- **Low temp** → amplifies high-probability words, suppresses low ones (more certain)
- **High temp** → flattens distribution, gives lower-ranked words more chance (more random)
- **temp=0** → always picks the single highest probability word (fully deterministic)

### Temperature Range & Scenarios

| Range | Label | Best For |
|---|---|---|
| `0.0` | Fully deterministic | Exact same answer every time |
| `0.1 – 0.3` | Very focused / factual | Factual Q&A, code generation, **semantic caches** |
| `0.4 – 0.6` | Balanced | General assistants, customer support |
| `0.7 – 0.9` | Creative / varied | Storytelling, marketing copy |
| `1.0+` | Highly random | Brainstorming, creative experiments |

### Example Output at Different Temperatures

```
Prompt: "What is the capital of France?"

temp=0.1  → "The capital of France is Paris."
temp=0.5  → "Paris is the capital of France, known for the Eiffel Tower and rich culture."
temp=0.95 → "Ah, the City of Light! Paris — a timeless jewel on the Seine — proudly
             holds the crown as France's beating heart and capital."
```

### Temperature and Semantic Caching — A Conflict

```
High temp → LLM gives different answers to same question each time
              ↓
            Cached answers become inconsistent / stale
              ↓
            Cache loses reliability ❌

Low temp  → Consistent answers, reliable cache entries ✅
```

> **Recommendation for this project:** Use low temperature (0.1–0.3) for Nova Pro to keep cached answers consistent and trustworthy.

---

## Key Takeaways

1. **`topK`** = how many candidates to fetch from the vector index (quantity)
2. **`SIMILARITY_THRESHOLD`** = how close a match must be to accept (quality)
3. **Quantization** = not needed at this scale; adds complexity with no benefit
4. **Storage** = UUID key is just an internal ID; retrieval is by vector proximity, not key lookup
5. **This is NOT RAG** — it's a semantic cache that *bypasses* the LLM on hits
6. **Two models**: Titan Embeddings (always) + Nova Pro LLM (only on MISS)
7. **Temperature ≠ Similarity** — they live at completely different stages of the pipeline
8. **Low temperature** is better suited for semantic caching workloads
