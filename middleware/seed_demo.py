import argparse

from sqlalchemy import select

from middleware.database import SessionLocal
from middleware.models import User
from middleware.services.demo_data import seed_demo_data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed demo sites, products, and sales for an existing user."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--email", help="Email address of the account")
    target.add_argument(
        "--all-users",
        action="store_true",
        help="Seed demo data for every existing account",
    )
    args = parser.parse_args()

    with SessionLocal.begin() as db:
        if args.all_users:
            users = db.scalars(select(User).order_by(User.id)).all()
        else:
            user = db.scalar(
                select(User).where(User.email == args.email.strip().lower())
            )
            if user is None:
                parser.error(f"No account found for {args.email}")
            users = [user]
        inserted = sum(seed_demo_data(db, user) for user in users)
        count = len(users)
    print(f"Inserted {inserted} demo sales records for {count} account(s).")


if __name__ == "__main__":
    main()
