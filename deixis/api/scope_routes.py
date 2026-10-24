"""A research's earlier question revisions (UI parity S8, R12): read only.

The research view carries the current revision only. "Revision N and its answer are kept · Show" opens the earlier
question as it was saved; this route returns that revision's question, its source scope, its English key terms and when
it was saved. Nothing is written and no run is started.
"""

from fastapi import Request


def register_scope_routes(app):
    @app.get("/api/researches/{research_id}/scope-revisions/{revision}")
    async def scope_revision(research_id: str, revision: int, request: Request):
        store = request.app.state.store
        store.research(research_id)  # a missing or trashed research is not found
        scope = store.scope(research_id, revision)
        return {"revision": scope["revision"], "question": scope["question"], "source_scope": scope["source_scope"],
                "key_terms": scope["key_terms"], "created_at": scope["created_at"]}
