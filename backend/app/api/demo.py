from datetime import timedelta
from math import sin
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy import delete, select
from app.api.dependencies import db_session, user
from app.domain.models import Base, User, MemoryEntity, Memory, Entity, RawCapture, now, uid
from app.services.capture_service import canonical

router = APIRouter(prefix="/api/demo")


def require_dev(request: Request):
    if request.app.state.config.app_env != "development":
        raise HTTPException(404, "Not found")


def require_demo(request: Request):
    if request.app.state.config.app_env != "development" or not request.app.state.config.demo_mode:
        raise HTTPException(404, "Not found")


@router.post("/reminder", dependencies=[Depends(require_dev)])
def mock_reminder(db=Depends(db_session), user_id=Depends(user)):
    from app.domain.models import Trigger, RelevanceEvent, Episode
    from app.services.trigger_service import deliver_due_reminders
    from app.repositories.memories import serialize
    db.scalar(select(Trigger).where(Trigger.user_id == user_id, Trigger.status == "pending").with_for_update())
    superceded = db.scalars(select(Trigger).where(Trigger.user_id == user_id, Trigger.status == "pending")).all()
    for old in superceded:
        old.status = "cancelled"
    memory = db.scalar(select(Memory).where(Memory.user_id == user_id)
                       .order_by((Memory.deadline.is_(None)).asc(), Memory.deadline.asc(), Memory.importance_score.desc()))
    if not memory:
        raise HTTPException(404, "No memories to remind about; save or seed something first.")
    trigger = Trigger(user_id=user_id, memory_id=memory.id, scheduled_at=now(),
                      external_reference="local-reminder")
    db.add(trigger)
    db.flush()
    db.commit()
    deliver_due_reminders(db)
    item = db.scalar(select(RelevanceEvent).where(RelevanceEvent.trigger_id == trigger.id))
    return {"suggested": bool(item), "reason": item.reason if item else "Reminder created and fired.",
            "memory": serialize(db, memory)}


def stub_embedding(seed):
    return [sin((i * 0.073 + seed) * 13.0) for i in range(1536)]


def clear_user(db, user_id):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    db.execute(delete(MemoryEntity).where(MemoryEntity.memory_id.in_(select(Memory.id).where(Memory.user_id == user_id))))
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in ("users", "memory_entities", "accounts", "login_sessions"):
            continue
        if "user_id" in table.c:
            db.execute(delete(table).where(table.c.user_id == user_id))
    db.get(User, user_id).context_enabled = False


def insert_memory(db, user_id, *, title, summary, type_, source_url, source_type, image_url,
                  captured_at, intent=None, topics=(), entities=(), actions=(), hints=(),
                  deadline=None, event_date=None, importance=0.5, excerpt=""):
    raw = RawCapture(user_id=user_id, request_id=f"demo-{uid()[:8]}", status="completed",
                     payload={"source_type": source_type, "source_url": source_url, "image_url": image_url,
                              "visible_text": excerpt, "captured_at": captured_at.isoformat(), "reading_status": "read"})
    db.add(raw)
    db.flush()
    memory = Memory(user_id=user_id, raw_capture_id=raw.id, type=type_, title=title, summary=summary,
                    intent=intent, topics=list(topics), possible_actions=list(actions), relevance_hints=list(hints),
                    deadline=deadline, event_date=event_date, embedding=stub_embedding(sum(ord(c) for c in title)),
                    embedding_model="demo", interpretation_provider="demo", importance_score=importance,
                    created_at=captured_at, updated_at=captured_at)
    db.add(memory)
    db.flush()
    for name, etype in entities:
        key = canonical(name)
        entity = db.scalar(select(Entity).where(Entity.user_id == user_id,
                                                Entity.canonical_name == key, Entity.entity_type == etype))
        if not entity:
            entity = Entity(user_id=user_id, name=name, canonical_name=key, entity_type=etype)
            db.add(entity)
            db.flush()
        db.add(MemoryEntity(memory_id=memory.id, entity_id=entity.id, confidence=0.9))
    return memory


@router.post("/seed", dependencies=[Depends(require_demo)])
def seed(db=Depends(db_session), user_id=Depends(user)):
    return {"count": seed_data(db, user_id), "demo": True}


