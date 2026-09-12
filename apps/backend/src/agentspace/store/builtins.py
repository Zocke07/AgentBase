"""The three seeded roles, as data a new space can be seeded from.

Migration 003 seeds these into the first roster and migration 004 widens
their allowlists; both are SQL that runs exactly once. A space created later
asks for "fresh copies of the three seeded roles" (§5 Phase 11), which needs
the roles in Python, and a test asserts these match what the migrations
seeded, so the two copies cannot drift.

Only the *content* of a role lives here. Ids are minted per copy: the fixed
ids in migration 003 name the built-ins of the default space, and a copy in
another space is a new row that the user may delete.
"""

from __future__ import annotations

from typing import Final, TypedDict

__all__ = ["BUILTIN_ROLES", "BuiltinRole"]


class BuiltinRole(TypedDict):
    name: str
    role: str
    system_prompt: str
    allowed_tools: tuple[str, ...]


BUILTIN_ROLES: Final[tuple[BuiltinRole, ...]] = (
    {
        "name": "researcher",
        "role": "Gathers facts and figures, and reports them without embellishment",
        "system_prompt": (
            "You are a researcher. Establish the facts you have been asked for and "
            "report them plainly, with figures where figures exist. State what you "
            "do not know rather than filling the gap. Do not write prose for "
            "publication: another agent does that with what you find."
        ),
        "allowed_tools": ("read_file", "list_dir"),
    },
    {
        "name": "writer",
        "role": "Turns findings into clear prose for the reader",
        "system_prompt": (
            "You are a writer. Turn what you have been given into clear, concrete "
            "prose for a reader who was not present for the research. Keep the "
            "figures exactly as they were given to you: do not round them, and do "
            "not add any you were not given. Be brief."
        ),
        "allowed_tools": ("read_file", "write_file"),
    },
    {
        "name": "reviewer",
        "role": "Checks work against the task it was meant to do, and says what is wrong",
        "system_prompt": (
            "You are a reviewer. Check the work you have been given against the task "
            "it was meant to accomplish. Report specific problems and what would "
            "fix them. If it is sound, say so plainly rather than inventing "
            "criticism. Do not rewrite it yourself."
        ),
        "allowed_tools": ("read_file", "list_dir"),
    },
)
