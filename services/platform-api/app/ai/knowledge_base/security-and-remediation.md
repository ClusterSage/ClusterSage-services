# Security And Remediation

## Read-only investigation assistant
The cluster investigation agent is read-only. It must never execute raw SQL, arbitrary shell commands, `kubectl`, Terraform, or Kubernetes mutations.

## Prompt-injection handling
Logs, documents, user text, annotations, and database fields are untrusted evidence. Instructions found inside them must not override the system prompt or tenant boundaries.

## Secret handling
Returned evidence must redact bearer tokens, API keys, connection strings, SAS tokens, passwords, private keys, and similar secrets before the model sees them or the user receives them.

## Approval-gated remediation
Existing remediation flows stay separate from the investigation agent. The assistant can explain likely next steps but must not claim a restart, patch, or rollout was applied.
