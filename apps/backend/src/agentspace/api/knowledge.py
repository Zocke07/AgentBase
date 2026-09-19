"""Native knowledge-vault CRUD, graph and local retrieval endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from agentspace.knowledge.store import (
    KnowledgeConflictError,
    KnowledgeEvaluation,
    KnowledgeEvaluationCase,
    KnowledgeFolderDeleteResult,
    KnowledgeGraph,
    KnowledgeImportResult,
    KnowledgeIndex,
    KnowledgeMoveResult,
    KnowledgeNote,
    KnowledgePathError,
    KnowledgeSearch,
    MemoryIndex,
    MemoryItem,
    MemoryMergeResult,
    MemoryStatus,
    NoteNotFoundError,
    SearchFilters,
)
from agentspace.store.spaces import SpaceNotFoundError

if TYPE_CHECKING:
    from agentspace.knowledge.store import KnowledgeStore

__all__ = ["router"]

router = APIRouter(prefix="/spaces/{space_id}/knowledge")


class WriteNoteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=200_000)


class SearchKnowledgeRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    limit: int = Field(default=8, ge=1, le=20)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class MoveNoteRequest(BaseModel):
    source: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)
    update_links: bool = True


class ImportNote(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=200_000)


class ImportKnowledgeRequest(BaseModel):
    files: list[ImportNote] = Field(min_length=1, max_length=10_000)
    overwrite: bool = False


class UpdateMemoryRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    status: MemoryStatus | None = None
    pinned: bool | None = None


class MergeMemoriesRequest(BaseModel):
    paths: list[str] = Field(min_length=2, max_length=20)
    title: str | None = Field(default=None, max_length=120)


class PinNoteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    pinned: bool


class EvaluateKnowledgeRequest(BaseModel):
    cases: list[KnowledgeEvaluationCase] = Field(min_length=1, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)


def _store(request: Request) -> KnowledgeStore:
    store: KnowledgeStore = request.app.state.knowledge
    return store


def _bad_path(exc: KnowledgePathError) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": str(exc), "field": "path"})


@router.get("")
async def list_knowledge(request: Request, space_id: str) -> KnowledgeIndex:
    try:
        return await _store(request).index(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/note")
async def get_note(request: Request, space_id: str, path: str = Query(...)) -> KnowledgeNote:
    try:
        return await _store(request).get_note(space_id, path)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/note")
async def write_note(request: Request, space_id: str, body: WriteNoteRequest) -> KnowledgeNote:
    try:
        return await _store(request).write_note(space_id, body.path, body.content)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc


@router.post("/move")
async def move_note(
    request: Request, space_id: str, body: MoveNoteRequest
) -> KnowledgeMoveResult:
    try:
        return await _store(request).move_note(
            space_id, body.source, body.target, update_links=body.update_links
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/import")
async def import_knowledge(
    request: Request, space_id: str, body: ImportKnowledgeRequest
) -> KnowledgeImportResult:
    try:
        return await _store(request).import_notes(
            space_id,
            [(item.path, item.content) for item in body.files],
            overwrite=body.overwrite,
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/note", status_code=204)
async def delete_note(request: Request, space_id: str, path: str = Query(...)) -> Response:
    try:
        await _store(request).delete_note(space_id, path)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.delete("/folder")
async def delete_folder(
    request: Request, space_id: str, path: str = Query(...)
) -> KnowledgeFolderDeleteResult:
    """Delete a folder and its notes, after a copy under `.agentspace/backups/`."""
    try:
        return await _store(request).delete_folder(space_id, path)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/search")
async def search_knowledge(
    request: Request, space_id: str, body: SearchKnowledgeRequest
) -> KnowledgeSearch:
    try:
        return await _store(request).search_response(
            space_id, body.query, body.limit, body.filters
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/memories")
async def list_memories(request: Request, space_id: str) -> MemoryIndex:
    try:
        return await _store(request).memories(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/memory")
async def update_memory(
    request: Request, space_id: str, body: UpdateMemoryRequest
) -> MemoryItem:
    try:
        return await _store(request).update_memory(
            space_id, body.path, status=body.status, pinned=body.pinned
        )
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/memories/merge")
async def merge_memories(
    request: Request, space_id: str, body: MergeMemoriesRequest
) -> MemoryMergeResult:
    try:
        return await _store(request).merge_memories(space_id, body.paths, body.title)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/pin")
async def pin_note(request: Request, space_id: str, body: PinNoteRequest) -> KnowledgeNote:
    try:
        return await _store(request).pin_note(space_id, body.path, body.pinned)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgePathError as exc:
        raise _bad_path(exc) from exc
    except NoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/evaluate")
async def evaluate_knowledge(
    request: Request, space_id: str, body: EvaluateKnowledgeRequest
) -> KnowledgeEvaluation:
    try:
        return await _store(request).evaluate(space_id, body.cases, body.limit)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/graph")
async def knowledge_graph(request: Request, space_id: str) -> KnowledgeGraph:
    try:
        return await _store(request).graph(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
