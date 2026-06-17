# Email Worker

Standalone service for the cluster-connected email worker.

## Owns

- Consuming cluster-connected messages from Azure Service Bus.
- Sending Azure Communication Services Email notifications.
- Ensuring email failures do not break cluster connection.

## Entrypoint

```bash
python -m app.main
```

## Setup

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

## Docker

```bash
docker build -t clustersage-email-worker .
```
