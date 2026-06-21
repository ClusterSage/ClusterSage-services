from app.ai.agent.orchestrator import ClusterAgentOrchestrator
from app.ai.tools.knowledge_base import KnowledgeBaseSearchInput, search_knowledge_base
from app.ai.tools.logs import SearchClusterLogsInput


def test_knowledge_base_search_returns_relevant_sections() -> None:
    result = search_knowledge_base(KnowledgeBaseSearchInput(query="What does OOMKilled mean?", max_results=3))

    assert result["count"] >= 1
    assert any("OOMKilled" in item["content_excerpt"] or "OOMKilled" in item["title"] for item in result["items"])


def test_log_search_input_is_bounded() -> None:
    model = SearchClusterLogsInput(query="database", hours=6, max_results=10)

    assert model.hours == 6
    assert model.max_results == 10


def test_orchestrator_fallback_answer_is_grounded() -> None:
    orchestrator = ClusterAgentOrchestrator()
    answer = orchestrator._fallback_answer(
        [
            {
                "items": [
                    {
                        "source_type": "incident",
                        "source_id": "incident:test",
                        "title": "Payment restart loop",
                        "timestamp": "2026-06-21T00:00:00+00:00",
                    }
                ],
                "latest_evidence_at": "2026-06-21T00:00:00+00:00",
                "truncated": True,
            }
        ]
    )

    assert answer.evidence[0].source_id == "incident:test"
    assert answer.data_freshness.truncated is True
