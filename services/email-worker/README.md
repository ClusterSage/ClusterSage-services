# Email Worker

Standalone service for ClusterSage notification email delivery.

## Owns

- Consuming notification messages from Azure Service Bus.
- Sending Azure Communication Services Email notifications.
- Handling cluster-connected emails and alert-threshold emails.
- Ensuring email failures do not break cluster connection or alert evaluation.

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
