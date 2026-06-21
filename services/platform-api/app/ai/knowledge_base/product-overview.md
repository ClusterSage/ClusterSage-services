# ClusterSage Product Overview

## What ClusterSage does
ClusterSage is a multi-tenant Kubernetes observability SaaS. A customer-installed agent runs inside the customer cluster and pushes telemetry outward to the platform API over HTTPS. The SaaS does not require direct access to the customer's Azure subscription and does not rely on Azure Lighthouse.

## Core architecture
The platform has a Next.js frontend, a FastAPI platform API, a standalone email worker, PostgreSQL for metadata, and Azure Blob Storage for compressed raw telemetry such as logs, events, and snapshots.

## Tenant and cluster isolation
Users, clusters, incidents, audit records, and agent conversations are scoped by organization and cluster. Blob paths use `orgId=` and `clusterId=` prefixes, and backend database queries are expected to apply organization and cluster filters.

## Data freshness and limitations
Cluster answers are limited to stored telemetry already collected from the selected cluster. Missing snapshots, unavailable logs, or delayed ingestion can reduce confidence and completeness.
