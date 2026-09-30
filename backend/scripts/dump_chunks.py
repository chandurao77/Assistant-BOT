"""Dump all chunks for a given page_id from Qdrant."""
from qdrant_client import QdrantClient

client = QdrantClient(host="qdrant", port=6333)
results = client.scroll(
    collection_name="confluence_docs",
    scroll_filter={"must": [{"key": "page_id", "match": {"value": "local_new_engineer_checklist"}}]},
    limit=20,
    with_payload=True,
    with_vectors=False,
)
points, _ = results
for p in sorted(points, key=lambda x: x.payload["chunk_index"]):
    pl = p.payload
    idx = pl["chunk_index"]
    total = pl["total_chunks"]
    text = pl["text"]
    has_confluence = "confluence" in text.lower()
    print(f"--- Chunk {idx}/{total} ({len(text)} chars) {'[HAS CONFLUENCE]' if has_confluence else ''} ---")
    print(text[:300])
    print()
