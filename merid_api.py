"""FastAPI entrypoint for MERID with unified trading suite and dev chat APIs."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from web.api.trading_suite import router as trading_suite_router
from web.api.dev_chat import router as dev_chat_router

app = FastAPI(
    title="MERID API",
    description="MERID unified trading suite + dev chat endpoints",
    version="v1",
)

# CORS
allowed_origins = os.getenv("MERID_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(trading_suite_router)
app.include_router(dev_chat_router)

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
