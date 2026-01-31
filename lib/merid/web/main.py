"""FastAPI entrypoint for the MERID web interface."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
import logging

from core.energy import create_energy
from pydantic import ValidationError
from web.schemas import SubmitRequest, MeridUpdate

logger = logging.getLogger(__name__)
from core.orchestrator import MeridCore
from web.metrics import metrics

app = FastAPI()
from web.admin import router as admin_router

app.include_router(admin_router)


@app.get("/metrics")
async def metrics_endpoint():
    """Expose in-process metrics for scraping/test inspection."""
    return metrics.get_metrics_text()

templates = Jinja2Templates(directory="web/templates")
merid = MeridCore()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Starlette/Jinja2 TemplateResponse signature changed; pass request first to avoid deprecation warnings
    return templates.TemplateResponse(request, "index.html")


@app.post("/submit")
async def handle_submit(request: Request, source: str = Form(...), payload: str = Form(...)):
    # Validate input with Pydantic so bad payloads are rejected consistently
    try:
        submit = SubmitRequest(source=source, payload=payload)
    except ValidationError as exc:
        logger.warning("Invalid submit payload: %s", exc)
        return {"detail": exc.errors()}

    energy = create_energy(submit.source, submit.payload)

    async def event_generator() -> AsyncIterator[str]:
        async for update in merid.run_cycle_stream(energy):
            # Validate shape returned by MeridCore to avoid streaming broken payloads
            if not isinstance(update, dict):
                logger.warning("MeridCore yielded non-dict update: %r", update)
                continue
            try:
                # Use Pydantic v2 model validation method to avoid deprecation warnings
                MeridUpdate.model_validate(update)
            except ValidationError as exc:
                logger.warning("MeridCore yielded invalid update: %s", exc)
                continue
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")