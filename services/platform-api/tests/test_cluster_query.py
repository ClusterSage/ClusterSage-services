from app.ai.cluster_query import ClusterQueryService, parse_cluster_question


def test_parse_cluster_question_supports_crashloop_filters() -> None:
    parsed = parse_cluster_question("Show me all CrashLoopBackOff errors in prod from the last 1 hour.")

    assert parsed is not None
    assert parsed.payload["intent"] == "find_crashloop_errors"
    assert parsed.payload["namespace"] == "prod"
    assert parsed.payload["time_range"] == {"amount": 1, "unit": "hour"}
    assert parsed.payload["group_by"] == "pod"


def test_parse_cluster_question_extracts_log_search_text() -> None:
    parsed = parse_cluster_question('Find logs containing "database connection failure".')

    assert parsed is not None
    assert parsed.payload["intent"] == "find_logs_containing_text"
    assert parsed.payload["search_text"] == "database connection failure"


def test_parse_cluster_question_returns_none_for_unsupported_question() -> None:
    assert parse_cluster_question("Can you fix everything automatically?") is None


def test_summary_for_cluster_health_is_human_readable() -> None:
    service = ClusterQueryService()

    summary = service._summary_for_result(
        {"intent": "summarize_cluster_health"},
        {"incident_counts": {"critical": 2, "major": 3, "minor": 1}},
    )

    assert "2 critical" in summary
    assert "3 major" in summary
    assert "1 minor" in summary
