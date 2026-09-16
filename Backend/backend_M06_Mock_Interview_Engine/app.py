"""M06 — Mock Interview Engine · standalone application.

Runs this module ALONE on its reserved port:

    uvicorn backend_M06_Mock_Interview_Engine.app:app --reload --port 8106

The same router is also mounted into the gateway on :8000. Identical behaviour
either way. Ports: PORTS.txt.

Nothing upstream is needed to boot. `/v1/deps` says which modules are up, and
a session narrows its scope around the ones that are not (spec §10).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from ai_core.db import create_all, engine
from ai_core.modules_meta import ModuleStatus, module_status
from ai_core.schema_repair import ensure_schema
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import MODULE_ID, PROMPT_VERSION
from . import models as _models  # noqa: F401 - registers tables
from .keys import load_keys
from .router import router

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_keys()
    # create_all() makes missing TABLES and ignores existing ones, so a model
    # that gained a field leaves an older dev.db one column short and the next
    # query 500s. ensure_schema() adds those columns, additively.
    create_all()
    for change in ensure_schema(engine):
        log.info("schema: added missing column %s", change)
    log.info("M06 ready — prompt version %s", PROMPT_VERSION)
    yield


app = FastAPI(title="M06 — Mock Interview Engine", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "module": MODULE_ID, "prompt_version": PROMPT_VERSION}


@app.get("/status", response_model=ModuleStatus, tags=["meta"])
def status() -> ModuleStatus:
    return module_status(MODULE_ID)
