from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict, HttpUrl, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureInput(StrictModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()), max_length=64)
    source_type: Literal["webpage", "selection", "link", "thought", "image"] = "webpage"
    source_url: HttpUrl | None = None
    page_title: str = Field(default="", max_length=500)
    visible_text: str = Field(default="", max_length=16000)
    selected_text: str | None = Field(default=None, max_length=8000)
    user_note: str | None = Field(default=None, max_length=2000)
    image_url: HttpUrl | None = None
    meta_description: str = Field(default="", max_length=2000)
    headings: list[str] = Field(default_factory=list, max_length=20)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("captured_at requires a timezone")
        return value

    @field_validator("headings")
    @classmethod
    def bounded_headings(cls, value):
        if any(len(h) > 300 for h in value):
            raise ValueError("Headings must be at most 300 characters")
        return value

    @model_validator(mode="after")
    def not_empty(self):
        if not any([self.source_url, self.visible_text.strip(), self.selected_text, self.user_note]):
            raise ValueError("A URL, text, selection, or thought is required")
        return self


class ExtractedEntity(StrictModel):
    name: str
    type: Literal["person", "place", "city", "country", "organization", "company", "event", "topic", "product", "restaurant", "technology", "project", "trip", "interest", "other"]
    relationship: str
    confidence: float = Field(ge=0, le=1)


class ExtractedRelationship(StrictModel):
    source: str
    relationship: str
    target: str
    confidence: float = Field(ge=0, le=1)


class PossibleAction(StrictModel):
    type: Literal["open", "draft_email", "research", "create_trip_plan", "compare", "reminder", "add_to_calendar"]
    label: str


class RelevanceHint(StrictModel):
    type: Literal["context", "time"]
    description: str
    confidence: float = Field(ge=0, le=1)


class EventMetadata(StrictModel):
    year: int | None = Field(ge=1, le=9999)
    month: int | None = Field(ge=1, le=12)
    day: int | None = Field(ge=1, le=31)
    start_time: str | None
    end_time: str | None
    timezone: str | None
    venue: str | None
    address: str | None
    organizer: str | None
    registration_url: str | None
    evidence: list[str]
    missing_fields: list[str]


class EventDetails(StrictModel):
    metadata: EventMetadata | None = None
    title: str
    date_text: str
    location: str | None
    starts_at: str | None
    ends_at: str | None
    needs_confirmation: bool
    clarification: str | None


class Extraction(StrictModel):
    event: EventDetails | None = None
    type: str
    title: str
    summary: str
    intent: str | None
    topics: list[str]
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    possible_actions: list[PossibleAction]
    relevance_hints: list[RelevanceHint]
    event_date: str | None
    deadline: str | None
    importance_score: float = Field(ge=0, le=1)


class ContextUnderstanding(StrictModel):
    activity: str
    intent: str | None
    topics: list[str]
    entities: list[str]
    confidence: float = Field(ge=0, le=1)


class Judgment(StrictModel):
    memory_id: str | None
    relevance_score: float = Field(ge=0, le=1)
    suggest_now: bool
    reason: str
    suggested_action: Literal["open", "draft_email", "research", "create_trip_plan", "compare", "reminder", "add_to_calendar"]


class DiscoveryRanking(StrictModel):
    ordered_indices: list[int] = Field(default_factory=list, max_length=6)


class EmailDraft(StrictModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
