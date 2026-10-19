import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from wms2ship.carrier_fees import router as carrier_fee_router
from wms2ship.config import Settings
from wms2ship.configuration import router as configuration_router
from wms2ship.contacts import router as contacts_router
from wms2ship.db import make_engine, migrate
from wms2ship.import_routes import router as import_router
from wms2ship.labels import router as label_router
from wms2ship.purchases import recover_interrupted
from wms2ship.purchases import router as purchase_router
from wms2ship.rates import router as rate_router
from wms2ship.reports import router as review_router
from wms2ship.sample import sample_workbook
from wms2ship.shipstation import ProviderUnavailable
from wms2ship.voids import recover_interrupted_voids
from wms2ship.voids import router as void_router
from wms2ship.workspace_settings import initialize_workspace
from wms2ship.workspace_settings import router as settings_router

ROOT = Path(__file__).parent


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        # Local single-process convenience. Cloud deploy will migrate separately.
        migrate(settings)
        app.state.engine = make_engine(settings)
        recover_interrupted(app.state.engine)
        recover_interrupted_voids(app.state.engine)
        initialize_workspace(app)

        app.state.csrf_token = secrets.token_urlsafe(32)
        try:
            yield
        finally:
            for connection in app.state.retired_connections:
                connection.close()
            if app.state.shipment_source:
                app.state.shipment_source.close()
            for provider in app.state.providers.values():
                if hasattr(provider, "close"):
                    provider.close()
            app.state.engine.dispose()

    app = FastAPI(title="WMS2ShipStation", lifespan=lifespan)
    app.state.settings = settings
    app.include_router(import_router)
    app.include_router(configuration_router)
    app.include_router(contacts_router)
    app.include_router(settings_router)
    app.include_router(review_router)
    app.include_router(carrier_fee_router)
    app.include_router(purchase_router)
    app.include_router(label_router)
    app.include_router(rate_router)
    app.include_router(void_router)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    templates = Jinja2Templates(directory=str(ROOT / "templates"))
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    @app.middleware("http")
    async def csrf_and_security(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("x-csrf-token", "")
            if not secrets.compare_digest(supplied, request.app.state.csrf_token):
                return JSONResponse({"detail": "Refresh the page and try again."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Cross-origin request rejected."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        return response

    @app.exception_handler(ProviderUnavailable)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=502)

    @app.get("/api/providers")
    def providers(request: Request):
        return [
            {
                "code": p.code,
                "mode": p.mode,
                "live_purchase_enabled": getattr(p, "enable_live", False),
            }
            for p in request.app.state.providers.values()
        ]

    @app.get("/sample.xlsx")
    def sample():
        return Response(
            sample_workbook(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="synthetic-demo.xlsx"'},
        )

    @app.get("/health")
    def health(request: Request):
        with request.app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/")
    def home(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "csrf": request.app.state.csrf_token,
                "version": "2026.10.19.2",
                "release_date": "2026-10-19",
            },
        )

    return app


app = create_app()
