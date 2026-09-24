"""Pure integrity rules for the schema 1.2 ``diagram`` block.

One implementation of the rules serves the parser (after a diagram's raw shape
checked clean) and validation (for ``Guide`` values built in memory). Every
function here is pure: a ``Diagram`` and a JSON path in, plain tuples out.
"""

from __future__ import annotations

from collections import deque
import re
from typing import Iterator

from .model import Diagram

ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

KIND_LABELS = {
    "flow": "Flow diagram",
    "concept_map": "Concept map",
    "comparison": "Comparison",
    "timeline": "Timeline",
}

#: The fields each kind requires; any other kind field is foreign to it.
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "flow": ("nodes", "edges"),
    "concept_map": ("hub", "nodes", "edges"),
    "timeline": ("events",),
    "comparison": ("items", "criteria"),
}
ALL_KIND_FIELDS = ("hub", "nodes", "edges", "events", "items", "criteria")

#: Inclusive (minimum, maximum) element counts per kind array.
ARRAY_BOUNDS: dict[str, dict[str, tuple[int, int]]] = {
    "flow": {"nodes": (2, 12), "edges": (1, 16)},
    "concept_map": {"nodes": (2, 12), "edges": (1, 12)},
    "timeline": {"events": (2, 10)},
    "comparison": {"items": (2, 4), "criteria": (1, 8)},
}

TITLE_LIMIT = 120
CAPTION_LIMIT = 240
LABEL_LIMIT = 48
SHORT_LIMIT = 32
DETAIL_LIMIT = 240

LINE_BREAKS = ("\n", "\r", " ", " ")

Finding = tuple[str, str, str]


def diagram_findings(block: Diagram, base: str) -> tuple[Finding, ...]:
    """Return every ``(code, absolute_path, message)`` rule failure of ``block``."""

    if block.kind not in KIND_FIELDS:
        return (("schema.invalid_value", f"{base}/kind", "invalid diagram kind"),)
    own = KIND_FIELDS[block.kind]
    return (
        *_cardinality(block, base),
        *_local_ids(block, base, own),
        *_texts(block, base),
        *_edge_rules(block, base),
        *_value_keys(block, base),
        *_foreign_fields(block, base, own),
    )


def back_edge_indices(block: Diagram) -> frozenset[int]:
    """Indices of the edges a depth-first walk in document order meets as back edges."""

    outgoing: dict[str, list[tuple[int, str]]] = {node.id: [] for node in block.nodes}
    for index, edge in enumerate(block.edges):
        if edge.from_id in outgoing:
            outgoing[edge.from_id].append((index, edge.to_id))
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(outgoing, white)
    back: set[int] = set()

    def visit(node: str) -> None:
        colour[node] = grey
        for index, target in outgoing[node]:
            state = colour.get(target)
            if state == grey:
                back.add(index)
            elif state == white:
                visit(target)
        colour[node] = black

    for node in outgoing:
        if colour[node] == white:
            visit(node)
    return frozenset(back)


def _cardinality(block: Diagram, base: str) -> Iterator[Finding]:
    for name, (minimum, maximum) in ARRAY_BOUNDS[block.kind].items():
        if not minimum <= len(getattr(block, name)) <= maximum:
            yield (
                "schema.cardinality",
                f"{base}/{name}",
                f"must contain {minimum}–{maximum} items",
            )


def _local_ids(block: Diagram, base: str, own: tuple[str, ...]) -> Iterator[Finding]:
    first: dict[str, str] = {}
    for name in ("nodes", "events", "items", "criteria"):
        if name not in own:
            continue
        for index, element in enumerate(getattr(block, name)):
            path = f"{base}/{name}/{index}/id"
            if not ID_RE.fullmatch(element.id):
                yield ("schema.invalid_id", path, "must match ^[a-z][a-z0-9-]{0,63}$")
            if element.id in first:
                yield (
                    "diagram.duplicate_id",
                    path,
                    f"duplicates diagram ID first declared at {first[element.id]}",
                )
            else:
                first[element.id] = path


