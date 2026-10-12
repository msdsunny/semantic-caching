"""
check_similarity.py
-------------------
Tests the cosine distance between question pairs using the same
Titan Embeddings model the Lambda uses, so you can tune the threshold.
"""
import boto3
import json
import math
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env", override=True)

REGION           = "us-east-1"
EMBEDDING_MODEL  = "amazon.titan-embed-text-v2:0"

bedrock = boto3.client("bedrock-runtime", region_name=REGION)

# -- Pairs to test ----------------------------------------------------------
PAIRS = [
    ("What is the pricing for this service?",
     "what pricing model this service uses"),

    ("What is the pricing for this service?",
     "what is the pricing model"),

    ("What is the pricing for this service?",
     "How much does it cost?"),

    ("what pricing model this service uses",
     "what is the pricing model"),

    # Control: identical string should be 0.0
    ("What is the pricing for this service?",
     "What is the pricing for this service?"),
]
# ---------------------------------------------------------------------------


def embed(text: str) -> list[float]:
    resp = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL,
        body=json.dumps({"inputText": text})
    )
    return json.loads(resp["body"].read())["embedding"]


def cosine_distance(a: list[float], b: list[float]) -> float:
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    return 1.0 - dot / (mag_a * mag_b)


print(f"\n{'Query A':<45} | {'Query B':<45} | Dist   | Sim    | @ 0.90 | @ 0.80 | @ 0.75")
print("-" * 165)

for a_text, b_text in PAIRS:
    vec_a = embed(a_text)
    vec_b = embed(b_text)
    dist  = cosine_distance(vec_a, vec_b)
    sim   = 1.0 - dist

    hit_90 = "HIT " if dist <= 0.10 else "MISS"
    hit_80 = "HIT " if dist <= 0.20 else "MISS"
    hit_75 = "HIT " if dist <= 0.25 else "MISS"

    a_short = (a_text[:42] + "...") if len(a_text) > 45 else a_text
    b_short = (b_text[:42] + "...") if len(b_text) > 45 else b_text

    print(f"{a_short:<45} | {b_short:<45} | {dist:.4f} | {sim:.4f} | {hit_90}   | {hit_80}   | {hit_75}")

print()
print("Threshold guide:")
print("  0.90 -> distance <= 0.10  (very strict, near-identical phrasing only)")
print("  0.80 -> distance <= 0.20  (similar meaning, some word variation)")
print("  0.75 -> distance <= 0.25  (paraphrases, different wording same intent)")
print()
