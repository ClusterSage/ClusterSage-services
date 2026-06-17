import asyncio
import logging
from typing import Any

from kubernetes.client import ApiException

from app.config import settings
from app.kubernetes_client import apply_rollout_restart, get_deployment
from app.models import AgentState
from app.sender import post_json_with_retry

log = logging.getLogger(__name__)


def capabilities_payload() -> dict[str, Any]:
    return {
        "remediation_enabled": settings.clusterwatch_remediation_enabled,
        "cluster_wide": settings.clusterwatch_remediation_cluster_wide,
        "allowed_namespaces": settings.remediation_allowed_namespaces,
        "allowed_actions": settings.remediation_allowed_actions,
        "agent_version": settings.clusterwatch_agent_version,
    }


def validate_action(state: AgentState, action: dict[str, Any]) -> dict[str, str]:
    if action.get("cluster_id") != state.cluster_id:
        raise ValueError("action does not belong to this cluster")
    if action.get("action_type") != "rollout_restart":
        raise ValueError("unsupported action type")
    if not settings.clusterwatch_remediation_enabled:
        raise ValueError("agent remediation is disabled")
    if "rollout_restart" not in settings.remediation_allowed_actions:
        raise ValueError("rollout_restart is not allowed by agent configuration")

    payload = action.get("action_payload")
    if not isinstance(payload, dict):
        raise ValueError("action payload is missing")

    workload_kind = str(payload.get("workload_kind") or "")
    workload_name = str(payload.get("workload_name") or "")
    namespace = str(payload.get("namespace") or "")
    if workload_kind != "Deployment":
        raise ValueError("only Deployment rollout restarts are supported")
    if not workload_name or not namespace:
        raise ValueError("deployment target is incomplete")

    if not settings.clusterwatch_remediation_cluster_wide:
        allowed_namespaces = settings.remediation_allowed_namespaces
        if not allowed_namespaces:
            raise ValueError("no remediation namespaces are configured")
        if namespace not in allowed_namespaces:
            raise ValueError(f"namespace '{namespace}' is not allowed for remediation")

    try:
        get_deployment(namespace, workload_name)
    except ApiException as exc:
        if exc.status == 404:
            raise ValueError("target deployment does not exist") from exc
        raise

    return {
        "namespace": namespace,
        "workload_kind": workload_kind,
        "workload_name": workload_name,
    }


async def report_capabilities_once(state: AgentState) -> None:
    if state.capabilities_reported:
        return
    await post_json_with_retry(state, "/api/agent/capabilities", capabilities_payload())
    state.capabilities_reported = True


async def report_action_status(state: AgentState, action_id: str, *, status: str, result: dict[str, Any] | None = None, error_message: str | None = None) -> None:
    await post_json_with_retry(
        state,
        f"/api/agent/actions/{action_id}/status",
        {
            "status": status,
            "result": result,
            "error_message": error_message,
        },
    )


async def process_action(state: AgentState, action: dict[str, Any]) -> None:
    action_id = str(action.get("id") or "")
    if not action_id:
        return
    if action_id in state.completed_action_ids or action_id in state.active_action_ids:
        return

    state.active_action_ids.add(action_id)
    try:
        target = validate_action(state, action)
        await report_action_status(state, action_id, status="running", result={"message": "validation passed"})
        result = await asyncio.to_thread(
            apply_rollout_restart,
            action_id,
            target["namespace"],
            target["workload_name"],
        )
        await report_action_status(state, action_id, status="succeeded", result=result)
        state.completed_action_ids.add(action_id)
    except Exception as exc:
        log.error("action execution failed action_id=%s error=%s", action_id, exc)
        try:
            await report_action_status(state, action_id, status="failed", error_message=str(exc))
        except Exception as report_exc:
            log.error("failed to report action failure action_id=%s error=%s", action_id, report_exc)
    finally:
        state.active_action_ids.discard(action_id)


async def action_loop(state: AgentState) -> None:
    while True:
        try:
            await report_capabilities_once(state)
            response = await post_json_with_retry(state, "/api/agent/actions/poll", {})
            actions = response.get("actions") if isinstance(response, dict) else []
            if isinstance(actions, list):
                for action in actions:
                    if isinstance(action, dict):
                        await process_action(state, action)
        except Exception as exc:
            log.error("action polling failed: %s", exc)
        await asyncio.sleep(settings.clusterwatch_remediation_poll_interval_seconds)
