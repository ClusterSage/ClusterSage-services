# Cluster Investigation

## Investigation workflow
Good investigations combine incidents, issues, snapshots, deployments, and bounded log excerpts. The assistant should gather only enough evidence to answer the user's question and explain when results were truncated.

## Deployment correlation
Recent deployments can help determine whether failures started after a rollout. Correlation should use stored deployment timestamps and incident timing, not speculation.

## Workload status
Workload checks should summarize current stored state, related pods, restart counts, and linked incidents or issues. They should stay compact and cluster-scoped.

## Next-step guidance
When evidence is incomplete, the assistant should suggest what to inspect next, such as recent logs, probe failures, restarts, image pull errors, or rollout timing.
