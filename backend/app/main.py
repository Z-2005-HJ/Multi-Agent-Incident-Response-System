from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router


app = FastAPI(
    title="Multi-Agent Incident Response System",
    version="0.1.0",
    description="MVP backend for multi-agent incident analysis and reporting.",
)
app.include_router(router)

