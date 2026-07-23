from contextlib import asynccontextmanager

from fastapi import FastAPI

from agent.api.dependencies import init_dialogue_engine
from agent.api.routers.chat_router import chat_router
from agent.infrastructure.http_client import init_http_client, close_http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    from agent.infrastructure.database import db
    db.init()
    init_http_client()
    init_dialogue_engine()
    yield
    await db.close()
    await close_http_client()


app = FastAPI(lifespan=lifespan)
app.include_router(chat_router)
