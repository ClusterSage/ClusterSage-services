# ClusterSage Services

Service-oriented source tree for ClusterSage.

## Services

- `services/platform-api`: FastAPI API, DB migrations, ingestion, storage, notification publishing, issue detection, and email worker code.
- `services/email-worker`: logical service boundary. Runtime code currently remains in `platform-api/app/workers` and uses the platform API image.
- `services/collector-agent`: customer-installed collector service.

## Shared Libraries

`libs` is prepared for future technical-only utilities. It must not become a dumping ground for business logic.

## Validation

```bash
cd services/platform-api
python -m compileall app

cd ../collector-agent
python -m compileall app
```
