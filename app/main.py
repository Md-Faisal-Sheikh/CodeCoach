"""FastAPI application entrypoint.

Wires the API routers, serves the no-build dashboard/student pages from
web/templates with Jinja2, and initialises the database on startup. The whole
app runs with no API key (heuristic AI, degraded-but-functional sandbox) so it
is always launchable for demos and CI.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import settings, BASE_DIR
from .db import init_db, get_session
from .models import User
from .auth import get_current_user
from .sandbox.runner import describe as sandbox_describe
from .sandbox.languages import available_languages
from .ai import client as ai_client

from .routers import (problems, submissions, hints, similarity, instructor,
                      grades, research)

WEB_DIR = BASE_DIR / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="CodeCoach", version="1.0",
              description="Coding-education platform with AI hints, sandboxed "
                          "autograding, plagiarism detection, and a hint-quality "
                          "research harness.")

app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(hints.router)
app.include_router(similarity.router)
app.include_router(instructor.router)
app.include_router(grades.router)
app.include_router(research.router)

if (WEB_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/api/system")
def system_info():
    """Sandbox isolation summary + AI mode. Powers the dashboard status strip."""
    return {
        "sandbox": sandbox_describe(),
        "languages": available_languages(),
        "ai": {
            "enabled": settings.ai_enabled,
            "available": ai_client.available(),
            "hint_model": settings.hint_model,
            "judge_model": settings.judge_model,
            "mode": "llm" if ai_client.available() else "heuristic-offline",
        },
        "leakage_threshold": settings.leakage_threshold,
    }


@app.get("/api/whoami")
def whoami(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role,
            "display_name": user.display_name}


# ---- HTML pages (token entered client-side, stored in localStorage) ----
@app.get("/", response_class=HTMLResponse)
def page_index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/student", response_class=HTMLResponse)
def page_student(request: Request):
    return templates.TemplateResponse(request, "student.html")


@app.get("/instructor", response_class=HTMLResponse)
def page_instructor(request: Request):
    return templates.TemplateResponse(request, "instructor.html")
