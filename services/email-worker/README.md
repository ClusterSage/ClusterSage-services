# Email Worker

Logical service boundary for the cluster-connected email worker.

The worker is currently implemented in `../platform-api/app/workers/email_worker.py` and deployed from the same backend image with this command:

```bash
python -m app.workers.email_worker
```

## Owns

- Consuming cluster-connected messages from Azure Service Bus.
- Sending Azure Communication Services Email notifications.
- Ensuring email failures do not break cluster connection.

## Split Readiness

This folder intentionally contains boundary documentation only in this phase. Extract code here later after the Service Bus message schema, shared config, and notification templates are stable enough for an independent package.
