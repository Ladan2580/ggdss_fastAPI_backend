from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

client: AsyncIOMotorClient | None = None
_actual_db = None


class DatabaseProxy:
    """Proxy object so module-level `from .database import db` 
    always points to the active database instance dynamically."""
    def __getattr__(self, name):
        if _actual_db is None:
            raise RuntimeError("Database is not connected yet!")
        return getattr(_actual_db, name)


# Exported db proxy
db = DatabaseProxy()


async def connect_db():
    global client, _actual_db

    client = AsyncIOMotorClient(settings.MONGO_URI)

    # Verify MongoDB connection
    await client.admin.command("ping")

    _actual_db = client[settings.MONGO_DB]

    await _ensure_indexes()

    print("MongoDB connected successfully!")
    return _actual_db


async def disconnect_db():
    global client, _actual_db

    if client:
        client.close()
        client = None
        _actual_db = None


async def _ensure_indexes():
    await _actual_db.users.create_index("username", unique=True)
    await _actual_db.students.create_index("admission_no", unique=True)
    await _actual_db.students.create_index([("full_name", "text")])
    await _actual_db.classes.create_index("name", unique=True)
    await _actual_db.subjects.create_index("name", unique=True)
    await _actual_db.sessions.create_index(
        [("name", 1), ("term", 1)], unique=True
    )
    await _actual_db.subject_results.create_index(
        [
            ("session_id", 1),
            ("class_id", 1),
            ("arm_id", 1),
            ("subject_id", 1),
            ("student_id", 1)
        ],
        unique=True,
    )
    await _actual_db.audit_logs.create_index([("created_at", -1)])