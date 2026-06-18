from pathlib import Path


def test_cluster_delete_route_uses_hard_delete() -> None:
    router_path = Path(__file__).resolve().parents[1] / "app" / "clusters" / "router.py"
    source = router_path.read_text(encoding="utf-8")

    assert 'await session.delete(cluster)' in source
    assert '"cluster.deleted"' in source
    assert '"cluster.deactivated"' not in source
