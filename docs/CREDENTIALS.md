# Credentials and configuration

Edit **`backend/.env`**, copied from `backend/.env.example`. Start the API from `backend/` so that it reads that file. The repository-root `.env` is not loaded. Existing secret files are never overwritten by setup.

Codex is the development tool. Re:Me's running backend uses the provider selected below; its credentials do not come from your Codex session.

## Required now

| Variable | What to enter |
| --- | --- |
| `DATABASE_URL` | PostgreSQL connection string. Local Docker: `postgresql+psycopg://reme:reme@localhost:5432/reme`. Cloud SQL: see below. |
| `API_TOKEN` | A token you generate for access to **your Re:Me API**. Generate with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Optional legacy access for scripts. The dashboard and extension use account sign-in; see [LOGIN.md](LOGIN.md). |
| `DEMO_MODE` | `false` for real model calls; `true` uses deterministic demo rules and requires no provider key. |
| `LLM_PROVIDER` | `openrouter` or `openai`. |

### Option A: OpenRouter only

```dotenv
DEMO_MODE=false
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=anthropic/claude-sonnet-4
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small
OPENAI_API_KEY=
```

Get your credential from [OpenRouter API keys](https://openrouter.ai/settings/keys). The same key authenticates extraction, context understanding, reranking and embeddings. You need credits and access to the selected models. Use a model endpoint supporting [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs); requests require compatible routing and results are validated locally. OpenRouter provides an [embeddings endpoint](https://openrouter.ai/docs/api/api-reference/embeddings/submit-an-embedding-request), so an OpenAI key is **not** required for this option.

### Option B: OpenAI directly

```dotenv
DEMO_MODE=false
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini
EMBEDDING_MODEL=text-embedding-3-small
OPENROUTER_API_KEY=
```

Create a key in the [OpenAI API dashboard](https://platform.openai.com/api-keys). The implementation uses [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and embeddings. Model IDs are configurable, not tied to the model used for development.

The schema expects **1536-dimensional embeddings**. A different embedding model requires re-embedding existing memories, even if the dimensions match. Demo embeddings are not comparable to real embeddings; use a separate database or reset the development demo before changing modes.

## Google Cloud

Cloud Run uses a dedicated service account and Secret Manager; do not paste a service-account JSON key into `.env`.

| Value / credential | Where it is used |
| --- | --- |
| Google Cloud project ID and region | Deployment commands and resource names; not secrets. |
| Cloud SQL instance connection name | `PROJECT:REGION:INSTANCE`, attached to Cloud Run. |
| Cloud SQL database, username, password | Build `DATABASE_URL`; store the resulting URL in Secret Manager. URL-encode special characters in username/password. |
| Provider API key | Secret Manager; inject as `OPENROUTER_API_KEY` or `OPENAI_API_KEY`. |
| Re:Me `API_TOKEN` | Optional legacy script access; if enabled, keep in Secret Manager with at least 32 random characters in production. |
| Cloud Run service account | Needs `roles/cloudsql.client` and access to the specific application secrets. |

Cloud Run database URL using its Cloud SQL socket:

```dotenv
DATABASE_URL=postgresql+psycopg://USERNAME:URL_ENCODED_PASSWORD@/reme?host=/cloudsql/PROJECT:REGION:INSTANCE
APP_ENV=production
DEMO_MODE=false
```

For a local connection to Cloud SQL, run the Cloud SQL Auth Proxy with your Google Application Default Credentials, then point `DATABASE_URL` at the proxy's localhost port. No Google API key is required for database access.

## Account login

Email/password login needs no provider key. Set `GOOGLE_CLIENT_ID` to a Google Web OAuth client ID to enable **Continue with Google**. See [LOGIN.md](LOGIN.md) for setup and extension sign-in.

## Optional integrations

| Variable | Needed for |
| --- | --- |
| `EXA_API_KEY` | Live, explicitly requested external discovery. Obtain from the Exa dashboard. |
| `TRIGGER_SECRET_KEY` | Secret API key from your Trigger.dev project API Keys page. Use the same environment key in backend and worker for scheduling and callback authentication. No separate callback token is required. |
| `PUBLIC_API_URL` | Reachable HTTPS backend URL for Trigger.dev callbacks. Localhost cannot receive hosted worker callbacks. |
| `ALLOWED_ORIGINS` | JSON array containing your dashboard origin, e.g. `["https://reme-web-....run.app"]`. |

Ambiguous credentials are not needed for the local draft action provider. Cloud Storage credentials are not needed for text/URL captures; future binary uploads should use the Cloud Run service identity and a private bucket.

Provider keys belong only in the backend or Secret Manager. Never place them in the extension or any `NEXT_PUBLIC_*` variable.
