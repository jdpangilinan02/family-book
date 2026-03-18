from fastapi import FastAPI

from app.routes.auth_routes import router as auth_router
from app.routes.health import router as health_router
from app.routes.persons import router as persons_router
from app.routes.relationships import router as relationships_router
from app.routes.tree import router as tree_router


def create_phase1_app() -> FastAPI:
    application = FastAPI(
        title="Family Book Phase 1 Test App",
        description="Phase 1-only app assembly for browser smoke tests",
        version="0.1.0",
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(persons_router)
    application.include_router(relationships_router)
    application.include_router(tree_router)
    return application


app = create_phase1_app()
