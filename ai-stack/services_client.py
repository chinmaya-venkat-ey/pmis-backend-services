"""
services_client.py
──────────────────
Ready-to-use async functions for every service in your stack.
Copy this file into your FastAPI project and import what you need.

Both Ollama and vLLM speak the OpenAI API format, so your code
doesn't need to care which backend is running — it always calls
VLLM_BASE_URL and uses LLM_MODEL. The .env + docker-compose wire
those to whichever backend is active.

From INSIDE Docker (container-to-container):
  LLM       → http://ollama:11434   or   http://vllm:8000
  Embedding → http://embedding:80
  Qdrant    → http://qdrant:6333
  OCR       → http://paddleocr:8002

From the HOST machine (curl / scripts):
  LLM       → http://localhost:11434  or  http://localhost:8000
  Embedding → http://localhost:8001
  Qdrant    → http://localhost:6333
  OCR       → http://localhost:8002
"""

import os
import httpx
import asyncio

# ── Read URLs from environment (set automatically by docker-compose) ──
LLM_URL       = os.getenv("VLLM_BASE_URL",  "http://localhost:11434")
LLM_MODEL     = os.getenv("LLM_MODEL",      "qwen3:8b")
EMBEDDING_URL = os.getenv("EMBEDDING_URL",  "http://localhost:8001")
QDRANT_URL    = os.getenv("QDRANT_URL",     "http://localhost:6333")
OCR_URL       = os.getenv("OCR_URL",        "http://localhost:8002")
QDRANT_KEY    = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_KEY} if QDRANT_KEY else {}


# ══════════════════════════════════════════════════════════
# 1. LLM  (works with both Ollama and vLLM automatically)
# ══════════════════════════════════════════════════════════

async def ask_llm(
    prompt: str,
    system: str = "You are a helpful assistant.",
    max_tokens: int = 1024,
    temperature: float = 0.7,
) -> str:
    """
    Send a message to the LLM and return its reply as a string.
    Works with Ollama and vLLM — both use the OpenAI /v1/chat/completions format.
    """
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{LLM_URL}/v1/chat/completions",
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens":  max_tokens,
                "temperature": temperature,
            }
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def stream_llm(prompt: str, system: str = "You are a helpful assistant."):
    """
    Stream the LLM response token by token.
    Use this for real-time UI (e.g. Server-Sent Events in FastAPI).

    Example FastAPI SSE route:
        from fastapi.responses import StreamingResponse
        @app.get("/chat")
        async def chat(q: str):
            return StreamingResponse(stream_llm(q), media_type="text/event-stream")
    """
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{LLM_URL}/v1/chat/completions",
            json={
                "model":    LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "stream": True,
            }
        ) as resp:
            import json
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and "[DONE]" not in line:
                    try:
                        chunk = json.loads(line[6:])
                        token = chunk["choices"][0]["delta"].get("content", "")
                        if token:
                            yield f"data: {token}\n\n"
                    except Exception:
                        pass


# ══════════════════════════════════════════════════════════
# 2. Embeddings  (text → 1024-number vector)
# ══════════════════════════════════════════════════════════

async def embed_text(text: str) -> list[float]:
    """
    Convert a single string to a 1024-dimension vector.
    Use this before storing or searching in Qdrant.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{EMBEDDING_URL}/embed", json={"inputs": text})
        r.raise_for_status()
        return r.json()


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts in one API call (faster than looping)."""
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(f"{EMBEDDING_URL}/embed", json={"inputs": texts})
        r.raise_for_status()
        return r.json()


# ══════════════════════════════════════════════════════════
# 3. Qdrant  (store and search vectors)
# ══════════════════════════════════════════════════════════

async def qdrant_create_collection(name: str, vector_size: int = 1024):
    """
    Create a collection (like a table) in Qdrant.
    Call once during setup — safe to call again, returns 409 if exists.
    vector_size must match your embedding model (BAAI-large = 1024).
    """
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{QDRANT_URL}/collections/{name}",
            headers=QDRANT_HEADERS,
            json={"vectors": {"size": vector_size, "distance": "Cosine"}}
        )
        if r.status_code not in (200, 409):
            r.raise_for_status()
        return r.json()


async def qdrant_upsert(
    collection: str,
    point_id: str,          # unique ID for this document (e.g. UUID or DB row ID)
    vector: list[float],    # from embed_text()
    payload: dict,          # any extra data you want back on search (title, url, etc.)
):
    """Store a document embedding in Qdrant."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(
            f"{QDRANT_URL}/collections/{collection}/points",
            headers=QDRANT_HEADERS,
            json={"points": [{"id": point_id, "vector": vector, "payload": payload}]}
        )
        r.raise_for_status()
        return r.json()


async def qdrant_search(
    collection: str,
    query_vector: list[float],
    top_k: int = 5,
    score_threshold: float = 0.6,
) -> list[dict]:
    """
    Find the top_k most similar documents to a query vector.
    Returns list of {id, score, payload} — payload has your original data.
    Lower score_threshold = more results but less relevant.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{QDRANT_URL}/collections/{collection}/points/search",
            headers=QDRANT_HEADERS,
            json={
                "vector":          query_vector,
                "limit":           top_k,
                "score_threshold": score_threshold,
                "with_payload":    True,
            }
        )
        r.raise_for_status()
        return r.json()["result"]


