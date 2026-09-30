"""Simulate exactly what the RAG pipeline does for a query."""
import asyncio
from app.config import Settings
from app.services.vector_store import VectorStore
from app.services.embeddings import EmbeddingService

async def test():
    s = Settings()
    vs = VectorStore(s)
    es = EmbeddingService(s)
    
    print(f"Settings: top_k={s.retrieval_top_k}, threshold={s.retrieval_score_threshold}, chunk_size={s.chunk_size}")
    print()
    
    for q in ["how to get confluence access", "how to Request Confluence Access"]:
        vec = await es.embed(q)
        # First search with NO threshold to see true scores
        results = await vs.search(vec, top_k=10, score_threshold=0.0)
        print(f"Q: '{q}'")
        print(f"  All results (no threshold):")
        for r in results[:8]:
            marker = " <<< MATCH" if "confluence" in r.title.lower() and "request" in r.title.lower() else ""
            print(f"    [{r.score:.3f}] {r.title}{marker}")
        
        # Now with threshold
        results_thresh = await vs.search(vec, top_k=s.retrieval_top_k, score_threshold=s.retrieval_score_threshold)
        print(f"  With threshold {s.retrieval_score_threshold}:")
        for r in results_thresh:
            print(f"    [{r.score:.3f}] {r.title}")
        print()

asyncio.run(test())
