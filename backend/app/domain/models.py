"""Separate persistent memory layers. PostgreSQL is the deployment database."""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, Float, Integer, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    context_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Account(Base):
    __tablename__ = "accounts"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RawCapture(Record, Base):
    __tablename__ = "raw_captures"
    __table_args__ = (UniqueConstraint("user_id", "request_id"),)
    request_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    error: Mapped[str | None] = mapped_column(Text)


class Memory(Record, Base):
    __tablename__ = "memories"
    raw_capture_id: Mapped[str] = mapped_column(ForeignKey("raw_captures.id"), unique=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(120))
    topics: Mapped[list] = mapped_column(JSON, default=list)
    possible_actions: Mapped[list] = mapped_column(JSON, default=list)
    relevance_hints: Mapped[list] = mapped_column(JSON, default=list)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    embedding: Mapped[list] = mapped_column(Vector(1536).with_variant(JSON, "sqlite"))
    embedding_model: Mapped[str] = mapped_column(String(100))
    interpretation_provider: Mapped[str] = mapped_column(String(100))
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_surfaced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismiss_count: Mapped[int] = mapped_column(Integer, default=0)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0)


class Episode(Record, Base):
    __tablename__ = "episodes"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    user_intent: Mapped[str | None] = mapped_column(String(120))
    importance: Mapped[float] = mapped_column(Float, default=0.5)


class Entity(Record, Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("user_id", "canonical_name", "entity_type"),)
    name: Mapped[str] = mapped_column(String(300))
    canonical_name: Mapped[str] = mapped_column(String(300), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class MemoryEntity(Base):
    __tablename__ = "memory_entities"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id"), primary_key=True)
    relationship_type: Mapped[str] = mapped_column(String(40), default="about")
    confidence: Mapped[float] = mapped_column(Float)


class Relationship(Record, Base):
    __tablename__ = "relationships"
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    relationship: Mapped[str] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    source_episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"))


class SemanticFact(Record, Base):
    __tablename__ = "semantic_facts"
    subject: Mapped[str] = mapped_column(String(300))
    predicate: Mapped[str] = mapped_column(String(120))
    object: Mapped[str] = mapped_column(String(300))
    confidence: Mapped[float] = mapped_column(Float)
    source_episode_ids: Mapped[list] = mapped_column(JSON)
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContextSession(Record, Base):
    __tablename__ = "context_sessions"
    status: Mapped[str] = mapped_column(String(24), default="active")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContextEvent(Record, Base):
    __tablename__ = "context_events"
    session_id: Mapped[str] = mapped_column(ForeignKey("context_sessions.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)


class Trigger(Record, Base):
    __tablename__ = "triggers"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), default="pending")
    external_reference: Mapped[str | None] = mapped_column(String(200))


class Action(Record, Base):
    __tablename__ = "actions"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="awaiting_approval")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_reference: Mapped[str | None] = mapped_column(String(200))


class RelevanceEvent(Record, Base):
    __tablename__ = "relevance_events"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    context_session_id: Mapped[str | None] = mapped_column(String(64))
    trigger_id: Mapped[str | None] = mapped_column(ForeignKey("triggers.id"), unique=True)
    relevance_score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    suggested_action: Mapped[str] = mapped_column(String(40), default="open")
    outcome: Mapped[str | None] = mapped_column(String(40))


Index("ix_memories_embedding_hnsw", Memory.embedding, postgresql_using="hnsw",
      postgresql_ops={"embedding": "vector_cosine_ops"}).ddl_if(dialect="postgresql")
