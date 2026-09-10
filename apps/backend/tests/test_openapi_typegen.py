"""The TypeScript emitter behind `packages/schemas`.

§5 Phase 7: "Generate TS types from the FastAPI OpenAPI schema; never
hand-write the API types." These tests are about the *generator*; the drift
between what it produces and what is committed is `test_openapi_snapshot.py`.

The property that matters most is the one in
:class:`~agentspace.openapi.UnsupportedSchemaError`: a construct the emitter
does not understand must raise, not become `unknown`. A generator that degrades
silently produces a file that typechecks and protects nothing, and — like every
other silent-success bug this project has hit — the test suite stays green while
it happens.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentspace.openapi import UnsupportedSchemaError, emit_typescript, schema


def _document(schemas: dict[str, Any]) -> dict[str, Any]:
    return {"components": {"schemas": schemas}}


def _emit(node: dict[str, Any], name: str = "Subject") -> str:
    return emit_typescript(_document({name: node}))


# --- the shapes FastAPI actually produces -----------------------------------


def test_a_required_field_is_not_optional() -> None:
    emitted = _emit({"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]})

    assert "id: string;" in emitted


def test_a_field_with_a_default_is_optional() -> None:
    """Faithful to the schema, which is the whole contract of a generator.

    FastAPI omits a defaulted field from `required` even on a response model
    that always sends it. Rendering it as required would be the generator
    improving on its input, which makes it a second source of truth about the
    API — exactly what generating from the schema is meant to avoid.
    """
    emitted = _emit({"type": "object", "properties": {"n": {"type": "integer", "default": 3}}})

    assert "n?: number;" in emitted


@pytest.mark.parametrize(
    ("json_type", "expected"),
    [
        ("string", "string"),
        ("integer", "number"),
        ("number", "number"),
        ("boolean", "boolean"),
    ],
)
def test_primitives_map_to_their_typescript_equivalents(json_type: str, expected: str) -> None:
    emitted = _emit(
        {"type": "object", "properties": {"f": {"type": json_type}}, "required": ["f"]}
    )

    assert f"f: {expected};" in emitted


def test_an_optional_field_renders_as_a_null_union() -> None:
    """`str | None` in Python is `string | null` here, not `string | undefined`.

    The distinction is real: the server sends `null`, and a client that only
    checked for `undefined` would treat a present-but-null field as set.
    """
    emitted = _emit(
        {
            "type": "object",
            "properties": {"maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
            "required": ["maybe"],
        }
    )

    assert "maybe: string | null;" in emitted


def test_an_enum_becomes_a_union_of_literals() -> None:
    emitted = _emit({"type": "string", "enum": ["low", "high"]})

    assert 'export type Subject = "low" | "high";' in emitted


def test_a_reference_becomes_the_referenced_name() -> None:
    emitted = emit_typescript(
        _document(
            {
                "Inner": {"type": "string"},
                "Outer": {
                    "type": "object",
                    "properties": {"inner": {"$ref": "#/components/schemas/Inner"}},
                    "required": ["inner"],
                },
            }
        )
    )

    assert "inner: Inner;" in emitted


def test_an_array_of_a_union_is_parenthesised() -> None:
    """`(A | B)[]`, never `A | B[]` — which is a different and wrong type."""
    emitted = _emit(
        {
            "type": "object",
            "properties": {
                "loc": {"type": "array", "items": {"anyOf": [{"type": "string"}, {"type": "integer"}]}}
            },
            "required": ["loc"],
        }
    )

    assert "loc: (string | number)[];" in emitted


def test_a_free_form_object_becomes_a_record() -> None:
    emitted = _emit(
        {"type": "object", "properties": {"payload": {"type": "object"}}, "required": ["payload"]}
    )

    assert "payload: Record<string, unknown>;" in emitted


def test_a_description_becomes_a_doc_comment() -> None:
    """The payload contracts live in these descriptions; keep them on hover."""
    emitted = _emit({"type": "string", "description": "How much damage a call can do."})

    assert "/** How much damage a call can do. */" in emitted


def test_a_long_union_is_wrapped_one_member_per_line() -> None:
    """`EventType` has 26 members and is reviewed in a diff, not in an editor."""
    emitted = _emit({"type": "string", "enum": [f"a.very.long.event.name.{n}" for n in range(20)]})

    assert '\n  | "a.very.long.event.name.0"' in emitted


def test_nothing_emitted_has_trailing_whitespace() -> None:
    emitted = emit_typescript()

    offenders = [line for line in emitted.splitlines() if line != line.rstrip()]
    assert offenders == []


# --- the refusal to guess ---------------------------------------------------


@pytest.mark.parametrize(
    "node",
    [
        pytest.param({"allOf": [{"type": "string"}]}, id="allOf"),
        pytest.param({"oneOf": [{"type": "string"}]}, id="oneOf"),
        pytest.param({"not": {"type": "string"}}, id="not"),
        pytest.param({"type": "array", "prefixItems": [{"type": "string"}]}, id="prefixItems"),
        pytest.param({"discriminator": {"propertyName": "kind"}}, id="discriminator"),
    ],
)
def test_an_unhandled_keyword_raises_rather_than_becoming_unknown(node: dict[str, Any]) -> None:
    """The property the whole generator rests on.

    Every one of these is a construct a later phase could plausibly introduce —
    a discriminated union of event payloads is the obvious Phase 8 candidate.
    Emitting `unknown` for it would leave the frontend typechecking against a
    field it knows nothing about, with nothing anywhere reporting a problem.
    """
    with pytest.raises(UnsupportedSchemaError):
        _emit(node)


def test_an_array_without_items_raises() -> None:
    with pytest.raises(UnsupportedSchemaError):
        _emit({"type": "array"})


def test_an_unknown_json_type_raises() -> None:
    with pytest.raises(UnsupportedSchemaError):
        _emit({"type": "definitely-not-a-json-schema-type"})


def test_a_reference_outside_component_schemas_raises() -> None:
    with pytest.raises(UnsupportedSchemaError):
        _emit({"$ref": "#/components/responses/Nope"})


def test_the_error_names_the_offending_field() -> None:
    """A build failure that does not say which model broke is a scavenger hunt."""
    with pytest.raises(UnsupportedSchemaError, match=r"Subject\.broken"):
        _emit({"type": "object", "properties": {"broken": {"allOf": []}}, "required": ["broken"]})


# --- the real document ------------------------------------------------------


def test_every_component_schema_is_emitted() -> None:
    """No model may be quietly skipped — that is the same failure as `unknown`."""
    emitted = emit_typescript()

    for name in schema()["components"]["schemas"]:
        assert f"export interface {name} " in emitted or f"export type {name} =" in emitted


def test_the_emitter_is_deterministic() -> None:
    assert emit_typescript() == emit_typescript()