async def qdrant_delete(collection: str, point_id: str):
    """Remove a document from Qdrant by its ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{QDRANT_URL}/collections/{collection}/points/delete",
            headers=QDRANT_HEADERS,
            json={"points": [point_id]}
        )
        r.raise_for_status()


# ══════════════════════════════════════════════════════════
# 4. PaddleOCR  (extract text from images)
# ══════════════════════════════════════════════════════════

async def ocr_image(image_bytes: bytes, filename: str = "image.jpg") -> list[dict]:
    """
    Extract text from an image.
    Returns list of {text, confidence, bbox} for each detected text block.

    Example:
        with open("scan.jpg", "rb") as f:
            blocks = await ocr_image(f.read())
        full_text = " ".join(b["text"] for b in blocks)
    """
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{OCR_URL}/ocr",
            files={"file": (filename, image_bytes, "image/jpeg")}
        )
        r.raise_for_status()
        return r.json()["blocks"]


# ══════════════════════════════════════════════════════════
# 5. Complete pipelines  (combine the above)
# ══════════════════════════════════════════════════════════

async def ingest_document(
    image_bytes: bytes,
    doc_id: str,
    metadata: dict,
    collection: str = "documents",
):
    """
    Full ingest pipeline: image file → OCR → embed → store in Qdrant.
    Call this when a user uploads a document.

    Args:
        image_bytes: raw bytes of the image/scanned page
        doc_id:      unique ID (e.g. str(uuid4()) or your DB primary key)
        metadata:    dict of info to store alongside the vector
                     e.g. {"filename": "invoice.pdf", "user_id": 42}
        collection:  Qdrant collection name
    """
    # 1. Extract text from image
    blocks = await ocr_image(image_bytes)
    full_text = " ".join(b["text"] for b in blocks)

    # 2. Embed the text
    vector = await embed_text(full_text)

    # 3. Store in Qdrant
    await qdrant_upsert(
        collection=collection,
        point_id=doc_id,
        vector=vector,
        payload={**metadata, "text_preview": full_text[:500]},
    )
    return {"doc_id": doc_id, "chars_extracted": len(full_text)}


async def rag_answer(
    question: str,
    collection: str = "documents",
    top_k: int = 3,
) -> str:
    """
    RAG (Retrieval-Augmented Generation) pipeline:
      1. Search Qdrant for documents relevant to the question
      2. Pass those documents as context to the LLM
      3. Return a grounded answer

    This is the standard pattern for document Q&A chatbots.
    """
    # 1. Turn the question into a vector and search
    q_vector = await embed_text(question)
    results  = await qdrant_search(collection, q_vector, top_k=top_k)

    if not results:
        return await ask_llm(question)  # fallback: answer from LLM knowledge

    # 2. Build context from the retrieved documents
    context_parts = []
    for i, r in enumerate(results, 1):
        preview = r["payload"].get("text_preview", "")
        context_parts.append(f"[Document {i}]\n{preview}")
    context = "\n\n".join(context_parts)

    # 3. Ask the LLM to answer using the context
    prompt = (
        f"Use the following documents to answer the question.\n"
        f"If the answer is not clearly in the documents, say so.\n\n"
        f"{context}\n\n"
        f"Question: {question}"
    )
    return await ask_llm(prompt, system="You are a precise document assistant.")


# ── Quick connectivity test ────────────────────────────────
# Run this file directly to check all services are reachable:
#   python services_client.py
if __name__ == "__main__":
    async def test_all():
        print("\n=== Connectivity test ===\n")

        tests = [
            ("LLM",       ask_llm("Reply with just the word OK.")),
            ("Embedding", embed_text("hello")),
            ("Qdrant",    qdrant_create_collection("_test_")),
        ]

        for name, coro in tests:
            try:
                result = await coro
                if name == "LLM":
                    print(f"  ✓ {name}: {str(result).strip()[:60]}")
                elif name == "Embedding":
                    print(f"  ✓ {name}: vector of {len(result)} dims")
                else:
                    print(f"  ✓ {name}: ok")
            except Exception as e:
                print(f"  ✗ {name}: {e}")

        print("\nDone. Fix any ✗ errors before starting your app.\n")

    asyncio.run(test_all())
