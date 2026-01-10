from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from core.orchestrator import MeridCore
from core.energy import create_energy
import json, asyncio

app = FastAPI()
templates = Jinja2Templates(directory="web/templates")
merid = MeridCore()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/submit")
async def handle_submit(request: Request, source: str = Form(...), payload: str = Form(...)):
    energy = create_energy(source, payload)
    async def event_generator():
        async for update in merid.run_cycle_stream(energy):
            yield f"data: {json.dumps(update)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream")