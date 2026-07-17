from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from manim_studio.catalog import CatalogEntry


@dataclass(frozen=True)
class SceneBeat:
    id: str
    label: str
    line: int


@dataclass(frozen=True)
class BeatDiscoveryResult:
    ok: bool
    beats: tuple[SceneBeat, ...]
    errors: tuple[str, ...] = ()


def discover_entry_beats(repo_root: Path | str, entry: CatalogEntry) -> BeatDiscoveryResult:
    source_path = (Path(repo_root).resolve() / entry.source_path).resolve()
    return discover_scene_beats(source_path)


def discover_scene_beats(source_path: Path | str) -> BeatDiscoveryResult:
    path = Path(source_path)
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return BeatDiscoveryResult(False, (), (f"{path}: invalid Python syntax: {exc}.",))
    except OSError as exc:
        return BeatDiscoveryResult(False, (), (f"{path}: could not read source: {exc}.",))

    visitor = _BeatCallVisitor()
    visitor.visit(tree)
    errors = _duplicate_errors(visitor.beats)
    return BeatDiscoveryResult(not errors, tuple(visitor.beats), tuple(errors))


def beat_by_id(beats: Sequence[SceneBeat], beat_id: str) -> SceneBeat | None:
    for beat in beats:
        if beat.id == beat_id:
            return beat
    return None


def beats_to_json(beats: Sequence[SceneBeat]) -> list[dict[str, object]]:
    return [asdict(beat) for beat in beats]


class _BeatCallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.beats: list[SceneBeat] = []

    def visit_Call(self, node: ast.Call) -> None:
        beat = _beat_from_call(node)
        if beat is not None:
            self.beats.append(beat)
        self.generic_visit(node)


def _beat_from_call(node: ast.Call) -> SceneBeat | None:
    if not _is_self_beat_call(node):
        return None
    if not node.args:
        return None

    beat_id = _string_constant(node.args[0])
    if beat_id is None:
        return None

    label = _label_from_call(node) or beat_id
    return SceneBeat(id=beat_id, label=label, line=node.lineno)


def _is_self_beat_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "beat"
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    )


def _label_from_call(node: ast.Call) -> str | None:
    for keyword in node.keywords:
        if keyword.arg == "label":
            return _string_constant(keyword.value)

    if len(node.args) >= 2:
        return _string_constant(node.args[1])
    return None


def _string_constant(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value.strip()
        return value or None
    return None


def _duplicate_errors(beats: Sequence[SceneBeat]) -> list[str]:
    first_line_by_id: dict[str, int] = {}
    errors: list[str] = []
    for beat in beats:
        first_line = first_line_by_id.get(beat.id)
        if first_line is not None:
            errors.append(
                f"duplicate beat id {beat.id!r} at lines {first_line} and {beat.line}"
            )
            continue
        first_line_by_id[beat.id] = beat.line
    return errors
