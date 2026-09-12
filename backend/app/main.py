import logging
import asyncio
from contextlib import suppress
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.core.config import settings
from app.core.database import make_database, initialize
from app.domain.models import User
from app.integrations.openai_client import provider
from app.api import ambiguous, calendar, actions, auth, captures, context, demo, discovery, graph, relevance, triggers
from app.services.context_engine import purge_expired
from app.services.capture_queue import process_next


def create_app(config=None, ai=None):
    config = config or settings()
    config.validate_runtime()
    engine, sessions = make_database(config.database_url)

    @asynccontextmanager
    async def lifespan(app):
        # Local only. Production schema is applied by a separate migration job.
        if config.app_env != "production":
            initialize(engine)
        with sessions() as db:
            if not db.get(User, config.user_id):
                db.add(User(id=config.user_id))
                db.commit()
        def cleanup():
            with sessions() as db:
                purge_expired(db)
                from app.services.trigger_service import deliver_due_reminders, dispatch_reminders
                dispatch_reminders(db, config)
                deliver_due_reminders(db)
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.to_thread(cleanup)
                except Exception:
                    logging.getLogger("reme").warning("CONTEXT_CLEANUP_FAILED")
                await asyncio.sleep(60)
        task = asyncio.create_task(cleanup_loop())
        stop_worker = asyncio.Event()
        async def capture_worker():
            while not stop_worker.is_set():
                try:
                    await asyncio.to_thread(process_next, sessions, app.state.ai, config)
                except Exception:
                    logging.getLogger("reme").exception("CAPTURE_WORKER_FAILED")
                try:
                    await asyncio.wait_for(stop_worker.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
        worker = asyncio.create_task(capture_worker())
        async def calendar_sync_loop():
            from app.services.ambiguous_sync import sync_pending_events
            while not stop_worker.is_set():
                try:
                    await asyncio.to_thread(sync_pending_events, sessions, config)
                except Exception:
                    logging.getLogger("reme").warning("AMBIGUOUS_SYNC_FAILED")
                try:
                    await asyncio.wait_for(stop_worker.wait(), timeout=10)
                except asyncio.TimeoutError:
                    pass
        calendar_worker = asyncio.create_task(calendar_sync_loop())
        yield
        stop_worker.set()
        await worker
        await calendar_worker
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        engine.dispose()

    app = FastAPI(title="Re:Me", description="The right memory. The right moment.", lifespan=lifespan)
    app.state.config, app.state.engine, app.state.sessions = config, engine, sessions
    app.state.ai = ai or provider(config)
    app.state.auth_limiter = auth.AuthLimiter()
    app.add_middleware(CORSMiddleware, allow_origins=config.allowed_origins,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
    app.include_router(captures.router)
    app.include_router(auth.router)
    app.include_router(context.router)
    app.include_router(relevance.router)
    app.include_router(graph.router)
    app.include_router(demo.router)
    app.include_router(triggers.router)
    app.include_router(discovery.router)
    app.include_router(actions.router)
    app.include_router(calendar.router)
    app.include_router(ambiguous.router)

    @app.get("/health")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "demo_mode": config.demo_mode, "provider": app.state.ai.name}

    return app


logging.basicConfig(level=logging.INFO, format="%(message)s")
