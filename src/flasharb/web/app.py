import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from ..models import Policy
from ..worker import Worker
from ..storage.ledger import summary, report_rows
from .auth import verify_password

ROOT = Path(__file__).parent


def create_app(config, store, password_digest, launch_worker=True, signer=None, mode="observe"):
    worker = Worker(config, store, signer, mode) if launch_worker else None

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(worker.run()) if worker else None
        yield
        if task:
            worker.stop.set()
            await task

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware, secret_key=secrets.token_hex(32), same_site="strict", max_age=3600
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")
    attempts = {}

    def csrf(request):
        if "csrf" not in request.session:
            request.session["csrf"] = secrets.token_urlsafe(32)
        return request.session["csrf"]

    def authenticated(request):
        if not request.session.get("auth"):
            raise HTTPException(401, "Login required")

    async def mutation(request):
        authenticated(request)
        form = await request.form()
        if not secrets.compare_digest(
            str(form.get("csrf", "")), str(request.session.get("csrf", "unavailable"))
        ):
            raise HTTPException(403, "Invalid form token")
        return form

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    @app.get("/login")
    async def login_page(request: Request):
        return templates.TemplateResponse(
            request=request, name="login.html", context={"csrf": csrf(request), "error": ""}
        )

    @app.post("/login")
    async def login(request: Request):
        form = await request.form()
        if not secrets.compare_digest(
            str(form.get("csrf", "")), str(request.session.get("csrf", "unavailable"))
        ):
            raise HTTPException(403)
        peer = request.client.host
        recent = [t for t in attempts.get(peer, []) if t > time.time() - 300]
        if len(recent) >= 5:
            raise HTTPException(429, "Wait five minutes before trying again")
        if not verify_password(str(form.get("password", "")), password_digest):
            attempts[peer] = recent + [time.time()]
            return templates.TemplateResponse(
                request=request,
                name="login.html",
                context={"csrf": csrf(request), "error": "Incorrect password"},
                status_code=401,
            )
        request.session.clear()
        request.session["auth"] = True
        csrf(request)
        attempts.pop(peer, None)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        await mutation(request)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    async def page(request, section):
        if not request.session.get("auth"):
            return RedirectResponse("/login", status_code=303)
        observations = store.rows(
            "SELECT chain_id,block,payload,created FROM observations ORDER BY id DESC LIMIT 100"
        )
        for x in observations:
            x["payload"] = json.loads(x["payload"])
        context = {
            "csrf": csrf(request),
            "section": section,
            "summary": summary(store),
            "networks": [
                {
                    "config": c,
                    "enabled": store.get_state("enabled:" + str(c.chain_id), c.enabled),
                    "health": store.get_state(
                        "health:" + str(c.chain_id), {"status": "not connected"}
                    ),
                }
                for c in config.chains
            ],
            "observations": observations,
            "transactions": report_rows(store)[:100],
            "mode": store.get_state("mode", "observe"),
            "paused": store.get_state("paused", False),
            "policy": Policy(**store.get_state("policy", config.policy.model_dump(mode="json"))),
        }
        return templates.TemplateResponse(request=request, name="dashboard.html", context=context)

    @app.get("/")
    async def home(request: Request):
        return await page(request, "Overview")

    @app.get("/{section}")
    async def section_page(section: str, request: Request):
        names = {
            "networks": "Networks",
            "opportunities": "Opportunities",
            "transactions": "Transactions",
            "reports": "Reports",
            "settings": "Settings",
        }
        if section not in names:
            raise HTTPException(404)
        return await page(request, names[section])

    @app.post("/control/pause")
    async def pause(request: Request):
        await mutation(request)
        store.set_state("paused", True)
        return RedirectResponse("/", 303)

    @app.post("/control/resume")
    async def resume(request: Request):
        await mutation(request)
        store.set_state("paused", False)
        return RedirectResponse("/", 303)

    @app.post("/control/mode")
    async def change_mode(request: Request):
        form = await mutation(request)
        value = form.get("mode")
        if value not in ("observe", "simulate"):
            raise HTTPException(403, "Enable live only through a local signer-unlocked process")
        store.set_state("mode", value)
        return RedirectResponse("/", 303)

    @app.post("/control/network")
    async def network(request: Request):
        form = await mutation(request)
        try:
            chain = int(form.get("chain_id", ""))
        except ValueError:
            raise HTTPException(422)
        if chain not in {c.chain_id for c in config.chains}:
            raise HTTPException(422)
        store.set_state("enabled:" + str(chain), form.get("enabled") == "true")
        return RedirectResponse("/networks", 303)

    @app.post("/control/settings")
    async def settings(request: Request):
        form = await mutation(request)
        values = {k: str(v) for k, v in form.items() if k != "csrf"}
        if set(values) - set(Policy.model_fields):
            raise HTTPException(422, "Only trading policy fields may be changed")
        try:
            policy = Policy(
                **(store.get_state("policy", config.policy.model_dump(mode="json")) | values)
            )
        except ValueError:
            raise HTTPException(422, "Invalid policy")
        store.set_state("paused", True)
        store.set_state("policy", policy.model_dump(mode="json"))
        return RedirectResponse("/settings", 303)

    @app.get("/export/{format}")
    async def export(format: str, request: Request):
        authenticated(request)
        if format == "json":
            return Response(
                json.dumps({"summary": summary(store), "executions": report_rows(store)}, indent=2),
                media_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="arbitrary-report.json"'},
            )
        if format != "csv":
            raise HTTPException(404)
        import csv
        import io

        rows = report_rows(store)
        out = io.StringIO()
        keys = sorted({k for r in rows for k in r} or {"id", "chain_id", "status"})
        writer = csv.DictWriter(out, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
        return Response(
            out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="arbitrary-report.csv"'},
        )

    return app
