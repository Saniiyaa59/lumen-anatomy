from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.registry import get_registry
from app.schemas import CommandRequest, CommandResponse
from app.sessions import router as sessions_router
from app.stub import stub_response

app = FastAPI(title="Lumen API")
app.include_router(sessions_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tutor")
def tutor() -> dict[str, str]:
    """Where study sessions come from, so the app can tell the student what to expect."""
    return {"source": settings.session_source}


@app.post("/api/command")
def command(request: CommandRequest) -> CommandResponse:
    """Handle one student command. Currently a stub that returns sample responses."""
    registry = get_registry()
    clicked = [*request.selection, *(click.structure_id for click in request.click_events)]
    unknown = sorted({structure_id for structure_id in clicked if structure_id not in registry})
    if unknown:
        raise HTTPException(status_code=422, detail=f"unknown structure ids: {unknown}")
    return stub_response(request)
