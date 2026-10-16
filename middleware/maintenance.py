from sqlalchemy import delete, func

from middleware.database import SessionLocal
from middleware.models import AuthSession


def delete_expired_sessions() -> int:
    with SessionLocal.begin() as db:
        result = db.execute(
            delete(AuthSession).where(AuthSession.expires_at <= func.now())
        )
        return result.rowcount or 0


if __name__ == "__main__":
    print(f"Deleted {delete_expired_sessions()} expired session(s).")
