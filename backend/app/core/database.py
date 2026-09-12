from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from app.domain.models import Base


def make_database(url):
    engine = create_engine(url, pool_pre_ping=True,
                           connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine, sessionmaker(engine, expire_on_commit=False)


def initialize(engine):
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)


def get_db(request):
    with request.app.state.sessions() as session:
        yield session
