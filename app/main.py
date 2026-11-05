from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import settings
from .database import connect_db, disconnect_db
from .routers import auth, users, students, academic, subjects, scores, results, exports, report_cards, dashboard


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Assign the returned database instance to app.state.db
    app.state.db = await connect_db()
    yield
    await disconnect_db()


app = FastAPI(title="GDSS Tudun Wada Result Management", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api"
app.include_router(auth.router, prefix=API)
app.include_router(users.router, prefix=API)
app.include_router(students.router, prefix=API)
app.include_router(academic.router, prefix=API)
app.include_router(subjects.router, prefix=API)
app.include_router(scores.router, prefix=API)
app.include_router(results.router, prefix=API)
app.include_router(exports.router, prefix=API)
app.include_router(report_cards.router, prefix=API)
app.include_router(dashboard.router, prefix=API)


@app.get("/api/health")
async def health():
    return {"status": "ok"}