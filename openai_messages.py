"""Convert stored thread messages into OpenAI Chat Completions payloads."""

from __future__ import annotations

import files


def _document_block(session_id: str, attachment: dict) -> str:
    name = attachment.get("name") or "document"
    text = files.get_extracted_text(session_id, attachment["id"])
    if not text:
        return f"--- {name} ---\n(no extractable text)"
    return f"--- {name} ---\n{text}"


def _build_user_content(session_id: str, message: dict) -> str | list[dict]:
    attachments = message.get("attachments") or []
    text = (message.get("content") or "").strip()

    doc_blocks = [
        _document_block(session_id, attachment)
        for attachment in attachments
        if attachment.get("kind") == "document"
    ]
    if doc_blocks:
        doc_section = "\n\n".join(doc_blocks)
        text = f"{text}\n\n{doc_section}".strip() if text else doc_section

    image_attachments = [
        attachment for attachment in attachments if attachment.get("kind") == "image"
    ]

    if not image_attachments:
        return text

    parts: list[dict] = []
    if text:
        parts.append({"type": "text", "text": text})
    for attachment in image_attachments:
        data_url = files.read_image_data_url(session_id, attachment["id"])
        if data_url:
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                }
            )

    if not parts:
        return text
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


def build_openai_messages(
    messages: list[dict], session_id: str
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for message in messages:
        role = message.get("role")
        if role not in {"user", "assistant"}:
            continue
        if role == "assistant":
            payload.append({"role": "assistant", "content": message.get("content", "")})
            continue

        attachments = message.get("attachments") or []
        if attachments:
            payload.append(
                {"role": "user", "content": _build_user_content(session_id, message)}
            )
        else:
            payload.append({"role": "user", "content": message.get("content", "")})
    return payload
