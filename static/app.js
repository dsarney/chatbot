let abortController = null;
let generationStopped = false;

function resizeComposer() {
  const ta = document.getElementById("composer-input");
  if (!ta) return;
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
}

function scrollTranscript() {
  const transcript = document.getElementById("transcript");
  if (transcript) transcript.scrollTop = transcript.scrollHeight;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setGenerating(on) {
  document.body.classList.toggle("is-generating", on);
}

function setError(message) {
  const banner = document.getElementById("error-banner");
  if (!banner) return;
  banner.innerHTML = message ? `<p class="error">${escapeHtml(message)}</p>` : "";
}

function appendUserBubble(text) {
  const messages = document.getElementById("messages");
  if (!messages) return;
  const article = document.createElement("article");
  article.className = "bubble bubble-user";
  article.innerHTML = `<div class="bubble-body"><p>${escapeHtml(text).replaceAll("\n", "<br>")}</p></div>`;
  messages.appendChild(article);
  document.getElementById("empty-state")?.classList.add("is-hidden");
  scrollTranscript();
}

function appendAssistantBubble() {
  const messages = document.getElementById("messages");
  const article = document.createElement("article");
  article.className = "bubble bubble-assistant";
  article.innerHTML = `
    <div class="avatar" aria-hidden="true">A</div>
    <div class="bubble-body is-streaming"></div>
  `;
  messages.appendChild(article);
  scrollTranscript();
  return article.querySelector(".bubble-body");
}

function updateThreadTitle(threadId, title) {
  const thread = document.querySelector(`[data-thread-id="${threadId}"]`);
  const button = thread?.querySelector(".thread-select button");
  if (button) button.textContent = title;
  const input = thread?.querySelector(".thread-rename input");
  if (input) input.value = title;
  const mobile = document.querySelector(".mobile-title");
  if (mobile && thread?.classList.contains("is-active")) mobile.textContent = title;
}

function startRename(thread) {
  document.querySelectorAll(".thread.is-editing").forEach((el) => el.classList.remove("is-editing"));
  thread.classList.add("is-editing");
  clearRenameError(thread);
  const input = thread.querySelector(".thread-rename input");
  input?.focus();
  input?.select();
}

function clearRenameError(thread) {
  const input = thread.querySelector(".thread-rename input");
  const error = thread.querySelector(".rename-error");
  input?.classList.remove("is-invalid");
  if (error) {
    error.hidden = true;
    error.classList.remove("is-visible");
    error.textContent = "";
  }
}

function showRenameError(thread, message) {
  thread.classList.add("is-editing");
  const input = thread.querySelector(".thread-rename input");
  const error = thread.querySelector(".rename-error");
  input?.classList.add("is-invalid");
  if (error) {
    error.hidden = false;
    error.classList.add("is-visible");
    error.textContent = message;
  }
  input?.focus();
  input?.select();
}

async function saveRename(form) {
  const thread = form.closest(".thread");
  const title = form.querySelector("[name=title]")?.value ?? "";
  const body = new FormData();
  body.set("title", title);
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body,
      credentials: "same-origin",
    });
    if (response.status === 409 || response.status === 400) {
      let message = "A chat already has that name.";
      try {
        message = (await response.json()).error || message;
      } catch {
        /* keep default */
      }
      showRenameError(thread, message);
      return;
    }
    if (!response.ok) {
      showRenameError(thread, "Could not rename this chat.");
      return;
    }
    const html = await response.text();
    const sidebar = document.getElementById("sidebar");
    if (sidebar) sidebar.outerHTML = html;
    if (window.htmx) htmx.process(document.getElementById("sidebar"));
  } catch {
    showRenameError(thread, "Could not rename this chat.");
  }
}

function stopGenerating() {
  generationStopped = true;
  abortController?.abort();
  fetch("/chat/stop", { method: "POST", credentials: "same-origin" });
  setGenerating(false);
}

async function sendChat(text) {
  const content = text.trim();
  if (!content || document.body.classList.contains("is-generating")) return;

  generationStopped = false;
  setError("");
  appendUserBubble(content);
  setGenerating(true);

  abortController = new AbortController();
  const body = new FormData();
  body.set("content", content);

  let bodyEl = null;
  let raw = "";

  try {
    const response = await fetch("/chat", {
      method: "POST",
      body,
      credentials: "same-origin",
      signal: abortController.signal,
    });
    if (!response.ok || !response.body) {
      throw new Error("bad response");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part
          .split("\n")
          .filter((line) => line.startsWith("data: "))
          .map((line) => line.slice(6))
          .join("");
        if (!dataLine) continue;
        const event = JSON.parse(dataLine);
        if (event.error) {
          setError(event.error);
          bodyEl?.closest("article")?.remove();
          return;
        }
        if (event.stopped || generationStopped) return;
        if (event.text) {
          if (!bodyEl) bodyEl = appendAssistantBubble();
          raw += event.text;
          bodyEl.textContent = raw;
          scrollTranscript();
        }
        if (event.done) {
          if (!bodyEl) bodyEl = appendAssistantBubble();
          bodyEl.classList.remove("is-streaming");
          bodyEl.innerHTML = event.html;
          if (event.thread_id && event.title) updateThreadTitle(event.thread_id, event.title);
        }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError" && !generationStopped) {
      setError("The assistant could not reply. Check your API key and try again.");
      bodyEl?.closest("article")?.remove();
    }
  } finally {
    setGenerating(false);
    abortController = null;
  }
}

document.addEventListener("input", (event) => {
  if (event.target.id === "composer-input") resizeComposer();
  if (event.target.closest(".thread-rename")) {
    clearRenameError(event.target.closest(".thread"));
  }
});

document.addEventListener("keydown", (event) => {
  if (event.target.closest(".thread-rename")) {
    if (event.key === "Escape") {
      event.target.closest(".thread")?.classList.remove("is-editing");
    }
    return;
  }
  if (event.target.id !== "composer-input") return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    event.target.form?.requestSubmit();
  }
});

document.addEventListener("click", (event) => {
  const toggle = event.target.closest("#sidebar-toggle");
  const backdrop = event.target.closest("#sidebar-backdrop");
  const edit = event.target.closest(".thread-edit");
  if (event.target.closest("#composer-stop")) {
    stopGenerating();
    return;
  }
  if (edit) {
    event.preventDefault();
    startRename(edit.closest(".thread"));
    return;
  }
  if (toggle) {
    document.body.classList.toggle("sidebar-open");
    const el = document.getElementById("sidebar-backdrop");
    if (el) el.hidden = !document.body.classList.contains("sidebar-open");
  }
  if (backdrop) {
    document.body.classList.remove("sidebar-open");
    backdrop.hidden = true;
  }
});

document.addEventListener(
  "submit",
  (event) => {
    const form = event.target;
    if (form?.classList?.contains("thread-rename")) {
      event.preventDefault();
      event.stopImmediatePropagation();
      saveRename(form);
      return;
    }
    if (form?.id === "composer" || form?.querySelector(".starter")) {
      event.preventDefault();
      const input = form.querySelector("[name=content]");
      const text = input?.value ?? "";
      if (form.id === "composer") {
        form.reset();
        resizeComposer();
      }
      sendChat(text);
    }
  },
  true
);

document.addEventListener("htmx:afterRequest", () => {
  document.body.classList.remove("sidebar-open");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (backdrop) backdrop.hidden = true;
});

document.addEventListener("DOMContentLoaded", scrollTranscript);
