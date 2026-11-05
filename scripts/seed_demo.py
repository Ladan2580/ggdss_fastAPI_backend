"""Optional demonstration data seed. Uses fictional sample data only.

Usage:
    cd backend
    python -m scripts.seed_demo
"""
import asyncio
from app.database import connect_db, disconnect_db, db


async def main():
    await connect_db()

    session = await db.sessions.find_one({"name": "2026/2027", "term": "First Term"})
    if not session:
        res = await db.sessions.insert_one({"name": "2026/2027", "term": "First Term", "is_current": True})
        session_id = res.inserted_id
    else:
        session_id = session["_id"]

    for level, names in {
        "JSS": ["JSS1", "JSS2", "JSS3"],
        "SS": ["SS1", "SS2", "SS3"],
    }.items():
        for n in names:
            if not await db.classes.find_one({"name": n}):
                await db.classes.insert_one({"name": n, "level": level})

    for arm in ["A", "B", "C"]:
        if not await db.arms.find_one({"name": arm}):
            await db.arms.insert_one({"name": arm})

    for sname, code in [
        ("Mathematics", "MTH"), ("English Language", "ENG"), ("Basic Science", "BSC"),
        ("Social Studies", "SOS"), ("Civic Education", "CVE"),
    ]:
        if not await db.subjects.find_one({"name": sname}):
            await db.subjects.insert_one({"name": sname, "code": code})

    await disconnect_db()
    print("Demo academic data ensured. (No students were created.)")


if __name__ == "__main__":
    asyncio.run(main())