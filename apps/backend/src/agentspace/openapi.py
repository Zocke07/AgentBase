"""The OpenAPI schema, and the TypeScript types generated from it (§5 Phase 7).

Both outputs are committed so the frontend typechecks without a Python
environment and drift shows in a diff; `test_openapi_snapshot.py` keeps them
current. The emitter lives here because `openapi-typescript` caps its
TypeScript peer below this tree's version and the input is a small closed set
of keywords. It raises on a keyword it does not understand rather than
emitting `unknown`, which would typecheck and protect nothing.

Side-effect free: `just schemas` and the drift test call the same functions.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Final

from agentspace.config import AppPaths
from agentspace.main import create_app

__all__ = [
    "UnsupportedSchemaError",
    "emit_typescript",
    "schema",
    "serialise",
    "write",
    "write_typescript",
]

#: Schema keywords the emitter reads. Anything else raises.
_KNOWN_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        # Structural: these decide the emitted type.
        "$ref",
        "anyOf",
        "additionalProperties",
        "const",
        "enum",
        "items",
        "properties",
        "required",
        "type",
        # Documentation and validation: read for comments, or ignored on
        # purpose (`minimum` has no TypeScript equivalent worth a branded type).
        "default",
        "description",
        "examples",
        "format",
        "maxLength",
        "maxItems",
        "maximum",
        "minLength",
        "minItems",
        "minimum",
        "title",
    }
)

_PRIMITIVES: Final[dict[str, str]] = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
}

_HEADER: Final[str] = """\
/**
 * Generated from the sidecar's OpenAPI schema. Do not edit.
 *
 * Regenerate with `just schemas`; `test_openapi_snapshot.py` fails if this
 * file drifts from the FastAPI app. A field is optional here exactly when the
 * schema does not list it as required.
 */

"""


class UnsupportedSchemaError(Exception):
    """A schema construct the emitter does not handle.

    Names the path so the model is obvious.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(
            f"{path}: {detail}. The emitter in agentspace/openapi.py needs "
            f"extending; see its docstring for why it refuses to guess."
        )


# --- the schema document ----------------------------------------------------


def schema() -> dict[str, Any]:
    """The live OpenAPI document for the sidecar.

    Built with throwaway paths: `create_app()` opens no database but does
    resolve the data directory, and a generator must not depend on the machine.
    """
    placeholder = Path("/nonexistent")
    app = create_app(
        AppPaths(
            data_dir=placeholder,
            db_path=placeholder / "agentspace.sqlite3",
            logs_dir=placeholder / "logs",
            spaces_dir=placeholder / "spaces",
            legacy_workspace=placeholder / "workspace",
        )
    )
    document: dict[str, Any] = app.openapi()
    return document