def seed_data(db, user_id):
    clear_user(db, user_id)
    now_ = now()
    day = timedelta(days=1)

    scenarios = [
        dict(title="Seoul Kitchen — bibimbap that hits different",
             summary="An Instagram reel of Seoul Kitchen, a Korean restaurant in Hyderabad. Known for bibimbap, Korean barbecue and homemade kimchi. Marked as a place you want to visit.",
             type_="restaurant", source_type="link",
             source_url="https://www.instagram.com/reel/SeoulKitchenHyd-korean-bbq/",
             image_url="https://images.unsplash.com/photo-1553621042-f6e147245754?w=900&q=70",
             captured_at=now_ - 12 * day, intent="want_to_visit",
             topics=["Korean food", "Hyderabad", "restaurants"],
             entities=[("Seoul Kitchen", "restaurant"), ("Hyderabad", "place"), ("Korean cuisine", "topic")],
             actions=[{"type": "open", "label": "Open Instagram reel"},
                      {"type": "research", "label": "Save to Google Maps"},
                      {"type": "research", "label": "Plan a visit"}],
             importance=0.8, excerpt="Bibimbap, Korean barbecue and homemade kimchi at Seoul Kitchen, Hyderabad."),
        dict(title="AI Agent Engineer at Sarvam — applications close soon",
             summary="LinkedIn post advertising an AI Engineer role at Sarvam AI. Deep match on your profile — LLMs, retrieval and agentic AI. Applications close in a few days.",
             type_="opportunity", source_type="link",
             source_url="https://www.linkedin.com/posts/sarvam-ai_ai-agent-engineer-llm-rag/",
             image_url="https://images.unsplash.com/photo-1521737608167-0d9bdad5183d?w=900&q=70",
             captured_at=now_ - 2 * day, intent="want_to_apply",
             deadline=now_ + 3 * day,
             topics=["AI engineering", "Sarvam", "job application"],
             entities=[("Sarvam AI", "organization"), ("AI Agent Engineer", "topic")],
             actions=[{"type": "draft_email", "label": "Draft application email"}, {"type": "open", "label": "Open job post"}],
             importance=0.95, excerpt="AI Engineer at Sarvam AI. Skills: LLMs, RAG, agentic AI. Apply before deadline."),
        dict(title="GenAI Hyderabad Meetup — registration open",
             summary="Post about the GenAI Hyderabad meetup happening soon: talks on agent evaluation and RAG at scale. Registration required.",
             type_="event", source_type="link",
             source_url="https://www.meetup.com/genai-hyderabad/events/agent-eval-rag-scale/",
             image_url="https://images.unsplash.com/photo-1540575467063-178a50c2df87?w=900&q=70",
             captured_at=now_ - 4 * day, intent="want_to_attend",
             event_date=now_ + 9 * day,
             topics=["AI events", "Hyderabad", "agent evaluation"],
             entities=[("GenAI Hyderabad", "organization"), ("AI meetup", "event")],
             actions=[{"type": "open", "label": "Register for meetup"},
                      {"type": "research", "label": "Add to calendar"},
                      {"type": "research", "label": "Remind me"}],
             importance=0.7, excerpt="GenAI Hyderabad meetup: agent evaluation and RAG at scale. Registration required."),
        dict(title="50% off AI agent toolkit — offer expires soon",
             summary="A tweet announcing 50% off an AI development toolkit for building and evaluating agents. Connects to your saved agent-development resources.",
             type_="offer", source_type="link",
             source_url="https://twitter.com/aicontinuous/status/agent-toolkit-50-off",
             image_url="https://images.unsplash.com/photo-1545241047-6083a3684587?w=900&q=70",
             captured_at=now_ - 1 * day,
             deadline=now_ + 5 * day,
             topics=["AI tools", "offers", "discounts"],
             entities=[("AI agent toolkit", "technology")],
             actions=[{"type": "open", "label": "Open offer"}, {"type": "research", "label": "Compare tools"}],
             importance=0.6, excerpt="50% off the AI agent toolkit. Expires in five days."),
        dict(title="A tiny café in Tokyo, slow coffee and a garden",
             summary="A café in Tokyo with slow pour-over coffee and a quiet moss garden. Saved under your Japan Trip project.",
             type_="place", source_type="webpage",
             source_url="https://japanvisitor.com/tokyo/cafes/slow-coffee-shinjuku-gyoen",
             image_url="https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?w=900&q=70",
             captured_at=now_ - 18 * day, topics=["Japan", "Tokyo cafés", "Japan Trip"],
             entities=[("Tokyo", "place"), ("Japan", "country"), ("Japan Trip", "project")],
             actions=[{"type": "research", "label": "Build an itinerary"}, {"type": "open", "label": "View café"}],
             importance=0.85, excerpt="Slow pour-over coffee, moss garden, Tokyo."),
        dict(title="Kyoto away from the crowds",
             summary="A quiet Kyoto temple with moss gardens and a slow afternoon walk, saved for the Japan trip.",
             type_="place", source_type="webpage",
             source_url="https://japanvisitor.com/kyoto/temples/quiet-moss-garden-walk",
             image_url="https://images.unsplash.com/photo-1493976040374-85c8e12f0c0e?w=900&q=70",
             captured_at=now_ - 18 * day, topics=["Japan", "Kyoto", "Japan Trip"],
             entities=[("Kyoto", "place"), ("Japan", "country"), ("Japan Trip", "project")],
             actions=[{"type": "research", "label": "View on map"}, {"type": "research", "label": "Build an itinerary"}],
             importance=0.85, excerpt="Quiet Kyoto temple, moss gardens, slow afternoon."),
        dict(title="A small hotel in Shinjuku near the station",
             summary="A compact Tokyo hotel in Shinjuku, two minutes from the station. Saved as an option for the Japan trip.",
             type_="place", source_type="webpage",
             source_url="https://agoda.com/tokyo-shinjuku/compact-hotel-near-station",
             image_url="https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?w=900&q=70",
             captured_at=now_ - 16 * day, topics=["Japan", "Tokyo hotels", "Japan Trip"],
             entities=[("Shinjuku", "place"), ("Japan", "country"), ("Japan Trip", "project")],
             actions=[{"type": "research", "label": "Check availability"}, {"type": "open", "label": "View hotel"}],
             importance=0.8, excerpt="Small hotel in Shinjuku, two minutes from the station."),
        dict(title="Japan by rail: Tokyo to Kyoto the easy way",
             summary="Article on riding the shinkansen between Tokyo and Kyoto — reservations, regional passes and tips. Part of the Japan Trip collection.",
             type_="article", source_type="webpage",
             source_url="https://japan-guide.com/e/rail/tokyo-kyoto-shinkansen.html",
             image_url="https://images.unsplash.com/photo-1474487548417-781cb71495f3?w=900&q=70",
             captured_at=now_ - 15 * day, intent="want_to_learn",
             topics=["Japan", "rail travel", "Japan Trip"],
             entities=[("Japan rail", "technology"), ("Japan", "country"), ("Japan Trip", "project")],
             actions=[{"type": "research", "label": "Build an itinerary"}, {"type": "open", "label": "Read article"}],
             importance=0.8, excerpt="Shinkansen Tokyo to Kyoto: reservations, regional passes and practical tips."),
        dict(title="Creamy one-pan pasta you'll want tonight",
             summary="Short video showing a creamy one-pan pasta recipe — garlic, parmesan and a trick for the sauce. Ingredients and steps extracted.",
             type_="recipe", source_type="link",
             source_url="https://www.youtube.com/watch?v=creamypasta_onepan",
             image_url="https://images.unsplash.com/photo-1552566626-52f8b828add9?w=900&q=70",
             captured_at=now_ - 6 * day, intent="want_to_try",
             topics=["recipes", "pasta", "cooking"],
             entities=[("Creamy pasta", "topic")],
             actions=[{"type": "research", "label": "Add ingredients to list"}, {"type": "research", "label": "Find similar recipes"}],
             importance=0.75, excerpt="Creamy one-pan pasta: garlic, parmesan and the sauce trick."),
        dict(title="Evaluating AI agents in production",
             summary="An article on evaluating production AI agents — regression testing, observability, and failure analysis for agentic systems. Connects to your agent-development project.",
             type_="article", source_type="webpage",
             source_url="https://www.hamilton.ai/blog/evaluating-ai-agents-in-production",
             image_url="https://images.unsplash.com/photo-1555255707-c07966088b7b?w=900&q=70",
             captured_at=now_ - 5 * day, intent="want_to_learn",
             topics=["agent evaluation", "observability", "LLM apps"],
             entities=[("AI agents", "technology"), ("regression testing", "topic")],
             actions=[{"type": "open", "label": "Open saved article"},
                      {"type": "research", "label": "Compare approaches"}],
             importance=0.85, excerpt="Regression testing, observability and failure analysis for production AI agents."),
        dict(title="Affordable LLMs compared (pricing update)",
             summary="A comparison of affordable LLMs for inference — cost per token, speed and context size. Re:Me later found pricing has changed for one model and two newer alternatives are available.",
             type_="article", source_type="webpage",
             source_url="https://www.vellum.ai/llm-leaderboard/affordable-models-2026",
             image_url="https://images.unsplash.com/photo-1611974789855-9bd53e0b1d0c?w=900&q=70",
             captured_at=now_ - 30 * day, topics=["LLMs", "pricing", "AI tools"],
             entities=[("LLM leaderboard", "technology")],
             actions=[{"type": "research", "label": "See what changed"},
                      {"type": "research", "label": "Compare models"}],
             importance=0.7, excerpt="Affordable LLMs compared: cost per token, speed and context size."),
        dict(title="Delhi: two hotels and a rooftop café",
             summary="Notes from a Delhi weekend — two hotel options and a rooftop café worth an evening. Less precious than Japan, but worth keeping close.",
             type_="place", source_type="thought",
             source_url=None,
             image_url=None,
             captured_at=now_ - 9 * day, topics=["Delhi", "weekend plans"],
             entities=[("Delhi", "place")],
             actions=[{"type": "open", "label": "Recall this memory"}, {"type": "research", "label": "Plan the weekend"}],
             importance=0.55, excerpt="Two hotel options and a rooftop café in Delhi for the weekend."),
    ]

    for item in scenarios:
        insert_memory(db, user_id, **{k: item.get(k) for k in ("title", "summary", "type_", "source_url", "source_type",
                                                            "image_url", "captured_at", "intent", "deadline", "event_date",
                                                            "importance", "excerpt")},
                      topics=item.get("topics", []), entities=item.get("entities", []),
                      actions=item.get("actions", []), hints=item.get("hints", []))
    db.commit()
    return len(scenarios)


@router.post("/reset", dependencies=[Depends(require_demo)])
def reset(db=Depends(db_session), user_id=Depends(user)):
    clear_user(db, user_id)
    db.commit()
    return {"reset": True}