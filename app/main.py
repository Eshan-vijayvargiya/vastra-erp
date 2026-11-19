"""Vastra Mills ERP: FastAPI app with server-rendered pages.

Run locally:  uvicorn app.main:app --reload    then open http://127.0.0.1:8000
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect
from starlette.middleware.sessions import SessionMiddleware

from . import seed
from .db import engine
from .routers import accounts, auth, dashboard, export, forecast, home, production, products, purchases, sales, stock
from .web import HERE, NotSignedIn


@asynccontextmanager
async def lifespan(app: FastAPI):
    # first start (or a fresh server on a free host): build the demo database
    if not inspect(engine).has_table("users"):
        seed.build(verbose=False)
    export.create_views()
    yield


app = FastAPI(title="Vastra Mills ERP", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"), same_site="lax")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.exception_handler(NotSignedIn)
async def to_login(request: Request, exc: NotSignedIn):
    return RedirectResponse("/login", status_code=303)


for r in (auth, home, dashboard, products, production, stock, purchases, sales, accounts, forecast, export):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"ok": True}
