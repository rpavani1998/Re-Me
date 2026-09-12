# Personal memory, not a bookmark table

Capture → understand → remember → connect → wait → observe temporary context → detect relevance → recall → optionally act.

## Data layers

| Tables | Responsibility |
| --- | --- |
| `users` | Configured identity and explicit context permission, default off. |
| `raw_captures` | Immutable submitted payload, idempotency key, processing status/error. Commit before calling AI. |
| `memories` | Derived interpretation, dates, intent, importance, embedding and model identity. |
| `episodes` | What happened, when, why, and to which memory. |
| `entities`, `memory_entities`, `relationships` | Personal relevance graph; confidence and episode provenance. Bounded traversal only. |
| `semantic_facts` | Future derived knowledge with source episodes, confidence and expiry. No aggressive consolidation in MVP. |
| `context_sessions`, `context_events` | Temporary active browsing window; never promoted to long-term memory. |
| `relevance_events` | Intervention reasons, scores and feedback. |
| `triggers` | Durable time-based wake-ups. |
| `actions` | Proposed action, approval, execution state and result. |

Every root record carries `user_id`; API identity comes from a configured token, never from an untrusted request field. Raw captures are preserved if downstream AI processing fails. A repeat `request_id` returns the existing memory or retries failed extraction. AI outputs never execute tools.

## Providers

OpenAI uses Responses structured parsing. OpenRouter uses Chat Completions with strict JSON schema, compatible-provider routing, and Pydantic validation. Both supply 1536-dimensional embeddings. The deterministic demo provider is opt-in and labelled in API/UI; live provider failures never silently fall back to it.

## Google Cloud target

Cloud Run hosts the FastAPI service and Next.js dashboard. Cloud SQL PostgreSQL hosts all memory layers and pgvector. Secret Manager supplies API and provider credentials through the service identity. Application logs contain lifecycle IDs and counts, not captured content. Cloud Storage is the future private binary-capture store; no bucket is needed for the working text/URL slice.

The selected AI provider, Exa discovery and Trigger.dev are external integrations. Google Cloud provides application hosting, persistence, secrets and observability. There is no Neo4j, deep GraphRAG, browser-history ingestion, or multi-agent orchestration.

## Deliberate MVP limits

One configured user, synchronous capture processing, basic entity canonicalization, no automatic semantic consolidation, no binary ingestion. A process killed during extraction can leave a `processing` capture requiring recovery (original data remains intact). Production schema changes after the initial migration need versioned follow-up migrations. Relational graph endpoint integrity is enforced by the service because graph endpoints are polymorphic.
