from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from starlette.middleware.sessions import SessionMiddleware

import store
from format_message import format_message

load_dotenv()

ROOT = Path(__file__).resolve().parent
api_key = os.getenv("OPENAI_API_KEY")
model = os.getenv("OPENAI_MODEL", "gpt-5-nano")

if not api_key:
    raise ValueError("OPENAI_API_KEY is not set")

client = AsyncOpenAI(api_key=api_key)


@dataclass
class InFlight:
    generation: str = field(default_factory=lambda: uuid4().hex)
    cancelled: bool = False
    stream: object | None = None


_inflight: dict[str, InFlight] = {}

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SESSION_SECRET", "dev-session-secret"),
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))
templates.env.filters["format_message"] = format_message

STARTER_PROMPTS = [
    "Explain this project like I'm new to it",
    "Give me three ideas for a weekend side project",
    "Help me draft a concise status update",
]


def get_session_id(request: Request) -> str:
    session_id = request.session.get("sid")
    if not session_id:
        session_id = uuid4().hex
        request.session["sid"] = session_id
    store.get_or_create_session(session_id)
    return session_id


def page_context(request: Request, error: str | None = None) -> dict:
    session_id = get_session_id(request)
    thread = store.current_thread(session_id)
    return {
        "request": request,
        "thread": thread,
        "threads": store.thread_list(session_id),
        "messages": thread.messages,
        "error": error,
        "starters": STARTER_PROMPTS,
    }


async def cancel_inflight(session_id: str, generation: str | None = None) -> None:
    item = _inflight.get(session_id)
    if item is None:
        return
    if generation is not None and item.generation != generation:
        return
    item.cancelled = True
    stream = item.stream
    item.stream = None
    if stream is not None:
        close = getattr(stream, "aclose", None) or getattr(stream, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                try:
                    await result
                except Exception:
                    pass
    if _inflight.get(session_id) is item:
        _inflight.pop(session_id, None)


async def watch_disconnect(request: Request, session_id: str, generation: str) -> None:
    try:
        while True:
            if await request.is_disconnected():
                await cancel_inflight(session_id, generation)
                return
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        return


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", page_context(request))


@app.post("/chat")
async def chat(request: Request, content: str = Form("")):
    session_id = get_session_id(request)
    text = content.strip()
    if not text:
        return StreamingResponse(
            iter([sse({"error": "Write a message before sending."})]),
            media_type="text/event-stream",
        )

    await cancel_inflight(session_id)
    store.append_user_message(session_id, text)
    thread = store.current_thread(session_id)
    thread_id = thread.id
    messages = list(thread.messages)
    inflight = InFlight()
    _inflight[session_id] = inflight

    async def events():
        watcher = asyncio.create_task(
            watch_disconnect(request, session_id, inflight.generation)
        )
        collected: list[str] = []
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
            )
            inflight.stream = stream
            async for chunk in stream:
                if inflight.cancelled:
                    break
                choice = chunk.choices[0] if chunk.choices else None
                delta = getattr(getattr(choice, "delta", None), "content", None) or ""
                if not delta:
                    continue
                collected.append(delta)
                yield sse({"text": delta})
            if inflight.cancelled:
                yield sse({"stopped": True})
                return
            reply = "".join(collected).strip()
            if not reply:
                yield sse(
                    {
                        "error": "The assistant could not reply. Check your API key and try again."
                    }
                )
                return
            store.append_assistant_message(session_id, reply, thread_id)
            current = store.current_thread(session_id)
            title = current.title if current.id == thread_id else thread.title
            yield sse(
                {
                    "done": True,
                    "html": format_message(reply),
                    "title": title,
                    "thread_id": thread_id,
                }
            )
        except asyncio.CancelledError:
            yield sse({"stopped": True})
        except Exception:
            yield sse(
                {
                    "error": "The assistant could not reply. Check your API key and try again."
                }
            )
        finally:
            inflight.stream = None
            watcher.cancel()
            if _inflight.get(session_id) is inflight:
                _inflight.pop(session_id, None)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/stop")
async def stop_chat(request: Request):
    await cancel_inflight(get_session_id(request))
    return Response(status_code=204)


@app.post("/threads/new")
def create_thread(request: Request):
    store.new_thread(get_session_id(request))
    return RedirectResponse("/", status_code=303)


@app.post("/threads/{thread_id}/select")
def select_thread(request: Request, thread_id: str):
    if store.select_thread(get_session_id(request), thread_id) is None:
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.post("/threads/{thread_id}/rename", response_class=HTMLResponse)
def rename_thread(request: Request, thread_id: str, title: str = Form("")):
    try:
        renamed = store.rename_thread(get_session_id(request), thread_id, title)
    except store.DuplicateTitleError:
        return JSONResponse(
            {"error": "A chat already has that name."},
            status_code=409,
        )
    if renamed is None:
        return JSONResponse({"error": "Enter a chat name."}, status_code=400)
    return templates.TemplateResponse(
        request, "partials/sidebar.html", page_context(request)
    )


@app.post("/threads/{thread_id}/delete")
def remove_thread(request: Request, thread_id: str):
    store.delete_thread(get_session_id(request), thread_id)
    return RedirectResponse("/", status_code=303)
