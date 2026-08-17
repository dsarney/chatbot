"""In-memory chat sessions and threads for the current process.

Each browser session maps to a SessionState of named threads. Titles are
unique within a session (case-insensitive). Thread order is insertion
order, with the most recently messaged thread last so thread_list() can
return newest-first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4


class DuplicateTitleError(ValueError):
    """Raised when a rename would collide with another thread in the session."""


@dataclass
class Thread:
    id: str
    title: str = "New chat"
    # When True, skip auto-titling from the first user message.
    manual_title: bool = False
    messages: list[dict] = field(default_factory=list)


@dataclass
class SessionState:
    current_id: str
    threads: dict[str, Thread]


_lock = Lock()
_sessions: dict[str, SessionState] = {}


def _normalize_title(title: str, limit: int = 48) -> str:
    """Collapse whitespace and truncate, adding an ellipsis when cut."""
    cleaned = " ".join(title.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def _title_taken(
    state: SessionState, title: str, exclude_id: str | None = None
) -> bool:
    key = title.casefold()
    return any(
        thread.title.casefold() == key and thread.id != exclude_id
        for thread in state.threads.values()
    )


def unique_title(
    state: SessionState, desired: str, exclude_id: str | None = None
) -> str:
    """Return desired (normalized) or 'New chat 2', 'New chat 3', … if taken."""
    base = _normalize_title(desired) or "New chat"
    if not _title_taken(state, base, exclude_id):
        return base
    n = 2
    while True:
        suffix = f" {n}"
        # Leave room for the suffix so the full title still fits the 48-char cap.
        room = max(1, 48 - len(suffix))
        candidate = _normalize_title(desired, room) + suffix
        if not _title_taken(state, candidate, exclude_id):
            return candidate
        n += 1


def _new_thread(state: SessionState | None = None) -> Thread:
    thread = Thread(id=uuid4().hex)
    if state is not None:
        thread.title = unique_title(state, "New chat")
    return thread


def get_or_create_session(session_id: str) -> SessionState:
    """Return existing session state, or create one with a blank thread."""
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            thread = Thread(id=uuid4().hex)
            state = SessionState(current_id=thread.id, threads={thread.id: thread})
            _sessions[session_id] = state
        return state


def current_thread(session_id: str) -> Thread:
    """Return the active thread, creating a replacement if the id is missing."""
    state = get_or_create_session(session_id)
    thread = state.threads.get(state.current_id)
    if thread is None:
        thread = _new_thread(state)
        state.threads[thread.id] = thread
        state.current_id = thread.id
    return thread


def thread_list(session_id: str) -> list[Thread]:
    """Threads newest-first (dict insertion order, reversed)."""
    state = get_or_create_session(session_id)
    return list(reversed(list(state.threads.values())))


def new_thread(session_id: str) -> Thread:
    """Create a thread, select it, and return it."""
    state = get_or_create_session(session_id)
    thread = _new_thread(state)
    with _lock:
        state.threads[thread.id] = thread
        state.current_id = thread.id
    return thread


def select_thread(session_id: str, thread_id: str) -> Thread | None:
    state = get_or_create_session(session_id)
    thread = state.threads.get(thread_id)
    if thread is None:
        return None
    state.current_id = thread_id
    return thread


def delete_thread(session_id: str, thread_id: str) -> Thread:
    """Remove a thread. Always leaves one thread selected (creates one if empty)."""
    state = get_or_create_session(session_id)
    with _lock:
        state.threads.pop(thread_id, None)
        if not state.threads:
            thread = _new_thread(state)
            state.threads[thread.id] = thread
            state.current_id = thread.id
            return thread
        if state.current_id == thread_id or state.current_id not in state.threads:
            state.current_id = next(reversed(state.threads))
        return state.threads[state.current_id]


def append_user_message(
    session_id: str,
    content: str,
    attachments: list[dict] | None = None,
) -> Thread:
    """Append a user message and auto-title from it if the thread is still untitled.

    Re-inserts the thread at the end of the dict so it sorts as most recent.
    """
    thread = current_thread(session_id)
    state = get_or_create_session(session_id)
    attachment_list = attachments or []
    with _lock:
        if not thread.messages and not thread.manual_title:
            title_source = content.strip().replace("\n", " ")
            if not title_source and attachment_list:
                title_source = attachment_list[0].get("name", "New chat")
            if title_source:
                thread.title = unique_title(state, title_source, exclude_id=thread.id)
        message: dict = {"role": "user", "content": content}
        if attachment_list:
            message["attachments"] = attachment_list
        thread.messages.append(message)
        # Pop + reinsert so this thread is last in insertion order (newest).
        state.threads.pop(thread.id)
        state.threads[thread.id] = thread
    return thread


def append_assistant_message(
    session_id: str, content: str, thread_id: str | None = None
) -> Thread | None:
    """Append an assistant reply to thread_id, or to the current thread if omitted."""
    state = get_or_create_session(session_id)
    thread = state.threads.get(thread_id) if thread_id else current_thread(session_id)
    if thread is None:
        return None
    with _lock:
        thread.messages.append({"role": "assistant", "content": content})
    return thread


def rename_thread(session_id: str, thread_id: str, title: str) -> Thread | None:
    """Set a manual title. Returns None if empty; raises if the name is taken."""
    state = get_or_create_session(session_id)
    thread = state.threads.get(thread_id)
    if thread is None:
        return None
    cleaned = _normalize_title(title)
    if not cleaned:
        return None
    with _lock:
        if _title_taken(state, cleaned, exclude_id=thread_id):
            raise DuplicateTitleError(cleaned)
        thread.title = cleaned
        thread.manual_title = True
    return thread
