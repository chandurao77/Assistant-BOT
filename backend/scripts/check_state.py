"""Check what chunks exist in Qdrant for the checklist."""
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
print(f"Total chunks for checklist: {len(points)}")
for p in sorted(points, key=lambda x: x.payload["chunk_index"]):
    pl = p.payload
    title = pl.get("title", "NO TITLE")
    text = pl["text"][:100].replace("\n", " ")
    idx = pl["chunk_index"]
    print(f"  [{idx}] {title}")
    print(f"       {text}")
    print()

# Also check semantic cache
try:
    info = client.get_collection("semantic_cache")
    print(f"Semantic cache points: {info.points_count}")
except Exception:
    print("Semantic cache: empty/not exists")
