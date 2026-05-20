#!/usr/bin/env python3
from __future__ import annotations

import html
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "md"
TARGET_DIR = ROOT / "html"


def render_inline(text: str) -> str:
    escaped = html.escape(text)
    parts: list[str] = []
    in_code = False
    buffer = ""
    for ch in escaped:
        if ch == "`":
            if in_code:
                parts.append(f"<code>{buffer}</code>")
            else:
                parts.append(buffer)
            buffer = ""
            in_code = not in_code
            continue
        buffer += ch
    if in_code:
        parts.append("`" + buffer)
    else:
        parts.append(buffer)
    return "".join(parts)


def render_markdown(markdown_text: str, title: str) -> str:
    lines = markdown_text.splitlines()
    body: list[str] = []
    paragraph: list[str] = []
    list_stack: list[str] = []
    in_code_block = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            text = " ".join(part.strip() for part in paragraph if part.strip())
            body.append(f"<p>{render_inline(text)}</p>")
            paragraph = []

    def flush_lists() -> None:
        nonlocal list_stack
        while list_stack:
            body.append(f"</{list_stack.pop()}>")

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            code = html.escape("\n".join(code_lines))
            body.append(f"<pre><code>{code}</code></pre>")
            code_lines = []

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_paragraph()
            flush_lists()
            if in_code_block:
                flush_code()
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        if not stripped:
            flush_paragraph()
            flush_lists()
            continue

        if stripped.startswith("#"):
            flush_paragraph()
            flush_lists()
            level = len(stripped) - len(stripped.lstrip("#"))
            text = stripped[level:].strip()
            tag = f"h{min(level, 3)}"
            if tag == "h2":
                body.append("<section>")
            body.append(f"<{tag}>{html.escape(text)}</{tag}>")
            continue

        if stripped.startswith("- "):
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ul":
                flush_lists()
                body.append("<ul>")
                list_stack.append("ul")
            body.append(f"<li>{render_inline(stripped[2:].strip())}</li>")
            continue

        if len(stripped) > 3 and stripped[0].isdigit() and stripped[1:3] == ". ":
            flush_paragraph()
            if not list_stack or list_stack[-1] != "ol":
                flush_lists()
                body.append("<ol>")
                list_stack.append("ol")
            body.append(f"<li>{render_inline(stripped[3:].strip())}</li>")
            continue

        paragraph.append(stripped)

    flush_paragraph()
    flush_lists()
    flush_code()

    rendered: list[str] = []
    open_sections = 0
    for entry in body:
        if entry == "<section>":
            if open_sections:
                rendered.append("</section>")
            rendered.append("<section>")
            open_sections = 1
            continue
        rendered.append(entry)
    if open_sections:
        rendered.append("</section>")

    body_html = "\n    ".join(rendered)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f4efe6;
      --panel: #fffdf8;
      --ink: #1f2933;
      --muted: #5f6b76;
      --line: #d7cfbf;
      --accent: #2f6f63;
      --accent-soft: #dfeee9;
      --code: #f2ede2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Noto Sans", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, #d8ebe3 0, transparent 28rem),
        linear-gradient(180deg, #f8f5ee 0%, var(--bg) 100%);
      line-height: 1.65;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      padding: 36px 20px 72px;
    }}
    header {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 28px;
      box-shadow: 0 12px 32px rgba(31, 41, 51, 0.06);
      margin-bottom: 18px;
    }}
    h1, h2, h3 {{ line-height: 1.2; margin: 0 0 12px; }}
    h1 {{ font-size: clamp(2rem, 4vw, 3rem); }}
    h2 {{ font-size: 1.45rem; margin-top: 0; }}
    h3 {{ font-size: 1.1rem; }}
    p {{ margin: 0 0 12px; }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 22px;
      margin-top: 18px;
      box-shadow: 0 10px 28px rgba(31, 41, 51, 0.04);
    }}
    code {{
      font-family: "Cascadia Code", "Fira Code", monospace;
      font-size: 0.95em;
      background: var(--code);
      padding: 0.12em 0.35em;
      border-radius: 6px;
    }}
    pre {{
      margin: 12px 0 0;
      overflow-x: auto;
      background: var(--code);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      white-space: pre-wrap;
    }}
    pre code {{ background: transparent; padding: 0; }}
    ul, ol {{ margin: 10px 0 0 20px; padding: 0; }}
    li + li {{ margin-top: 6px; }}
    .eyebrow {{
      display: inline-block;
      margin-bottom: 10px;
      padding: 5px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .lead {{
      color: var(--muted);
      max-width: 48rem;
      font-size: 1.05rem;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <div class="eyebrow">ofpm Docs</div>
      <h1>{html.escape(title)}</h1>
      <p class="lead">Human-friendly reference generated from the Markdown source under <code>docs/md/</code>.</p>
    </header>
    {body_html}
  </main>
</body>
</html>
"""


def render_file(source_path: Path, target_path: Path) -> None:
    title = source_path.stem.replace("-", " ").title()
    markdown_text = source_path.read_text(encoding="utf-8")
    html_text = render_markdown(markdown_text, title)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(html_text, encoding="utf-8")


def main() -> int:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(SOURCE_DIR.glob("*.md")):
        target_path = TARGET_DIR / f"{source_path.stem}.html"
        render_file(source_path, target_path)
        print(f"rendered {target_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
