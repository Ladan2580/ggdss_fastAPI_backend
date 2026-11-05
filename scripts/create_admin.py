
import argparse
import asyncio

from app import database
from app.security import hash_password


async def main(username: str, password: str, full_name: str):
    try:
        await database.connect_db()

        db = database.db

        if db is None:
            raise RuntimeError("MongoDB database is not initialised.")

        existing_user = await db.users.find_one({"username": username})

        if existing_user:
            print(f"User '{username}' already exists.")
            return

        await db.users.insert_one({
            "username": username,
            "full_name": full_name,
            "password_hash": hash_password(password),
            "role": "super_admin",
            "is_active": True,
        })

        print(f"Created super_admin '{username}' successfully.")

    finally:
        await database.disconnect_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--name", default="Administrator")

    args = parser.parse_args()

    asyncio.run(main(args.username, args.password, args.name))
