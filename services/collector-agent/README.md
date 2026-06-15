# Collector Agent

Customer-installed in-cluster collector for ClusterSage.

## Owns

- Registration with the ClusterSage API.
- Heartbeats.
- Kubernetes snapshots and events.
- Local Fluent Bit log receiver.
- Gzipped outbound sends to ingestion endpoints.

## Entrypoint

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Setup

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

## Docker

```bash
docker build -t clustersage-agent .
```
