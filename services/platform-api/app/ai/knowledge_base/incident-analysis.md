# Incident Analysis

## Incident lifecycle
Log ingestion stores raw batches first, then performs deterministic grouping and optional Azure AI analysis without blocking ingestion success. Findings can become AI incidents and remediation suggestions.

## Severity definitions
- `critical`: crash loops, OOM kills, or failures that indicate severe workload instability.
- `major`: image pull failures, database connectivity failures, permission failures, or repeated application errors.
- `minor`: warnings, lower-severity anomalies, and timeouts that still deserve operator review.

## Safety model
AI-generated remediation suggestions are advisory by default. Rollout restart suggestions require approval and must not imply that a change has already been executed.

## Common Kubernetes failures
CrashLoopBackOff usually points to repeated startup/runtime crashes. OOMKilled means the container exceeded memory limits. ImagePullBackOff and ErrImagePull indicate image fetch failures. Probe failures suggest readiness or liveness checks are failing. DNS, database, or RBAC failures often appear first in logs and incident summaries.