def _text_limits(block: Diagram, base: str) -> Iterator[tuple[str, str | None, int]]:
    """Every diagram text of ``block``'s kind as ``(path, value, limit)``."""

    yield f"{base}/title", block.title, TITLE_LIMIT
    yield f"{base}/caption", block.caption, CAPTION_LIMIT
    if block.kind in {"flow", "concept_map"}:
        for i, node in enumerate(block.nodes):
            yield f"{base}/nodes/{i}/label", node.label, LABEL_LIMIT
            yield f"{base}/nodes/{i}/detail", node.detail, DETAIL_LIMIT
        for i, edge in enumerate(block.edges):
            yield f"{base}/edges/{i}/label", edge.label, SHORT_LIMIT
    elif block.kind == "timeline":
        for i, event in enumerate(block.events):
            yield f"{base}/events/{i}/when", event.when, SHORT_LIMIT
            yield f"{base}/events/{i}/label", event.label, LABEL_LIMIT
            yield f"{base}/events/{i}/detail", event.detail, DETAIL_LIMIT
    else:
        for i, item in enumerate(block.items):
            yield f"{base}/items/{i}/label", item.label, LABEL_LIMIT
        for i, criterion in enumerate(block.criteria):
            yield f"{base}/criteria/{i}/label", criterion.label, LABEL_LIMIT
            for value in criterion.values:
                path = f"{base}/criteria/{i}/values/{value.item_id}"
                yield path, value.text, DETAIL_LIMIT


def _texts(block: Diagram, base: str) -> Iterator[Finding]:
    for path, value, limit in _text_limits(block, base):
        if value is None:
            continue
        if len(value.strip()) > limit:
            yield ("diagram.text_too_long", path, f"must not exceed {limit} characters")
        if any(mark in value for mark in LINE_BREAKS):
            yield ("diagram.multiline_text", path, "must be a single line")


def _edge_rules(block: Diagram, base: str) -> Iterator[Finding]:
    if block.kind not in {"flow", "concept_map"}:
        return
    node_ids = {node.id for node in block.nodes}
    seen: dict[tuple[str, ...], int] = {}
    for i, edge in enumerate(block.edges):
        path = f"{base}/edges/{i}"
        for end, ref in (("from", edge.from_id), ("to", edge.to_id)):
            if ref not in node_ids:
                yield ("diagram.unknown_node", f"{path}/{end}", f"unknown node ID {ref!r}")
        if edge.from_id == edge.to_id:
            yield ("diagram.self_edge", path, "an edge must connect two different nodes")
            continue
        pair = (edge.from_id, edge.to_id)
        key = pair if block.kind == "flow" else tuple(sorted(pair))
        if key in seen:
            yield (
                "diagram.duplicate_edge",
                path,
                f"duplicates the edge at {base}/edges/{seen[key]}",
            )
        else:
            seen[key] = i
    if block.kind == "flow":
        yield from _isolated_nodes(block, base)
    else:
        yield from _hub_rules(block, base, node_ids)


def _isolated_nodes(block: Diagram, base: str) -> Iterator[Finding]:
    touched = {end for edge in block.edges for end in (edge.from_id, edge.to_id)}
    for i, node in enumerate(block.nodes):
        if node.id not in touched:
            yield ("diagram.isolated_node", f"{base}/nodes/{i}", f"node {node.id!r} has no edges")


def _hub_rules(block: Diagram, base: str, node_ids: set[str]) -> Iterator[Finding]:
    hub = block.hub
    if hub not in node_ids:
        yield ("diagram.unknown_node", f"{base}/hub", f"unknown node ID {hub!r}")
        return
    reached = _reachable_undirected(block, hub)
    for i, node in enumerate(block.nodes):
        if node.id not in reached:
            yield (
                "diagram.disconnected",
                f"{base}/nodes/{i}",
                f"node {node.id!r} is not connected to the hub {hub!r}",
            )


def _reachable_undirected(block: Diagram, start: str) -> set[str]:
    neighbours: dict[str, set[str]] = {}
    for edge in block.edges:
        neighbours.setdefault(edge.from_id, set()).add(edge.to_id)
        neighbours.setdefault(edge.to_id, set()).add(edge.from_id)
    reached = {start}
    queue = deque([start])
    while queue:
        for other in sorted(neighbours.get(queue.popleft(), ())):
            if other not in reached:
                reached.add(other)
                queue.append(other)
    return reached


def _value_keys(block: Diagram, base: str) -> Iterator[Finding]:
    if block.kind != "comparison":
        return
    item_ids = [item.id for item in block.items]
    for i, criterion in enumerate(block.criteria):
        path = f"{base}/criteria/{i}/values"
        keys = [value.item_id for value in criterion.values]
        for key in keys:
            if key not in item_ids:
                yield ("diagram.unknown_value_key", f"{path}/{key}", f"unknown item ID {key!r}")
        for item_id in dict.fromkeys(item_ids):
            if item_id not in keys:
                yield ("diagram.missing_value", path, f"missing a value for item {item_id!r}")


def _foreign_fields(block: Diagram, base: str, own: tuple[str, ...]) -> Iterator[Finding]:
    for name in ALL_KIND_FIELDS:
        if name not in own and getattr(block, name) not in (None, ()):
            yield ("schema.unknown_field", f"{base}/{name}", f"unknown field {name!r}")
