# Platform API

FastAPI service for ClusterSage.

## Owns

- User registration/login and JWT auth.
- Agent key management.
- Agent registration and heartbeat.
- Log, event, and snapshot ingestion.
- Cluster/resource/log/issue APIs.
- Audit logs.
- Blob storage reads/writes.
- Service Bus notification publishing.
- Alembic migrations and PostgreSQL metadata models.

## Entrypoints

API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Setup

```bash
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
```

## Docker

```bash
docker build -t clustersage-backend .
```

The image uses a multi-stage build and the runtime container runs as a non-root application user.
