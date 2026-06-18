from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth.router import router as auth_router
from routers.pilots import router as pilots_router
from routers.championships import router as championships_router
from routers.teams import router as teams_router
from routers.news import router as news_router
from routers.classes import router as classes_router
from routers.push import router as push_router
from routers.feed import router as feed_router

app = FastAPI(
    title="Gripline API",
    version="0.2.0",
    description="Мобильный API для приложения Gripline",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(pilots_router)
app.include_router(championships_router)
app.include_router(teams_router)
app.include_router(news_router)
app.include_router(classes_router)
app.include_router(push_router)
app.include_router(feed_router)


@app.get("/health")
def health():
    return {"status": "ok"}
