let abortController = null;
let generationStopped = false;
let pendingFiles = [];
let previewUrls = new Map();

const IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
]);

function setSidebarOpen(open) {
  document.body.classList.toggle("sidebar-open", open);
  const backdrop = document.getElementById("sidebar-backdrop");
  if (backdrop) backdrop.hidden = !open;
  const toggle = document.getElementById("sidebar-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    toggle.setAttribute("aria-label", open ? "Close chats" : "Open chats");
  }
}

function isDesktopLayout() {
  return window.matchMedia("(min-width: 1024px)").matches;
}

function isCoarsePointer() {
  return window.matchMedia("(pointer: coarse)").matches;
}

function syncAppViewport() {
  const viewport = window.visualViewport;
  const height = viewport?.height ?? window.innerHeight;
  const offset = viewport?.offsetTop ?? 0;
  document.documentElement.style.setProperty("--app-height", `${height}px`);
  document.documentElement.style.setProperty("--app-offset", `${offset}px`);
}

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

function fileKind(file) {
  return IMAGE_TYPES.has(file.type) ? "image" : "document";
}

function revokePreviewUrl(file) {
  const url = previewUrls.get(file);
  if (url) {
    URL.revokeObjectURL(url);
    previewUrls.delete(file);
  }
}

function clearPendingFiles() {
  for (const file of pendingFiles) revokePreviewUrl(file);
  pendingFiles = [];
  const input = document.getElementById("composer-files");
  if (input) input.value = "";
  renderAttachmentPreview();
}

function renderAttachmentPreview() {
  const container = document.getElementById("attachment-preview");
  if (!container) return;

  if (!pendingFiles.length) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }

  container.hidden = false;
  container.innerHTML = pendingFiles
    .map((file, index) => {
      const kind = fileKind(file);
      const preview =
        kind === "image"
          ? `<img src="${previewUrls.get(file) || ""}" alt="" />`
          : `<span class="attachment-doc-icon" aria-hidden="true">DOC</span>`;
      return `
        <div class="preview-item" data-index="${index}">
          ${preview}
          <span class="preview-name">${escapeHtml(file.name)}</span>
          <button type="button" class="preview-remove" aria-label="Remove ${escapeHtml(file.name)}">×</button>
        </div>
      `;
    })
    .join("");
}

function addPendingFiles(fileList) {
  const maxFiles = 5;
  const next = [...pendingFiles];
  for (const file of fileList) {
    if (next.length >= maxFiles) {
      setError(`Maximum ${maxFiles} files per message.`);
      break;
    }
    if (
      next.some(
        (existing) =>
          existing.name === file.name && existing.size === file.size,
      )
    ) {
      continue;
    }
    next.push(file);
    if (fileKind(file) === "image") {
      previewUrls.set(file, URL.createObjectURL(file));
    }
  }
  pendingFiles = next;
  setError("");
  renderAttachmentPreview();
}

function removePendingFile(index) {
  const file = pendingFiles[index];
  if (file) revokePreviewUrl(file);
  pendingFiles = pendingFiles.filter((_, i) => i !== index);
  renderAttachmentPreview();
}

function renderAttachmentsHtml(attachments) {
  if (!attachments?.length) return "";
  const items = attachments
    .map((attachment) => {
      if (attachment.kind === "image") {
        const src = attachment.previewUrl || `/attachments/${attachment.id}`;
        return `
          <a class="attachment-image" href="${src}" target="_blank" rel="noopener">
            <img class="attachment-thumb" src="${src}" alt="${escapeHtml(attachment.name)}" />
          </a>
        `;
      }
      const href = attachment.id ? `/attachments/${attachment.id}` : "#";
      const download = attachment.id ? " download" : "";
      return `
        <a class="attachment-doc" href="${href}"${download}>
          <span class="attachment-doc-icon" aria-hidden="true">DOC</span>
          <span class="attachment-doc-name">${escapeHtml(attachment.name)}</span>
        </a>
      `;
    })
    .join("");
  return `<div class="attachments">${items}</div>`;
}

function setGenerating(on) {
  document.body.classList.toggle("is-generating", on);
  const attach = document.getElementById("composer-attach");
  if (attach) attach.disabled = on;
}

function setError(message) {
  const banner = document.getElementById("error-banner");
  if (!banner) return;
  banner.innerHTML = message
    ? `<p class="error">${escapeHtml(message)}</p>`
    : "";
}

