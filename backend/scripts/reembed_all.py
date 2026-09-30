"""Re-embed all existing documents in Qdrant using the updated embedding service (with search_document: prefix)."""
import asyncio
import uuid
from qdrant_client import QdrantClient, models as qmodels

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import Settings
from app.services.embeddings import EmbeddingService

async def main():
    settings = Settings()
    es = EmbeddingService(settings)
    client = QdrantClient(host="qdrant", port=6333)

    # Scroll all points
    points, next_offset = client.scroll(
        collection_name="confluence_docs",
        limit=100,
        with_payload=True,
        with_vectors=False,
    )

    print(f"Found {len(points)} points to re-embed")

    texts = [p.payload["text"] for p in points]
    vectors = await es.embed_batch(texts)
    print(f"Generated {len(vectors)} new embeddings with search_document: prefix")

    # Upsert with new vectors
    new_points = [
        qmodels.PointStruct(
            id=str(p.id),
            vector=vec,
            payload=p.payload,
        )
        for p, vec in zip(points, vectors)
    ]

    batch_size = 50
    for i in range(0, len(new_points), batch_size):
        batch = new_points[i:i+batch_size]
        client.upsert(
            collection_name="confluence_docs",
            points=batch,
            wait=True,
        )

    print(f"✓ Re-embedded {len(points)} points")

asyncio.run(main())
