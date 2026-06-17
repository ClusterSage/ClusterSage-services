import importlib
import os


def load_actions_module():
    os.environ.setdefault("CLUSTERWATCH_BACKEND_URL", "https://example.com")
    os.environ.setdefault("CLUSTERWATCH_EMAIL", "owner@example.com")
    os.environ.setdefault("CLUSTERWATCH_ACCESS_KEY", "cw_test_key")
    os.environ.setdefault("CLUSTERWATCH_CLUSTER_NAME", "prod-cluster")
    os.environ.setdefault("CLUSTERWATCH_REMEDIATION_ENABLED", "true")
    os.environ.setdefault("CLUSTERWATCH_REMEDIATION_ALLOWED_NAMESPACES", "prod,platform")
    os.environ.setdefault("CLUSTERWATCH_REMEDIATION_ALLOWED_ACTIONS", "rollout_restart")

    config = importlib.import_module("app.config")
    importlib.reload(config)
    actions = importlib.import_module("app.actions")
    importlib.reload(actions)
    return actions


def test_capabilities_payload_reflects_current_settings() -> None:
    actions = load_actions_module()

    payload = actions.capabilities_payload()

    assert payload["remediation_enabled"] is True
    assert payload["cluster_wide"] is False
    assert payload["allowed_namespaces"] == ["prod", "platform"]
    assert payload["allowed_actions"] == ["rollout_restart"]


def test_validate_action_accepts_allowed_deployment_restart(monkeypatch) -> None:
    actions = load_actions_module()
    models = importlib.import_module("app.models")
    state = models.AgentState(cluster_id="cluster-1")

    monkeypatch.setattr(actions, "get_deployment", lambda namespace, name: {"namespace": namespace, "name": name})
    action = {
        "cluster_id": "cluster-1",
        "action_type": "rollout_restart",
        "action_payload": {
            "workload_kind": "Deployment",
            "workload_name": "platform-api",
            "namespace": "prod",
        },
    }

    target = actions.validate_action(state, action)

    assert target == {
        "namespace": "prod",
        "workload_kind": "Deployment",
        "workload_name": "platform-api",
    }


def test_validate_action_rejects_disallowed_namespace(monkeypatch) -> None:
    actions = load_actions_module()
    models = importlib.import_module("app.models")
    state = models.AgentState(cluster_id="cluster-1")

    monkeypatch.setattr(actions, "get_deployment", lambda namespace, name: {"namespace": namespace, "name": name})
    action = {
        "cluster_id": "cluster-1",
        "action_type": "rollout_restart",
        "action_payload": {
            "workload_kind": "Deployment",
            "workload_name": "platform-api",
            "namespace": "finance",
        },
    }

    try:
        actions.validate_action(state, action)
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("validate_action should reject namespaces outside the allowlist")
