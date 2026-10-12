import boto3
import json
import os
import uuid
from botocore.exceptions import ClientError

# --- Configuration ---
# SIMILARITY_THRESHOLD: cosine similarity required for a cache HIT.
# Cosine distance = 1.0 - similarity, so:
#   0.90 -> distance <= 0.10  (near-identical phrasing only)
#   0.80 -> distance <= 0.20  (similar meaning, some word variation)
#   0.75 -> distance <= 0.25  (paraphrases, different wording, same intent) <-- default
# Tune via the SIMILARITY_THRESHOLD Lambda environment variable.
BUCKET_NAME = os.environ.get("BUCKET_NAME", "semantic-cache-app")
INDEX_NAME = os.environ.get("INDEX_NAME", "cache-index")
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
LLM_MODEL_ID = "amazon.nova-pro-v1:0"
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "0.75"))

# --- Clients ---
bedrock = boto3.client('bedrock-runtime')
s3_vectors = boto3.client('s3vectors')


def lambda_handler(event, context):
    try:
        # 1. Parse Input
        body = json.loads(event.get('body', '{}'))
        user_prompt = body.get('prompt', '')

        if not user_prompt:
            return {"statusCode": 400, "body": json.dumps({"error": "No prompt provided"})}

        print(f"Received Prompt: {user_prompt[:50]}...")

        # 2. Create Vector Embedding for the Prompt
        prompt_vector = generate_embedding(user_prompt)

        # 3. Check S3 Vector Cache
        cached_response = check_cache(prompt_vector)

        if cached_response:
            print("CACHE HIT")
            return {
                "statusCode": 200,
                "headers": {"X-Cache-Status": "HIT"},
                "body": json.dumps({"response": cached_response})
            }

        # 4. Cache Miss - Generate New Response
        print("CACHE MISS - Invoking LLM")
        llm_response = generate_llm_response(user_prompt)

        # 5. Store in S3 Vector Cache
        save_to_cache(user_prompt, prompt_vector, llm_response)

        return {
            "statusCode": 200,
            "headers": {"X-Cache-Status": "MISS"},
            "body": json.dumps({"response": llm_response})
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}


# --- Helper Functions ---

def generate_embedding(text):
    """Generates a 1024-dim vector using Amazon Titan Embeddings v2"""
    response = bedrock.invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        body=json.dumps({"inputText": text})
    )
    response_body = json.loads(response['body'].read())
    return response_body['embedding']


def check_cache(vector):
    """
    Queries S3 Vectors using cosine distance.
    Distance = 1.0 - Similarity  →  0.0 is a perfect match.
    """
    try:
        response = s3_vectors.query_vectors(
            vectorBucketName=BUCKET_NAME,
            indexName=INDEX_NAME,
            queryVector={'float32': vector},
            topK=1,
            returnMetadata=True,
            returnDistance=True
        )

        if not response.get('vectors'):
            print("Cache is empty -> MISS")
            return None

        match = response['vectors'][0]
        distance = match.get('distance', 1.0)
        cache_threshold = 1.0 - SIMILARITY_THRESHOLD
        similarity_pct = (1.0 - distance) * 100

        print(f"Nearest neighbor distance : {distance:.4f}")
        print(f"Cosine similarity         : {similarity_pct:.1f}%")
        print(f"Required similarity       : {SIMILARITY_THRESHOLD * 100:.0f}% (distance <= {cache_threshold:.2f})")
        print(f"Matched prompt            : {match.get('metadata', {}).get('original_prompt', 'N/A')[:80]}")

        if distance <= cache_threshold:
            print("Decision: CACHE HIT")
            return match.get('metadata', {}).get('answer')

        print("Decision: CACHE MISS (similarity too low)")
        return None

    except ClientError as e:
        print(f"S3 Vector Query Error: {e}")
        return None


def save_to_cache(prompt, vector, answer):
    """Writes the new Q&A pair to S3 Vectors"""
    try:
        unique_key = str(uuid.uuid4())
        s3_vectors.put_vectors(
            vectorBucketName=BUCKET_NAME,
            indexName=INDEX_NAME,
            vectors=[{
                "key": unique_key,
                "data": {"float32": vector},
                "metadata": {
                    "original_prompt": prompt,
                    "answer": answer[:1000]
                }
            }]
        )
        print(f"Saved new vector to cache with key: {unique_key}")
    except Exception as e:
        print(f"Failed to save to cache: {e}")


def generate_llm_response(prompt):
    """Invoke Amazon Nova Pro via Bedrock"""
    body = json.dumps({
        "messages": [
            {
                "role": "user",
                "content": [{"text": prompt}]
            }
        ]
    })

    response = bedrock.invoke_model(
        modelId=LLM_MODEL_ID,
        body=body
    )

    result = json.loads(response["body"].read())
    return result["output"]["message"]["content"][0]["text"]
