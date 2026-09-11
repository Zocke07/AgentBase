"""The OpenAPI schema, and the TypeScript types generated from it.

§5 Phase 7: "Generate TS types from the FastAPI OpenAPI schema; never
hand-write the API types."

**Why the schema and the types are committed rather than built on demand.** A
build step that starts the sidecar to read `/openapi.json` makes the frontend's
typecheck depend on a working Python environment, which breaks `just check` on a
clean clone and turns a type error into a startup error. Committing both keeps
`packages/schemas` an ordinary source dependency — and makes drift visible in a
diff: changing a response model shows up as a change to these files in the same
commit. `test_openapi_snapshot.py` is what stops them going stale.

**Why the emitter is here and not `openapi-typescript`.** That is the canonical
tool and it caps its TypeScript peer at `^5.x`, while this tree is on 6.0.3, so
it cannot be installed without `--legacy-peer-deps` on every `npm install` —
which would weaken peer checking for the whole dependency tree to satisfy one
dev tool. This is the same conflict Phase 0 hit with `eslint-plugin-import`
against ESLint 10; there the answer was a maintained fork, and here there is
none. The input is 17 schemas over a closed set of keywords, so generating them
here costs less than the flag does.

**The emitter raises on a keyword it does not understand.** A generator that
fell back to `unknown` would quietly stop protecting anything the first time a
later phase added a model with `oneOf` or `allOf` in it, and nothing would fail.
:class:`UnsupportedSchemaError` makes that a build failure instead.

Deliberately importable and side-effect free: the functions here are what both
`just schemas` and the drift test call, so the two cannot disagree about what
"the schema" means.
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

#: Schema keywords the emitter reads. Anything else raises, rather than being
#: silently dropped — see the module docstring.
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
        # purpose. A constraint like `minimum` has no TypeScript equivalent, and
        # pretending otherwise with a branded type would make the generated
        # types harder to consume than the API they describe.
        "default",
        "description",
        "examples",
        "format",
        "maxLength",
        "maximum",
        "minLength",
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
 * Regenerate with `just schemas`. BUILD_SPEC §5 Phase 7 requires the API types
 * to be generated rather than hand-written, and
 * `test_openapi_snapshot.py` fails if this file drifts from the FastAPI app.
 *
 * A field is optional here exactly when the schema does not list it as
 * required, which for a response model means it has a default. That is the
 * schema's reading rather than a judgement about what the server sends, because
 * a generator that second-guessed its input would be a second source of truth.
 */

"""


class UnsupportedSchemaError(Exception):
    """A schema construct the emitter does not handle.

    Raised rather than degraded to `unknown`: the point of generated types is
    that they are checked, and a silent `unknown` is an unchecked field that
    still typechecks. The message names the path so the offending model is
    obvious.
    """

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(
            f"{path}: {detail}. The emitter in agentspace/openapi.py needs "
            f"extending — see its docstring for why it refuses to guess."
        )


# --- the schema document ----------------------------------------------------


def schema() -> dict[str, Any]:
    """The live OpenAPI document for the sidecar.

    Built from an app with explicit, throwaway paths. `create_app()` opens no
    database — that happens in the lifespan — but it *does* resolve the data
    directory, and resolving it in a code generator is how a generated artefact
    ends up depending on which machine ran the generator.
    """
    placeholder = Path("/nonexistent")
    app = create_app(
        AppPaths(
            data_dir=placeholder,
            db_path=placeholder / "agentspace.sqlite3",
            logs_dir=placeholder / "logs",
            workspace_root=placeholder / "workspace",
        )
    )
    document: dict[str, Any] = app.openapi()
    return document


def serialise(document: dict[str, Any]) -> str:
    """Render the schema exactly as the committed file holds it.

    Sorted keys and a trailing newline, so a regeneration produces a diff of
    what actually changed rather than a reordering of the whole file.
    """
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
        # Deduplicated because `str | None` and `Optional[str]` can both reach
        # here, and `string | null | null` is noise rather than information.
        return _union(list(dict.fromkeys(members)), indent)

    if "enum" in node:
        return _union([_literal(value, path) for value in node["enum"]], indent)

    # A `Literal` with one member. Pydantic writes it as `const`, not as a
    # one-element `enum`, and the type is the same: that one literal.
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
        # A genuinely unconstrained value — Pydantic's bare `Any`. `unknown` is
        # the honest rendering: the schema really does say nothing.
        return "unknown"

    raise UnsupportedSchemaError(
        path, "no `type`, `$ref`, `anyOf`, `enum` or `const` to render"
    )


#: Beyond this, a union is rendered one member per line. `EventType` has 26
#: members and would otherwise be a single 900-character line — technically
#: correct and unreadable in a diff, which is where these types get reviewed.
_UNION_WRAP_AT: Final[int] = 88


def _union(members: list[str], indent: str) -> str:
    """Join union members, wrapping a long one across lines."""
    single = " | ".join(members)
    if len(single) + len(indent) <= _UNION_WRAP_AT or len(members) < 2:
        return single

    inner = indent + "  "
    newline = "\n"
    return newline + newline.join(f"{inner}| {member}" for member in members)


def _unsupported(member: str, path: str) -> str:  # pragma: no cover - defensive
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
    """Render a schema `description` as a JSDoc comment.

    Kept because these descriptions are where the payload contracts and the
    warnings live — "do not render `run.completed.summary` as fact" is worth
    having on hover in the editor, not only in CLAUDE.md.
    """
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

    Only `components.schemas` is emitted. Route and operation types are what
    `openapi-typescript` spends most of its output on and they are painful to
    consume — `paths["/runs"]["get"]["responses"][200]["content"]...` — while
    the thing the dashboard actually needs is the model types. The paths
    themselves are asserted to exist by
    `test_the_schema_covers_every_route_the_dashboard_calls`.
    """
    doc = document if document is not None else schema()
    schemas: dict[str, Any] = doc["components"]["schemas"]

    parts = [_HEADER]
    parts.extend(_declaration(name, node) for name, node in sorted(schemas.items()))
    body = "\n".join(parts)

    # A wrapped union leaves `export type X = ` with a trailing space before the
    # newline. Stripping here rather than at each construction site means one
    # rule — no trailing whitespace, anywhere — instead of a rule every future
    # branch has to remember.
    return "\n".join(line.rstrip() for line in body.splitlines()) + "\n"


# --- writing ----------------------------------------------------------------


def _write_text(destination: Path, text: str) -> None:
    """Write ``text`` with LF endings, whatever the platform.

    `Path.write_text` on Windows translates every `\\n` to `\\r\\n`, which
    contradicts `.gitattributes`' `* text=auto eol=lf` and is invisible to
    `ruff check`, `mypy` and `pytest` — a mistake this project has already made
    once (CLAUDE.md, Phase 4).
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def write(destination: Path) -> None:
    """Write the OpenAPI document to ``destination``."""
    _write_text(destination, serialise(schema()))


def write_typescript(destination: Path) -> None:
    """Write the generated TypeScript types to ``destination``."""
    _write_text(destination, emit_typescript())


if __name__ == "__main__":  # pragma: no cover - exercised by `just schemas`
    write(Path(sys.argv[1]))
    write_typescript(Path(sys.argv[2]))
