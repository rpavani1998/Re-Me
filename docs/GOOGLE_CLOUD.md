# Google Cloud deployment

This guide deploys Re:Me on Cloud Run with Cloud SQL for PostgreSQL and pgvector. It creates no resources by itself. Substitute `PROJECT_ID` and `REGION` in every command and manifest before use. Use a region supported by both Cloud Run and Cloud SQL, such as `us-central1`.

## Architecture and security

`reme-api` is a public Cloud Run API used by the dashboard, extension, and Trigger.dev callback. `reme-web` is a public Cloud Run Next.js service. Only the API service identity reads application secrets. Cloud SQL has no public IP: Cloud Run connects through the Cloud SQL Unix socket at `/cloudsql/PROJECT_ID:REGION:reme-postgres`.

Create a private Cloud Storage bucket named `PROJECT_ID-reme-captures` only when PDF, image, or audio capture is added. The current text and URL MVP does not access it. Future binary-capture code should use the API service identity, object names prefixed by the configured user ID, and no public ACLs or signed upload URLs longer than the immediate upload window.

## Required values and secrets

Create these Secret Manager secrets outside source control. The application values map directly to backend environment variables.

| Secret name | Environment variable | Required |
| --- | --- | --- |
| `reme-database-url` | `DATABASE_URL` | Yes |
| `reme-api-token` | `API_TOKEN` | Optional legacy script access |
| `reme-openrouter-api-key` | `OPENROUTER_API_KEY` | Yes for OpenRouter |
| `reme-exa-api-key` | `EXA_API_KEY` | Only discovery |
| `reme-trigger-secret-key` | `TRIGGER_SECRET_KEY` | Only Trigger.dev |

The production database URL is:

```dotenv
DATABASE_URL=postgresql+psycopg://USERNAME:URL_ENCODED_PASSWORD@/reme?host=/cloudsql/PROJECT_ID:REGION:reme-postgres
```

Set `APP_ENV=production`, `DEMO_MODE=false`, `LLM_PROVIDER=openrouter`, `OPENROUTER_MODEL=openai/gpt-5-mini`, `OPENROUTER_EMBEDDING_MODEL=openai/text-embedding-3-small`, and `ALLOWED_ORIGINS` to a JSON array containing the final `reme-web` URL. Do not create `NEXT_PUBLIC_*` values for provider, database, or application-token secrets.

## Provisioning sequence

Enable services and create the private registry, service accounts, and least-privilege bindings:

```sh
gcloud config set project PROJECT_ID
gcloud services enable run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com storage.googleapis.com
gcloud artifacts repositories create reme --repository-format=docker --location=REGION
gcloud iam service-accounts create reme-api --display-name="ReMe API"
gcloud iam service-accounts create reme-web --display-name="ReMe web"
gcloud projects add-iam-policy-binding PROJECT_ID --member="serviceAccount:reme-api@PROJECT_ID.iam.gserviceaccount.com" --role=roles/cloudsql.client
```

Create Cloud SQL without a public IP, then create the application database and user through a secured administrator connection. Enable pgvector with the schema-init job below; no manual `CREATE EXTENSION` command is needed.

```sh
gcloud sql instances create reme-postgres --database-version=POSTGRES_16 --cpu=2 --memory=7680MiB --region=REGION --no-assign-ip
gcloud sql databases create reme --instance=reme-postgres
gcloud storage buckets create gs://PROJECT_ID-reme-captures --location=REGION --uniform-bucket-level-access
gcloud storage buckets update gs://PROJECT_ID-reme-captures --public-access-prevention=enforced
```

For each listed secret, create it and grant only the API identity access. Do not put literal secret values in shell history; Secret Manager supports console entry or a protected CI secret input.

```sh
gcloud secrets create reme-database-url --replication-policy=automatic
gcloud secrets add-iam-policy-binding reme-database-url --member="serviceAccount:reme-api@PROJECT_ID.iam.gserviceaccount.com" --role=roles/secretmanager.secretAccessor
# Repeat the create and secretAccessor binding for every secret in the table.
```

Build images from the repository root and deploy templates after replacing placeholders. The dashboard build argument must be the deployed API URL, not a secret.

```sh
gcloud builds submit backend --tag REGION-docker.pkg.dev/PROJECT_ID/reme/reme-api:latest
gcloud builds submit . --config cloudrun/cloudbuild-web.yaml --substitutions=_IMAGE=REGION-docker.pkg.dev/PROJECT_ID/reme/reme-web:latest,_NEXT_PUBLIC_API_URL=https://reme-api-PROJECT_ID.REGION.run.app
gcloud run jobs replace cloudrun/cloudsql-init.yaml --region=REGION
gcloud run jobs execute reme-schema-init --region=REGION --wait
gcloud run services replace cloudrun/api-service.yaml --region=REGION
gcloud run services replace cloudrun/web-service.yaml --region=REGION
```

Verify the deployed API URL first, then rebuild the dashboard with that exact URL, update `ALLOWED_ORIGINS` to the dashboard URL, and redeploy the API revision.

## Operational checks

Run the schema job before the first API revision and after any migration change. Confirm `GET /health` returns a live provider and that the API can query Cloud SQL. Set `PUBLIC_API_URL` to the final HTTPS API URL before enabling Trigger.dev. Keep Cloud SQL automated backups enabled and monitor Cloud Run request errors, Cloud SQL connections, and Secret Manager access audit logs.

The supplied [Cloud Run API manifest](../cloudrun/api-service.yaml), [dashboard manifest](../cloudrun/web-service.yaml), and [schema job](../cloudrun/cloudsql-init.yaml) are templates. Review image digests, instance sizing, IAM bindings, and public access policy before applying them in a production project.
