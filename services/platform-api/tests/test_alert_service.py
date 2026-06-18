from app.alerts.service import compare_threshold, metric_label, operator_label


def test_compare_threshold_supports_all_supported_operators() -> None:
    assert compare_threshold("gt", 6, 5) is True
    assert compare_threshold("gte", 5, 5) is True
    assert compare_threshold("lt", 4, 5) is True
    assert compare_threshold("lte", 5, 5) is True
    assert compare_threshold("eq", 5, 5) is True


def test_metric_and_operator_labels_are_human_readable() -> None:
    assert metric_label("warning_events") == "Warning events"
    assert operator_label("gte") == ">="
