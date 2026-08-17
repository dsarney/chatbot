# Chatbot

A small OpenAI chat app with a FastAPI UI. Conversations are multi-turn and stored in memory for the browser session (they reset when the server restarts).

## Clone

```bash
git clone https://github.com/dsarney/chatbot.git
cd chatbot
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirement.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`. Optionally set `OPENAI_MODEL` and `SESSION_SECRET`.

For file uploads, use a **vision-capable model** (for example `gpt-4o-mini`) if you plan to send images.

Optional upload limits (defaults shown in `.env.example`):

- `MAX_UPLOAD_BYTES` — max size per file (default 10 MB)
- `MAX_FILES_PER_MESSAGE` — max attachments per message (default 5)
- `MAX_EXTRACTED_CHARS` — max extracted document text sent to the model (default 80,000)

## Run

```bash
uvicorn main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000).

## File uploads

Attach files from the paperclip button in the composer:

| Type      | Formats             | How the assistant uses them                               |
| --------- | ------------------- | --------------------------------------------------------- |
| Images    | PNG, JPG, WEBP, GIF | Sent as vision input to the model                         |
| Documents | TXT, PDF, DOCX      | Text is extracted server-side and included in the message |

Uploads are stored on disk under `uploads/` for the current browser session. Like chat history, they are ephemeral and are lost when the server restarts.
