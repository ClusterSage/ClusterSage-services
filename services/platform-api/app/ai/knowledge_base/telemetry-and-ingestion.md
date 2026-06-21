# Telemetry And Ingestion

## Supported telemetry
ClusterSage stores compressed log batches, event payloads, snapshots, and runtime metrics. Snapshot data includes resources such as pods, deployments, services, replica sets, stateful sets, daemon sets, jobs, cron jobs, and namespaces.

## Ingestion flow
The customer agent registers, sends heartbeats, and posts logs, events, snapshots, and metrics. The backend writes raw telemetry to Blob Storage and stores searchable metadata in PostgreSQL.

## Snapshot data
Snapshot summaries can reveal pod restart counts, pod phases, deployment availability, namespace health, and workload ownership hints. They are useful for compact cluster health summaries but may lag the live cluster.

## Known limitations
The platform works from stored telemetry. It does not execute live `kubectl` queries from the AI assistant, and it must not scan entire log archives or return full log files.
