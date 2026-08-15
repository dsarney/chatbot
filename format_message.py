from __future__ import annotations

import html
import re

_FENCE = re.compile(r"```(?:\w+)?\n(.*?)```", re.DOTALL)
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_UL = re.compile(r"(?:^|\n)(?:[-*] .+(?:\n[-*] .+)*)")


def format_message(text: str) -> str:
    fences: list[str] = []

    def stash(match: re.Match[str]) -> str:
        fences.append(f"<pre><code>{html.escape(match.group(1).rstrip())}</code></pre>")
        return f"@@FENCE{len(fences) - 1}@@"

    working = _FENCE.sub(stash, text)
    working = html.escape(working)
    working = _BOLD.sub(r"<strong>\1</strong>", working)

    def lists(match: re.Match[str]) -> str:
        items = [
            f"<li>{line[2:].strip()}</li>"
            for line in match.group(0).strip().splitlines()
            if line.startswith(("- ", "* "))
        ]
        return "\n<ul>" + "".join(items) + "</ul>"

    working = _UL.sub(lists, working)

    blocks = []
    for chunk in working.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("<ul>") or chunk.startswith("@@FENCE"):
            blocks.append(chunk)
        else:
            blocks.append(f"<p>{chunk.replace(chr(10), '<br>')}</p>")

    rendered = "\n".join(blocks) or "<p></p>"
    for i, fence in enumerate(fences):
        rendered = rendered.replace(f"@@FENCE{i}@@", fence)
    return rendered
