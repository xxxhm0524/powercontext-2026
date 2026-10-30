"""Parse specs, source files and tests into retrievable chunks."""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from .models import Chunk

_SPEC_HEADING = re.compile(
    r"^##\s+(?P<spec_id>SPEC-[A-Z0-9-]+)\s*(?:[—–:-]\s*)?(?P<title>.*)$"
)


def _stable_id(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"chk_{digest}"


def parse_specs(path: Path, *, root: Path) -> list[Chunk]:
    """Split a Markdown spec file on ``## SPEC-...`` headings."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    relative = path.relative_to(root).as_posix()
    matches: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = _SPEC_HEADING.match(line.strip())
        if match:
            matches.append((index, match.group("spec_id"), match.group("title").strip()))

    chunks: list[Chunk] = []
    for position, (line_index, spec_id, title) in enumerate(matches):
        end_index = matches[position + 1][0] if position + 1 < len(matches) else len(lines)
        body_lines = lines[line_index + 1 : end_index]
        body = "\n".join(body_lines).strip()
        content = f"{spec_id} — {title}\n{body}".strip()
        chunks.append(
            Chunk(
                chunk_id=_stable_id("spec", spec_id),
                kind="spec",
                source_path=relative,
                symbol=spec_id,
                title=title,
                content=content,
                start_line=line_index + 1,
                end_line=end_index,
                metadata={"spec_id": spec_id, "heading": lines[line_index].strip()},
            )
        )
    return chunks


def _docstring_metadata(node: ast.AST) -> dict[str, object]:
    doc = ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
    metadata: dict[str, object] = {}
    if not doc:
        return metadata
    specs = re.search(r"TARGET_SPECS?\s*:\s*([^\n]+)", doc)
    if specs:
        metadata["target_specs"] = [item.strip() for item in re.split(r"[,，]", specs.group(1)) if item.strip()]
    symbols = re.search(r"TARGET_SYMBOLS?\s*:\s*([^\n]+)", doc)
    if symbols:
        metadata["target_symbols"] = [item.strip() for item in re.split(r"[,，]", symbols.group(1)) if item.strip()]
    if re.search(r"REGRESSION\s*:\s*true", doc, re.IGNORECASE):
        metadata["regression"] = True
    return metadata


def parse_python(path: Path, *, root: Path, kind: str) -> list[Chunk]:
    """Split a Python file into module, class, method and function chunks."""

    source = path.read_text(encoding="utf-8")
    relative = path.relative_to(root).as_posix()
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()
    chunks: list[Chunk] = []

    module_doc = ast.get_docstring(tree) or ""
    module_end = len(lines)
    module_content = module_doc.strip() if module_doc else f"# module {relative}"
    chunks.append(
        Chunk(
            chunk_id=_stable_id(kind, relative, "<module>"),
            kind=kind,
            source_path=relative,
            symbol="<module>",
            title=f"模块 {relative}",
            content=module_content,
            start_line=1,
            end_line=module_end,
            metadata={"module": True},
        )
    )

    def add_node(node: ast.AST, prefix: str = "") -> None:
        name = getattr(node, "name", "")
        symbol = f"{prefix}{name}" if prefix else name
        segment = ast.get_source_segment(source, node)
        if not segment:
            return
        metadata = _docstring_metadata(node)
        title = f"{kind} {symbol}"
        chunks.append(
            Chunk(
                chunk_id=_stable_id(kind, relative, symbol),
                kind=kind,
                source_path=relative,
                symbol=symbol,
                title=title,
                content=segment,
                start_line=getattr(node, "lineno", 1),
                end_line=getattr(node, "end_lineno", getattr(node, "lineno", 1)),
                metadata=metadata,
            )
        )
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add_node(child, prefix=f"{symbol}.")

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            add_node(node)
    return chunks


def load_corpus(root: Path) -> list[Chunk]:
    """Load all specs, source files and tests below one project root."""

    root = root.resolve()
    chunks: list[Chunk] = []

    specs_dir = root / "specs"
    if specs_dir.is_dir():
        for path in sorted(specs_dir.glob("*.md")):
            chunks.extend(parse_specs(path, root=root))

    src_dir = root / "src"
    if src_dir.is_dir():
        for path in sorted(src_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            chunks.extend(parse_python(path, root=root, kind="code"))

    tests_dir = root / "tests"
    if tests_dir.is_dir():
        for path in sorted(tests_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            chunks.extend(parse_python(path, root=root, kind="test"))

    return chunks
