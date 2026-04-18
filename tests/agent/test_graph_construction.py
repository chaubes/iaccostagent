"""Graph-compilation sanity tests (no LLM or backend required)."""

from iaccostagent.agent.graph import build_graph


class TestGraphConstruction:
    def test_graph_compiles(self) -> None:
        graph = build_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self) -> None:
        graph = build_graph()
        node_names = set(graph.get_graph().nodes.keys())
        expected = {
            "__start__",
            "__end__",
            "parse_terraform",
            "estimate_costs",
            "analyze_resources",
            "detect_patterns",
            "suggest_optimizations",
            "generate_report",
        }
        assert expected.issubset(node_names)
