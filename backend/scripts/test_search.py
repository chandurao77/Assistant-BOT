"""Quick test: search Qdrant for a query to verify document ingestion."""
import asyncio
from app.config import Settings
from app.services.vector_store import VectorStore
from app.services.embeddings import EmbeddingService

async def test():
    s = Settings()
    vs = VectorStore(s)
    es = EmbeddingService(s)
    q = "How do I set up VPN access as a new engineer?"
    vec = await es.embed(q)
    results = await vs.search(vec, top_k=3)
    for r in results:
        print(f"  [{r.score:.3f}] {r.title} -- {r.content[:120]}...")

asyncio.run(test())
