"""
Matrix bot startup — called from app lifespan to run the sync loop
as a background task.
"""

import asyncio
import logging

from app.database import async_session_factory
from app.matrix.client import create_matrix_client
from app.matrix.handler import MatrixEventHandler
from app.config import get_settings

logger = logging.getLogger(__name__)

_matrix_task: asyncio.Task | None = None
_matrix_client = None


async def start_matrix_bot() -> None:
    """Start the Matrix sync loop if configured. Non-blocking."""
    global _matrix_task, _matrix_client

    client = create_matrix_client()
    if client is None:
        logger.info("Matrix not configured, skipping bot startup")
        return

    settings = get_settings()
    handler = MatrixEventHandler(
        session_factory=async_session_factory,
        matrix_client=client,
        data_dir=settings.DATA_DIR,
    )

    await client.start()
    _matrix_client = client
    _matrix_task = asyncio.create_task(
        client.run_sync_loop(handler.handle_event),
        name="matrix-sync",
    )
    logger.info("Matrix sync loop started")


async def stop_matrix_bot() -> None:
    """Gracefully stop the Matrix sync loop."""
    global _matrix_task, _matrix_client

    if _matrix_client:
        await _matrix_client.stop()
        _matrix_client = None

    if _matrix_task and not _matrix_task.done():
        _matrix_task.cancel()
        try:
            await _matrix_task
        except asyncio.CancelledError:
            pass
        _matrix_task = None

    logger.info("Matrix sync loop stopped")
