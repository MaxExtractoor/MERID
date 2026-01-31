"""FastAPI entrypoint for the MERID web interface."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from core.energy import create_energy
from core.orchestrator import MeridCore

app = FastAPI()
templates = Jinja2Templates(directory="web/templates")
merid = MeridCore()


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/submit")
async def handle_submit(request: Request, source: str = Form(...), payload: str = Form(...)):
    energy = create_energy(source, payload)

    async def event_generator() -> AsyncIterator[str]:
        async for update in merid.run_cycle_stream(energy):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")