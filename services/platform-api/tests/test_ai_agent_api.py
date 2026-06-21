from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.clusters import router as clusters_router
from app.core.config import settings
from app.db.session import get_session
from app.main import app
from app.models.entities import AIConversation, AIMessage, Cluster, User


class FakeSession:
    def __init__(self, cluster: Cluster) -> None:
        self.cluster = cluster

    async def get(self, model, identity):
        if model is Cluster and identity == self.cluster.id:
            return self.cluster
        return None


def _make_user_and_cluster() -> tuple[User, Cluster]:
    organization_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        organization_id=organization_id,
        email="owner@example.com",
        password_hash="hashed",
        role="owner",
    )
    cluster = Cluster(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name="prod-aks",
        provider="aks",
        status="healthy",
    )
    return user, cluster


def test_ai_chat_endpoint_returns_conversation_payload(monkeypatch) -> None:
    user, cluster = _make_user_and_cluster()
    fake_session = FakeSession(cluster)
    created_at = datetime.now(timezone.utc)
    conversation = AIConversation(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        cluster_id=cluster.id,
        user_id=user.id,
        title="Payment restarts",
        created_at=created_at,
        updated_at=created_at,
    )
    message = AIMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        organization_id=user.organization_id,
        cluster_id=cluster.id,
        role="assistant",
        content="The payment pods are restarting after repeated OOM kills.",
        evidence_references=[{"source_type": "incident", "source_id": "incident:test", "title": "Payment OOMKilled"}],
        tool_execution_metadata=[{"tool_name": "list_cluster_incidents", "status": "ok"}],
        confidence="medium",
        data_freshness={"latest_evidence_at": created_at.isoformat(), "truncated": False},
        created_at=created_at,
    )

    class FakeOrchestrator:
        async def chat(self, **kwargs):
            assert kwargs["message"] == "Why are payment pods restarting?"
            return conversation, message

    async def override_current_user():
        return user

    async def override_session():
        yield fake_session

    monkeypatch.setattr(settings, "ai_agent_enabled", True)
    monkeypatch.setattr(clusters_router, "cluster_agent_orchestrator", FakeOrchestrator())
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        response = client.post(
            f"/api/clusters/{cluster.id}/ai/chat",
            json={"message": "Why are payment pods restarting?"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["conversation_id"] == str(conversation.id)
    assert payload["message_id"] == str(message.id)
    assert payload["confidence"] == "medium"
    assert payload["tools_used"] == ["list_cluster_incidents"]


def test_ai_conversation_endpoints_return_history(monkeypatch) -> None:
    user, cluster = _make_user_and_cluster()
    fake_session = FakeSession(cluster)
    created_at = datetime.now(timezone.utc)
    conversation = AIConversation(
        id=uuid.uuid4(),
        organization_id=user.organization_id,
        cluster_id=cluster.id,
        user_id=user.id,
        title="Checkout unhealthy",
        summary="Investigating checkout deployment health",
        created_at=created_at,
        updated_at=created_at,
    )
    messages = [
        AIMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            user_id=user.id,
            role="user",
            content="Why is checkout unhealthy?",
            created_at=created_at,
        ),
        AIMessage(
            id=uuid.uuid4(),
            conversation_id=conversation.id,
            organization_id=user.organization_id,
            cluster_id=cluster.id,
            role="assistant",
            content="Checkout shows repeated probe failures.",
            evidence_references=[{"source_type": "log", "source_id": "log:test", "title": "checkout logs"}],
            created_at=created_at,
        ),
    ]

    class FakeOrchestrator:
        async def list_conversations(self, **kwargs):
            return [conversation]

        async def get_conversation(self, **kwargs):
            return conversation, messages

    async def override_current_user():
        return user

    async def override_session():
        yield fake_session

    monkeypatch.setattr(settings, "ai_agent_enabled", True)
    monkeypatch.setattr(clusters_router, "cluster_agent_orchestrator", FakeOrchestrator())
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        list_response = client.get(f"/api/clusters/{cluster.id}/ai/conversations")
        detail_response = client.get(f"/api/clusters/{cluster.id}/ai/conversations/{conversation.id}")
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == str(conversation.id)
    assert detail_response.status_code == 200
    assert detail_response.json()["conversation"]["id"] == str(conversation.id)
    assert len(detail_response.json()["messages"]) == 2


def test_ai_agent_endpoints_return_feature_disabled_when_flag_off(monkeypatch) -> None:
    user, cluster = _make_user_and_cluster()
    fake_session = FakeSession(cluster)

    async def override_current_user():
        return user

    async def override_session():
        yield fake_session

    monkeypatch.setattr(settings, "ai_agent_enabled", False)
    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_session] = override_session
    try:
        client = TestClient(app)
        response = client.get(f"/api/clusters/{cluster.id}/ai/conversations")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"] == "AI agent is disabled in this environment"