def serialise(document: dict[str, Any]) -> str:
    """Render the schema as the committed file holds it: sorted keys, trailing newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


# --- the TypeScript emitter -------------------------------------------------


def _ref_name(ref: str, path: str) -> str:
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        raise UnsupportedSchemaError(path, f"unsupported $ref target {ref!r}")
    return ref.removeprefix(prefix)


def _literal(value: object, path: str) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return json.dumps(value)
    raise UnsupportedSchemaError(path, f"cannot express enum member {value!r} as a TS literal")


def _check_keywords(node: dict[str, Any], path: str) -> None:
    unknown = sorted(set(node) - _KNOWN_KEYWORDS)
    if unknown:
        raise UnsupportedSchemaError(path, f"unhandled schema keyword(s) {unknown}")


def _type_of(node: dict[str, Any], path: str, indent: str = "") -> str:
    """Render one schema node as a TypeScript type expression."""
    _check_keywords(node, path)

    if "$ref" in node:
        return _ref_name(node["$ref"], path)

    if "anyOf" in node:
        members = [
            _type_of(member, f"{path}.anyOf[{index}]", indent)
            for index, member in enumerate(node["anyOf"])
        ]
        # Deduplicated: `str | None` can otherwise render as `string | null | null`.
        return _union(list(dict.fromkeys(members)), indent)

    if "enum" in node:
        return _union([_literal(value, path) for value in node["enum"]], indent)

    # A one-member `Literal`: Pydantic writes it as `const`, not `enum`.
    if "const" in node:
        return _literal(node["const"], path)

    declared = node.get("type")

    if declared == "array":
        items = node.get("items")
        if not isinstance(items, dict):
            raise UnsupportedSchemaError(path, "an array without an `items` schema")
        inner = _type_of(items, f"{path}[]", indent)
        # Parenthesised so `(A | B)[]` does not become `A | B[]`.
        return f"({inner})[]" if "|" in inner else f"{inner}[]"

    if declared == "object":
        return _object_type(node, path, indent)

    if isinstance(declared, list):
        return _union(
            [
                _PRIMITIVES[member] if member in _PRIMITIVES else _unsupported(member, path)
                for member in declared
            ],
            indent,
        )

    if isinstance(declared, str):
        if declared in _PRIMITIVES:
            return _PRIMITIVES[declared]
        raise UnsupportedSchemaError(path, f"unknown JSON Schema type {declared!r}")

    if not node or set(node) <= {"title", "description"}:
        # Pydantic's bare `Any`: the schema really does say nothing.
        return "unknown"

    raise UnsupportedSchemaError(
        path, "no `type`, `$ref`, `anyOf`, `enum` or `const` to render"
    )


#: Beyond this, a union is rendered one member per line (`EventType` has 26).
_UNION_WRAP_AT: Final[int] = 88


def _union(members: list[str], indent: str) -> str:
    """Join union members, wrapping a long one across lines."""
    single = " | ".join(members)
    if len(single) + len(indent) <= _UNION_WRAP_AT or len(members) < 2:
        return single

    inner = indent + "  "
    newline = "\n"
    return newline + newline.join(f"{inner}| {member}" for member in members)


def _unsupported(member: str, path: str) -> str:  # pragma: no cover: defensive
    raise UnsupportedSchemaError(path, f"unknown JSON Schema type {member!r}")


def _object_type(node: dict[str, Any], path: str, indent: str) -> str:
    properties = node.get("properties")
    additional = node.get("additionalProperties")

    if not properties:
        if additional is None or additional is True:
            return "Record<string, unknown>"
        if additional is False:
            return "Record<string, never>"
        value = _type_of(additional, f"{path}.additionalProperties", indent)
        return f"Record<string, {value}>"

    inner = indent + "  "
    required = set(node.get("required", []))
    lines: list[str] = ["{"]

    for name, child in properties.items():
        child_path = f"{path}.{name}"
        rendered = _type_of(child, child_path, inner)
        optional = "" if name in required else "?"

        for comment in _doc_comment(child, inner):
            lines.append(comment)
        lines.append(f"{inner}{_property_key(name)}{optional}: {rendered};")

    lines.append(f"{indent}}}")
    return "\n".join(lines)


#: A property name that is not a plain identifier has to be quoted.
def _property_key(name: str) -> str:
    if name.isidentifier():
        return name
    return json.dumps(name)


def _doc_comment(node: dict[str, Any], indent: str) -> list[str]:
    """Render a schema `description` as a JSDoc comment, so contracts show on hover."""
    description = node.get("description")
    if not description:
        return []

    body = [line.rstrip() for line in str(description).strip().splitlines()]
    if len(body) == 1:
        return [f"{indent}/** {body[0]} */"]

    lines = [f"{indent}/**"]
    lines.extend(f"{indent} * {line}".rstrip() for line in body)
    lines.append(f"{indent} */")
    return lines


def _declaration(name: str, node: dict[str, Any]) -> str:
    """One exported declaration for one component schema."""
    rendered = _type_of(node, name)
    comment = "\n".join(_doc_comment(node, ""))
    prefix = f"{comment}\n" if comment else ""

    if rendered.startswith("{"):
        return f"{prefix}export interface {name} {rendered}\n"
    return f"{prefix}export type {name} = {rendered};\n"


def emit_typescript(document: dict[str, Any] | None = None) -> str:
    """Render every component schema as a TypeScript declaration.

    Only `components.schemas`: the model types are what the dashboard needs,
    and the routes are asserted to exist by a test instead.
    """
    doc = document if document is not None else schema()
    schemas: dict[str, Any] = doc["components"]["schemas"]

    parts = [_HEADER]
    parts.extend(_declaration(name, node) for name, node in sorted(schemas.items()))
    body = "\n".join(parts)

    # A wrapped union leaves a trailing space after `=`; one rule here, not
    # one at every construction site.
    return "\n".join(line.rstrip() for line in body.splitlines()) + "\n"


# --- writing ----------------------------------------------------------------


def _write_text(destination: Path, text: str) -> None:
    """Write ``text`` with LF endings: `Path.write_text` on Windows would write CRLF."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write(destination: Path) -> None:
    """Write the OpenAPI document to ``destination``."""
    _write_text(destination, serialise(schema()))


def write_typescript(destination: Path) -> None:
    """Write the generated TypeScript types to ``destination``."""
    _write_text(destination, emit_typescript())


if __name__ == "__main__":  # pragma: no cover: exercised by `just schemas`
    write(Path(sys.argv[1]))
    write_typescript(Path(sys.argv[2]))
