from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4


class DuplicateTitleError(ValueError):
    pass


@dataclass
class Thread:
    id: str
    title: str = "New chat"
    manual_title: bool = False
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass
class SessionState:
    current_id: str
    threads: dict[str, Thread]


_lock = Lock()
_sessions: dict[str, SessionState] = {}


def _normalize_title(title: str, limit: int = 48) -> str:
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
    base = _normalize_title(desired) or "New chat"
    if not _title_taken(state, base, exclude_id):
        return base
    n = 2
    while True:
        suffix = f" {n}"
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
    with _lock:
        state = _sessions.get(session_id)
        if state is None:
            thread = Thread(id=uuid4().hex)
            state = SessionState(current_id=thread.id, threads={thread.id: thread})
            _sessions[session_id] = state
        return state


def current_thread(session_id: str) -> Thread:
    state = get_or_create_session(session_id)
    thread = state.threads.get(state.current_id)
    if thread is None:
        thread = _new_thread(state)
        state.threads[thread.id] = thread
        state.current_id = thread.id
    return thread


def thread_list(session_id: str) -> list[Thread]:
    state = get_or_create_session(session_id)
    return list(reversed(list(state.threads.values())))


def new_thread(session_id: str) -> Thread:
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


def append_user_message(session_id: str, content: str) -> Thread:
    thread = current_thread(session_id)
    state = get_or_create_session(session_id)
    with _lock:
        if not thread.messages and not thread.manual_title:
            title = content.strip().replace("\n", " ")
            thread.title = unique_title(state, title, exclude_id=thread.id)
        thread.messages.append({"role": "user", "content": content})
        state.threads.pop(thread.id)
        state.threads[thread.id] = thread
    return thread


def append_assistant_message(
    session_id: str, content: str, thread_id: str | None = None
) -> Thread | None:
    state = get_or_create_session(session_id)
    thread = state.threads.get(thread_id) if thread_id else current_thread(session_id)
    if thread is None:
        return None
    with _lock:
        thread.messages.append({"role": "assistant", "content": content})
    return thread


def rename_thread(session_id: str, thread_id: str, title: str) -> Thread | None:
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
