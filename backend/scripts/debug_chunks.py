"""Debug: show what chunks exist in Qdrant for the New Engineer Checklist."""
import asyncio
from qdrant_client import QdrantClient

async def main():
    client = QdrantClient(host="qdrant", port=6333)
    results = client.scroll(
        collection_name="confluence_docs",
        scroll_filter={"must": [{"key": "page_id", "match": {"value": "local_new_engineer_checklist"}}]},
        limit=10,
        with_payload=True,
        with_vectors=False,
    )
    points, _ = results
    for p in points:
        payload = p.payload
        print(f"\n=== Chunk {payload['chunk_index']}/{payload['total_chunks']} ===")
        print(f"Title: {payload['title']}")
        text = payload['text']
        print(f"Length: {len(text)} chars")
        print(f"First 200 chars: {text[:200]}")
        print(f"Last 200 chars: {text[-200:]}")
        if "confluence" in text.lower():
            print(">>> CONTAINS 'confluence' <<<")
        else:
            print(">>> Does NOT contain 'confluence' <<<")

asyncio.run(main())
