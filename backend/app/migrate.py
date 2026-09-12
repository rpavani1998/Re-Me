"""Initial schema migration. Run once before deploying a production revision."""
from app.core.config import settings
from app.core.database import make_database, initialize

if __name__ == "__main__":
    engine, _ = make_database(settings().database_url)
    initialize(engine)
    engine.dispose()
