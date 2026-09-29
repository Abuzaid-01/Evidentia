# Evidentia Deployment Guide (Render & Vercel)

This guide walks you through deploying **Evidentia** into production:
- **Backend API & Celery Worker**: [Render](https://render.com)
- **Database**: Render PostgreSQL (with pgvector)
- **Queue/Cache**: Render Redis / Upstash Redis
- **Frontend Dashboard**: [Vercel](https://vercel.com)

---

## 1. Prerequisites & Services Needed

Before starting, ensure you have accounts on:
1. **GitHub** (with repo `https://github.com/Abuzaid-01/Evidentia.git`)
2. **Render** (free or paid account)
3. **Vercel** (free Hobby or Pro account)
4. **Cloudinary** (Cloud Name, API Key, API Secret)
5. **Google AI Studio** (`GEMINI_API_KEY`)
6. **Groq** (`GROQ_API_KEY`)

---

## 2. Deploy Backend & Database on Render

### Option A: Using `render.yaml` (Recommended / Blueprint)

1. Go to your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** -> **Blueprint**.
3. Connect your GitHub repository: `Abuzaid-01/Evidentia`.
4. Render will read `render.yaml` and create:
   - **evidentia-db** (Managed PostgreSQL)
   - **evidentia-api** (FastAPI Web Service)
   - **evidentia-worker** (Celery Background Worker)
5. Fill in the required secret environment variables prompted by Render:
   - `CLOUDINARY_URL`: `cloudinary://<api_key>:<api_secret>@<cloud_name>`
   - `GEMINI_API_KEY`: Your Gemini API key
   - `GROQ_API_KEY`: Your Groq API key
   - `REDIS_URL`: Your Redis connection URL (from Render Key-Value or Upstash Redis)
6. Click **Apply**.

---

### Option B: Manual Service Creation on Render

If you prefer setting up services individually:

#### Step 1: Create PostgreSQL Database
1. Click **New +** -> **PostgreSQL**.
2. **Name**: `evidentia-db`
3. **Database**: `evidentia`
4. **User**: `evidentia`
5. Click **Create Database**.
6. Copy the **Internal Database URL** (e.g. `postgres://evidentia:...@.../evidentia`).

#### Step 2: Create Redis Instance
1. Click **New +** -> **Redis** (or create a free Redis database on [Upstash](https://upstash.com)).
2. Copy the **Internal Redis URL** (e.g. `redis://red-...:6379`).

#### Step 3: Create Web Service (FastAPI)
1. Click **New +** -> **Web Service**.
2. Connect your repo `Abuzaid-01/Evidentia`.
3. Configure:
   - **Name**: `evidentia-api`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install uv && uv sync`
   - **Start Command**: `uv run alembic upgrade head && uv run uvicorn evidentia_api.main:app --host 0.0.0.0 --port $PORT`
   - **Health Check Path**: `/healthz`
4. Add Environment Variables:
   | Variable | Value |
   |---|---|
   | `PYTHON_VERSION` | `3.12.8` |
   | `ENVIRONMENT` | `production` |
   | `DATABASE_URL` | `postgresql+psycopg://evidentia:...@.../evidentia` *(replace `postgres://` with `postgresql+psycopg://`)* |
   | `REDIS_URL` | `<Your Redis Connection String>` |
   | `CLOUDINARY_URL` | `cloudinary://<api_key>:<api_secret>@<cloud_name>` |
   | `GEMINI_API_KEY` | `<your-gemini-api-key>` |
   | `GROQ_API_KEY` | `<your-groq-api-key>` |
   | `AUTH_MODE` | `dev` *(or `clerk` for production auth)* |
   | `EMBEDDINGS_ENABLED` | `false` *(recommended for free tier memory limits; uses text+tags+Cloudinary search)* |
   | `DEMO_MODE_ENABLED` | `true` |
   | `API_CORS_ORIGINS` | `https://your-app.vercel.app` *(update once Vercel is deployed)* |
   | `PUBLIC_API_BASE_URL` | `https://evidentia-api.onrender.com` |
   | `WEB_BASE_URL` | `https://your-app.vercel.app` |

#### Step 4: Create Background Worker (Celery)
1. Click **New +** -> **Background Worker**.
2. Connect your repo `Abuzaid-01/Evidentia`.
3. Configure:
   - **Name**: `evidentia-worker`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install uv && uv sync`
   - **Start Command**: `uv run celery -A evidentia_worker.celery_app worker -Q ingest,analysis,maintenance,reports,ml --pool=threads --concurrency=2 --loglevel=INFO`
4. Add Environment Variables:
   - Same `DATABASE_URL`, `REDIS_URL`, `CLOUDINARY_URL`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `EMBEDDINGS_ENABLED=false`.

---

## 3. Deploy Frontend on Vercel

1. Go to [Vercel Dashboard](https://vercel.com/dashboard) and click **Add New...** -> **Project**.
2. Import the `Abuzaid-01/Evidentia` repository.
3. In **Project Configuration**:
   - **Framework Preset**: `Next.js`
   - **Root Directory**: Click **Edit** and choose `apps/web`.
4. In **Build and Output Settings**:
   - Leave defaults (`pnpm build`).
5. In **Environment Variables**, add:
   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | `https://evidentia-api.onrender.com` *(your Render API URL)* |
   | `NEXT_PUBLIC_AUTH_MODE` | `dev` *(or `clerk`)* |
6. Click **Deploy**.

---

## 4. Post-Deployment Checklist

1. **Verify API Health:**
   Visit `https://evidentia-api.onrender.com/healthz` — should return `{"status":"ok"}`.
2. **Cloudinary Webhooks:**
   In your Cloudinary Console > Settings > Webhooks, set notification URL to:
   `https://evidentia-api.onrender.com/v1/webhooks/cloudinary`
3. **Verify Web App:**
   Visit `https://your-app.vercel.app` and try creating a project or uploading an asset.
