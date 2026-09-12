import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import initialize
from app.api.demo import seed_data

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://reme:reme@localhost:5432/reme")
engine = create_engine(DATABASE_URL)
initialize(engine)
Session = sessionmaker(engine, expire_on_commit=False)
user_id = sys.argv[1]
with Session() as db:
    count = seed_data(db, user_id)
    print(f"seeded {count} memories for {user_id}")