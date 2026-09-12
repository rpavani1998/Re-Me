# Re:Me

**The right memory. The right moment.**

Re:Me remembers the things I intentionally care about, understands how they connect, and brings the right memory back when my life makes it relevant again.

## Features

- Save text, links, and web images from the dashboard or Chrome extension.
- Organize memories with extracted entities, connections, and contextual recall.
- Review extracted events, confirm dates, and receive reminders in the dashboard and extension.
- Keep memories scoped to an account with email/password or optional Google sign-in.
- Try the capture flow locally with deterministic demo AI before configuring a live provider.

## Start locally

Requirements: Python 3.12+, Node.js 22+, PostgreSQL 16 with pgvector (or Docker).

```sh
# From ReMe/
docker compose up -d db
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env. The default template explicitly enables simulated AI.
.venv/bin/python -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd ReMe/web
npm ci
cp .env.example .env.local
npm run dev
```

Open http://localhost:3000 and choose **Create an account**, then sign in with email/password. Sessions last 30 days; **Account settings → Sign out** revokes the current session. Google sign-in is available after configuring `GOOGLE_CLIENT_ID`; see [login setup](docs/LOGIN.md). API docs: http://localhost:8000/docs.

For a local demo without PostgreSQL, explicitly set `DATABASE_URL=sqlite:///./reme-demo.db` and `DEMO_MODE=true`. This is a development/testing convenience, not the production storage architecture or a validation of pgvector search.

## Provider credentials

See **[docs/CREDENTIALS.md](docs/CREDENTIALS.md)** for exact values and Google Cloud credentials. Set `LLM_PROVIDER=openrouter` to use a single OpenRouter key for both understanding and embeddings. Set `LLM_PROVIDER=openai` for OpenAI directly. Codex development authentication is independent of these runtime credentials.

## Google Cloud deployment

Deployment-ready Cloud Run, Cloud SQL, Secret Manager, and future private Cloud Storage templates are in **[docs/GOOGLE_CLOUD.md](docs/GOOGLE_CLOUD.md)**. They use `PROJECT_ID` and `REGION` placeholders and do not provision any Google Cloud resources automatically.

## Load the extension

1. Open `chrome://extensions`, enable Developer mode, and choose **Load unpacked → ReMe/extension**.
2. Open the extension settings and click **Sign in to Re:Me**. Sign in on the dashboard with either method, then click **Connect extension**. The extension gets its own session; no API key is required.
3. Visit a normal webpage and choose **Remember this page**, or right-click a selection/link/image. **Remember image with Re:Me** saves the selected web image as its preview, with its source page and available caption. Inline data/blob images are not supported.
4. Open the dashboard to view the memory, preserved original, episode and extracted entities.

The extension sends bounded article text, title, headings, description, URL, and a page preview image URL, never the complete DOM. Live URL-only saves fetch readable public HTML before AI extraction; blocked pages remain saved with an unread notice. The dashboard shows the page image when available, with a styled fallback if it cannot load. Existing memories are not automatically reprocessed. Text/URL captures are the MVP; screenshot, PDF and audio capture are future Cloud Storage-backed interfaces.

## Verification

```sh
cd backend
.venv/bin/python -m pytest -q
cd ../web
npm run build
```

Backend tests use an explicit SQLite database and deterministic/mock providers. Live provider access and PostgreSQL/pgvector must also be verified in the deployment environment.

## Structure

- `backend/app/api`: HTTP routes with account-session authentication and optional legacy script access.
- `backend/app/domain`: separate memory layers and typed AI schemas.
- `backend/app/services`: memory lifecycle and relevance policies.
- `backend/app/repositories`: scoped access and response serialization.
- `backend/app/integrations`: OpenAI, OpenRouter, demo and later optional providers.
- `backend/app/migrate.py`: database migration entry point.
- `web`: Next.js, TypeScript and Tailwind dashboard.
- `extension`: Manifest V3 capture and opt-in context interface.
- `trigger-worker`: optional Trigger.dev event reminder tasks; see [worker setup](trigger-worker/README.md).
- `cloudrun`: Google Cloud deployment templates.
- `compose.yaml`: local PostgreSQL with pgvector.
- `docs`: credentials, login, architecture, and deployment guides.

Email/password and Google accounts have separate memories. The optional legacy `API_TOKEN` still accesses the original configured user for scripts; existing demo memories are not automatically transferred into new accounts. No automatic publishing, sending messages, or external action execution occurs on capture.

## Saving and processing

Dashboard and extension saves persist the original content and return HTTP 202 before article reading or AI calls. Pending saves appear in the dashboard and refresh every five seconds. A failed analysis preserves the original and offers Retry. Queued saves survive API restarts; interrupted processing becomes retryable after ten minutes. The API process runs one queue worker, so it must stay running. Hosted instances need CPU allocated between requests and at least one running instance (or a separately deployed queue worker). Synchronous API clients can continue using `/api/captures` without `background=true`.

## Repository files

Commit source code, documentation, configuration templates, and image assets. Local `.env` files, dependencies, generated build files, databases, and videos are excluded by `.gitignore`. Copy the supplied `.env.example` templates for local configuration and keep credentials out of commits.
