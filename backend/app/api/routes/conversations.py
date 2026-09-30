"""REST endpoints for listing, retrieving, exporting, and deleting persisted conversations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

from app.api.dependencies import get_optional_user, require_admin

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(request: Request, user: dict | None = Depends(get_optional_user)):
    """Return conversations ordered by most-recently-updated, scoped to user."""
    store = request.app.state.conversation_store
    user_id = user["id"] if user else None
    return await store.list_conversations(user_id=user_id)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str, request: Request, user: dict | None = Depends(get_optional_user)):
    """Return metadata + ordered messages for a single conversation."""
    store = request.app.state.conversation_store
    user_id = user["id"] if user else None
    messages = await store.get_conversation_messages(conversation_id, user_id=user_id)
    if messages is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"conversation_id": conversation_id, "messages": messages}


@router.get("/{conversation_id}/export")
async def export_conversation(conversation_id: str, request: Request, user: dict | None = Depends(get_optional_user)):
    """Export a conversation as a downloadable Markdown file."""
    store = request.app.state.conversation_store
    user_id = user["id"] if user else None
    messages = await store.get_conversation_messages(conversation_id, user_id=user_id)
    if messages is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Build Markdown
    lines: list[str] = ["# Assistant Bot Conversation Export\n"]

    # Get conversation title
    convos = await store.list_conversations(user_id=user_id)
    title = conversation_id
    for c in convos:
        if c["id"] == conversation_id:
            title = c.get("title", conversation_id)
            lines.append(f"**Conversation:** {title}\n")
            lines.append(f"**Date:** {c.get('created_at', 'N/A')}\n")
            break

    lines.append("---\n")

    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            lines.append(f"## 🧑 User\n\n{content}\n")
        else:
            lines.append(f"## 🤖 Assistant Bot\n\n{content}\n")

    md_content = "\n".join(lines)
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)[:50].strip() or "conversation"
    filename = f"assistant-bot-{safe_title}.md"

    return PlainTextResponse(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/{conversation_id}")
async def rename_conversation(conversation_id: str, request: Request, user: dict | None = Depends(get_optional_user)):
    """Rename a conversation."""
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="title is required")
    store = request.app.state.conversation_store
    user_id = user["id"] if user else None
    updated = await store.rename_conversation(conversation_id, title, user_id=user_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"conversation_id": conversation_id, "title": title}


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, request: Request, user: dict | None = Depends(get_optional_user)):
    """Delete a conversation and all its messages."""
    store = request.app.state.conversation_store
    user_id = user["id"] if user else None
    deleted = await store.delete_conversation(conversation_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")


@router.delete("/user/{user_id}/purge", dependencies=[Depends(require_admin)])
async def purge_user_data(user_id: str, request: Request):
    """
    GDPR right to be forgotten — permanently delete ALL data for a user.
    Admin-only endpoint. Deletes conversations, messages, and feedback.
    """
    store = request.app.state.conversation_store
    result = await store.purge_user_data(user_id)
    if result["conversations_deleted"] == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No data found for this user")
    return result


@router.get("/user/{user_id}/export", dependencies=[Depends(require_admin)])
async def export_user_data(user_id: str, request: Request):
    """
    GDPR right of access — export ALL data for a user as JSON.
    Admin-only endpoint. Returns conversations, messages, and feedback.
    """
    store = request.app.state.conversation_store
    result = await store.export_user_data(user_id)
    if result["conversations_count"] == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No data found for this user")
    return result
