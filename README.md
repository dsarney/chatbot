# Chatbot

A small OpenAI chat app with a FastAPI UI. Conversations are multi-turn and stored in memory for the browser session (they reset when the server restarts).

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirement.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Optionally set `OPENAI_MODEL` and `SESSION_SECRET`.

## Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).
