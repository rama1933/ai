from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routers import auth, documents, health, upload


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Agentic RAG", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(auth.router)
    app.include_router(upload.router)
    return app


app = create_app()
