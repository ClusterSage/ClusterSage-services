# Glossary

## Cluster health
Cluster health is a compact interpretation of stored incidents, workload availability, restart activity, and snapshot status. It is not a hidden live health score.

## Incident
An incident is a stored AI-enriched cluster problem record built from grouped evidence such as logs.

## Issue
An issue is a deterministic platform-detected problem derived from events or snapshots.

## Snapshot
A snapshot is a stored representation of cluster resources captured by the agent.

## CrashLoopBackOff
A pod is repeatedly starting and crashing.

## OOMKilled
A container exceeded its memory limit and was terminated.

## ImagePullBackOff or ErrImagePull
The cluster could not pull the requested container image.

## Probe failure
Readiness or liveness checks are failing, so the workload may not become healthy or may restart.

## RBAC or permission failure
The workload or platform tried an action that Kubernetes or another system denied.
