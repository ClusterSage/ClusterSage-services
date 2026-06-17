# ClusterSage Services

Service-oriented source tree for ClusterSage.

## Services

- `services/platform-api`: FastAPI API, DB migrations, ingestion, storage, notification publishing, and issue detection.
- `services/email-worker`: standalone cluster-connected email worker.
- `services/collector-agent`: customer-installed collector service.

## Shared Libraries

`libs` is prepared for future technical-only utilities. It must not become a dumping ground for business logic.

## Validation

```bash
cd services/platform-api
python -m compileall app
pytest
alembic upgrade head --sql > migration-preview.sql

cd ../email-worker
python -m compileall app

cd ../collector-agent
python -m compileall app
pytest
```
