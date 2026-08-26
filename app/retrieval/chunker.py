import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

TARGET_WORDS = 180
MAX_WORDS = 260


@dataclass
class Chunk:
    id: str
    tenant: str
    source: str  # filename
    title: str  # frontmatter title
    topic: str
    office: str
    heading: str  # e.g. "Proof of registration › When it is blocked"
    text: str


def parse_frontmatter(raw: str) -> Tuple[dict, str]:
    if not raw.startswith("---"):
        return {}, raw
    _, fm, body = raw.split("---", 2)
    meta = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, body


def chunk_file(path: Path, tenant: str) -> List[Chunk]:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    title = meta.get("title", path.stem)

    chunks: List[Chunk] = []
    current_heading = title
    buffer: List[str] = []
    n = 0

    def flush():
        nonlocal buffer, n
        if not buffer:
            return
        text = " ".join(buffer).strip()
        if text:
            chunks.append(
                Chunk(
                    id=f"{tenant}:{path.stem}:{len(chunks)}",
                    tenant=tenant,
                    source=path.name,
                    title=title,
                    topic=meta.get("topic", path.stem),
                    office=meta.get("office", "registrar"),
                    heading=current_heading,
                    text=text,
                )
            )
        buffer, n = [], 0

    for line in body.splitlines():
        if re.match(r"^#{1,6}\s", line):
            flush()
            current_heading = f"{title} › {line.lstrip('# ').strip()}"
            continue
        words = len(line.split())
        if n + words > MAX_WORDS:
            flush()
        buffer.append(line)
        n += words
        if n >= TARGET_WORDS:
            flush()

    flush()
    return chunks