function appendUserBubble(text, attachments = []) {
  const messages = document.getElementById("messages");
  if (!messages) return null;

  const parts = [];
  if (text) {
    parts.push(`<p>${escapeHtml(text).replaceAll("\n", "<br>")}</p>`);
  }
  parts.push(renderAttachmentsHtml(attachments));

  const article = document.createElement("article");
  article.className = "bubble bubble-user";
  article.innerHTML = `<div class="bubble-body">${parts.join("")}</div>`;
  messages.appendChild(article);
  document.getElementById("empty-state")?.classList.add("is-hidden");
  scrollTranscript();
  return article;
}

function updateUserBubbleAttachments(article, attachments) {
  if (!article) return;
  const body = article.querySelector(".bubble-body");
  if (!body) return;
  body.querySelector(".attachments")?.remove();
  const html = renderAttachmentsHtml(attachments);
  if (html) body.insertAdjacentHTML("beforeend", html);
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
  if (mobile && thread?.classList.contains("is-active"))
    mobile.textContent = title;
}

function startRename(thread) {
  document
    .querySelectorAll(".thread.is-editing")
    .forEach((el) => el.classList.remove("is-editing"));
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

async function sendChat(text, files = []) {
  const content = text.trim();
  const hasFiles = files.length > 0;
  if (
    (!content && !hasFiles) ||
    document.body.classList.contains("is-generating")
  ) {
    return;
  }

  generationStopped = false;
  setError("");

  const localPreviewUrls = [];
  const optimisticAttachments = files.map((file) => {
    let previewUrl = null;
    if (fileKind(file) === "image") {
      previewUrl = URL.createObjectURL(file);
      localPreviewUrls.push(previewUrl);
    }
    return {
      name: file.name,
      kind: fileKind(file),
      previewUrl,
    };
  });

  const userBubble = appendUserBubble(content, optimisticAttachments);
  setGenerating(true);

  abortController = new AbortController();
  const body = new FormData();
  body.set("content", content);
  for (const file of files) {
    body.append("files", file);
  }

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
          userBubble?.remove();
          for (const url of localPreviewUrls) URL.revokeObjectURL(url);
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
          if (event.attachments?.length) {
            updateUserBubbleAttachments(userBubble, event.attachments);
          }
          for (const url of localPreviewUrls) URL.revokeObjectURL(url);
          if (event.thread_id && event.title) {
            updateThreadTitle(event.thread_id, event.title);
          }
        }
      }
    }
  } catch (error) {
    if (error.name !== "AbortError" && !generationStopped) {
      setError(
        "The assistant could not reply. Check your API key and try again.",
      );
      userBubble?.remove();
      for (const url of localPreviewUrls) URL.revokeObjectURL(url);
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
  if (event.key === "Enter" && !event.shiftKey && !isCoarsePointer()) {
    event.preventDefault();
    event.target.form?.requestSubmit();
  }
});

document.addEventListener("click", (event) => {
  const toggle = event.target.closest("#sidebar-toggle");
  const backdrop = event.target.closest("#sidebar-backdrop");
  const edit = event.target.closest(".thread-edit");
  const attach = event.target.closest("#composer-attach");
  const remove = event.target.closest(".preview-remove");

  if (event.target.closest("#composer-stop")) {
    stopGenerating();
    return;
  }
  if (attach) {
    document.getElementById("composer-files")?.click();
    return;
  }
  if (remove) {
    const index = Number(remove.closest(".preview-item")?.dataset.index);
    if (!Number.isNaN(index)) removePendingFile(index);
    return;
  }
  if (edit) {
    event.preventDefault();
    startRename(edit.closest(".thread"));
    return;
  }
  if (toggle) {
    setSidebarOpen(!document.body.classList.contains("sidebar-open"));
    return;
  }
  if (backdrop) {
    setSidebarOpen(false);
    return;
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id !== "composer-files") return;
  addPendingFiles(Array.from(event.target.files || []));
  event.target.value = "";
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
      const files = form.id === "composer" ? [...pendingFiles] : [];
      if (form.id === "composer") {
        form.reset();
        clearPendingFiles();
        resizeComposer();
      }
      sendChat(text, files);
    }
  },
  true,
);

document.addEventListener("htmx:afterRequest", () => {
  setSidebarOpen(false);
});

window.addEventListener("resize", () => {
  if (isDesktopLayout()) setSidebarOpen(false);
  syncAppViewport();
});

if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", syncAppViewport);
  window.visualViewport.addEventListener("scroll", syncAppViewport);
}

document.addEventListener("DOMContentLoaded", () => {
  syncAppViewport();
  scrollTranscript();
});
