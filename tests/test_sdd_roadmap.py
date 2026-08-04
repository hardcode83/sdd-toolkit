from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sdd_roadmap  # noqa: E402
from sdd_roadmap import Graph, parse_roadmap  # noqa: E402


NEW_FORMAT = """# Roadmap

<!-- The template ships its own legend, which looks exactly like metadata:
       needs:  a hard dependency
       size: S | M | L
-->

## Stage 1 — el dominio existe y persiste

- [x] domain — [BE] entidades base
      size: L · kind: feature
- [ ] jobs — [BE] runner de jobs
      needs: domain · size: M · kind: infra

## Stage 2 — reservas entrando por webhook

- [ ] webhooks — [BE] recepción de webhooks
      needs: domain, jobs · size: M · kind: feature
- [ ] spike — [BE] medir el proveedor
      size: S · kind: spike
- [ ] adapter — [BE] adaptador real
      needs: jobs · informs-from: spike · size: L · kind: feature
- [ ] hardening — [INFRA] mitigar el residual
      size: S · kind: fix
- [ ] ingress — [INFRA] camino desde internet
      deferred-until: el frontend invoque getServerConfig() · size: M
"""

LEGACY_FORMAT = """# Roadmap

- [x] first — hecho hace tiempo → changes/archive/2026-01-01-first/
- [ ] second — pendiente, sin metadatos
- [ ] third — también pendiente
"""


def build(content: str, **files: str) -> Path:
    """A throwaway project root carrying `content` as its roadmap."""
    directory = tempfile.mkdtemp()
    root = Path(directory)
    (root / "sdd").mkdir()
    (root / "sdd" / "roadmap.md").write_text(content, encoding="utf-8")
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def graph_of(content: str, **files: str) -> Graph:
    root = build(content, **files)
    return Graph(root, parse_roadmap(root / "sdd" / "roadmap.md"))


def state_file(state: str) -> str:
    return f"---\nschema: 1\nstate: {state}\n---\n"


def codes(graph: Graph) -> list[str]:
    return [finding.code for finding in graph.validate()]


class ParsingTests(unittest.TestCase):
    def test_parses_stages_metadata_and_relations(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(
            ["domain", "jobs", "webhooks", "spike", "adapter", "hardening", "ingress"],
            [entry.feature for entry in graph.entries],
        )
        jobs = graph.by_feature["jobs"]
        self.assertEqual("Stage 1 — el dominio existe y persiste", jobs.stage)
        self.assertEqual(("domain",), jobs.edges["needs"])
        self.assertEqual("M", jobs.size)
        self.assertEqual("infra", jobs.kind)
        self.assertEqual("[BE] runner de jobs", jobs.summary)

    def test_an_entry_can_depend_on_several_others(self) -> None:
        """The graph is a DAG, not a tree — the reason indentation was rejected."""
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(("domain", "jobs"), graph.by_feature["webhooks"].predecessors)

    def test_ordering_relations_other_than_needs_also_constrain(self) -> None:
        graph = graph_of(NEW_FORMAT)
        adapter = graph.by_feature["adapter"]
        self.assertEqual(("spike",), adapter.edges["informs-from"])
        self.assertIn("spike", adapter.predecessors)

    def test_html_comments_never_become_metadata(self) -> None:
        """The template's legend is indented and key-shaped; it must be skipped."""
        graph = graph_of(NEW_FORMAT)
        self.assertEqual((), graph.by_feature["domain"].edges.get("needs", ()))
        self.assertEqual("L", graph.by_feature["domain"].size)

    def test_deferred_until_keeps_its_free_text(self) -> None:
        graph = graph_of(NEW_FORMAT)
        ingress = graph.by_feature["ingress"]
        self.assertEqual("el frontend invoque getServerConfig()", ingress.deferred_until)
        self.assertEqual((), ingress.predecessors)

    def test_prose_lines_are_not_metadata(self) -> None:
        graph = graph_of(
            "- [ ] alpha — algo\n"
            "      esto es prosa indentada sin claves conocidas\n"
        )
        self.assertEqual({}, graph.by_feature["alpha"].edges)
        self.assertEqual("", graph.by_feature["alpha"].size)

    def test_metadata_may_span_several_sub_lines(self) -> None:
        graph = graph_of(
            "- [ ] alpha — algo\n"
            "- [ ] beta — otra cosa\n"
            "      needs: alpha\n"
            "      size: L · kind: fix\n"
        )
        beta = graph.by_feature["beta"]
        self.assertEqual(("alpha",), beta.edges["needs"])
        self.assertEqual("L", beta.size)
        self.assertEqual("fix", beta.kind)

    def test_a_blank_line_closes_the_metadata_window(self) -> None:
        graph = graph_of("- [ ] alpha — algo\n\n      needs: beta\n")
        self.assertEqual({}, graph.by_feature["alpha"].edges)


class LegacyTests(unittest.TestCase):
    def test_flat_roadmap_parses_and_degrades_to_one_wave(self) -> None:
        graph = graph_of(LEGACY_FORMAT)
        self.assertEqual(
            ["second", "third"], [entry.feature for entry in graph.frontier()]
        )
        self.assertEqual(1, len(graph.waves()))
        self.assertFalse(graph.has_edges())

    def test_legacy_archive_pointer_is_still_captured(self) -> None:
        graph = graph_of(LEGACY_FORMAT)
        self.assertEqual(
            "changes/archive/2026-01-01-first", graph.by_feature["first"].pointer
        )

    def test_indented_list_item_is_an_independent_entry(self) -> None:
        """Documents the hazard that ruled out expressing hierarchy by indent."""
        graph = graph_of("- [ ] parent — uno\n  - [ ] child — dos\n")
        self.assertEqual(["parent", "child"], [e.feature for e in graph.entries])
        self.assertEqual((), graph.by_feature["child"].predecessors)


class DerivedStateTests(unittest.TestCase):
    def test_status_comes_from_state_md_not_from_the_roadmap(self) -> None:
        graph = graph_of(
            "- [ ] alpha — algo\n",
            **{"sdd/changes/alpha/STATE.md": state_file("PR_OPEN")},
        )
        self.assertEqual("PR_OPEN", graph.status["alpha"])
        self.assertEqual("PR", sdd_roadmap.status_symbol("PR_OPEN"))

    def test_a_non_empty_blocked_file_outranks_the_lifecycle_state(self) -> None:
        graph = graph_of(
            "- [ ] alpha — algo\n",
            **{
                "sdd/changes/alpha/STATE.md": state_file("ACTIVE"),
                "sdd/changes/alpha/BLOCKED.md": "- phase: run · decision: ¿cuál?\n",
            },
        )
        self.assertEqual("BLOCKED", graph.status["alpha"])

    def test_an_archive_on_disk_closes_the_entry(self) -> None:
        graph = graph_of(
            "- [ ] alpha — algo\n- [ ] beta — otra\n      needs: alpha\n",
            **{"sdd/changes/archive/2026-01-01-alpha/proposal.md": "# Proposal\n"},
        )
        self.assertEqual("ARCHIVED", graph.status["alpha"])
        self.assertTrue(graph.closed["alpha"])
        self.assertEqual(["beta"], [e.feature for e in graph.frontier()])

    def test_a_cancelled_entry_is_never_proposed_as_workable(self) -> None:
        """It is not closed either, so it would otherwise sit in the frontier."""
        graph = graph_of(
            "- [ ] alpha — cancelada\n- [ ] beta — libre\n",
            **{"sdd/changes/alpha/STATE.md": state_file("CANCELLED")},
        )
        self.assertEqual(["beta"], [e.feature for e in graph.frontier()])
        self.assertEqual([["beta"]], [[e.feature for e in w] for w in graph.waves()])
        self.assertEqual(["alpha"], [e.feature for e in graph.cancelled()])

    def test_a_cancelled_dependency_keeps_blocking_its_successor(self) -> None:
        graph = graph_of(
            "- [ ] alpha — cancelada\n- [ ] beta — la espera\n      needs: alpha\n",
            **{"sdd/changes/alpha/STATE.md": state_file("CANCELLED")},
        )
        self.assertFalse(graph.closed["alpha"])
        self.assertEqual([], graph.frontier())
        report = sdd_roadmap.render_report(graph)
        self.assertIn("Canceladas", report)
        self.assertIn("bloquea: beta", report)

    def test_ready_for_pr_does_not_unblock_a_successor(self) -> None:
        """Nothing is merged behind READY_FOR_PR, so it cannot close a dependency."""
        graph = graph_of(
            "- [ ] alpha — algo\n- [ ] beta — otra\n      needs: alpha\n",
            **{"sdd/changes/alpha/STATE.md": state_file("READY_FOR_PR")},
        )
        self.assertFalse(graph.closed["alpha"])
        self.assertEqual(["alpha"], [e.feature for e in graph.frontier()])


class FrontierTests(unittest.TestCase):
    def test_frontier_is_exactly_the_first_wave(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(
            [entry.feature for entry in graph.frontier()],
            [entry.feature for entry in graph.waves()[0]],
        )

    def test_frontier_holds_only_entries_with_every_dependency_closed(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(
            ["jobs", "spike", "hardening"], [e.feature for e in graph.frontier()]
        )

    def test_waves_order_dependants_after_their_dependencies(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(
            [["jobs", "spike", "hardening"], ["webhooks", "adapter"]],
            [[e.feature for e in level] for level in graph.waves()],
        )

    def test_a_deferred_entry_is_neither_in_the_frontier_nor_in_a_wave(self) -> None:
        graph = graph_of(NEW_FORMAT)
        scheduled = {e.feature for level in graph.waves() for e in level}
        self.assertNotIn("ingress", scheduled)
        self.assertNotIn("ingress", {e.feature for e in graph.frontier()})
        self.assertEqual(["ingress"], [e.feature for e in graph.deferred()])

    def test_an_unknown_dependency_blocks_rather_than_being_ignored(self) -> None:
        graph = graph_of("- [ ] alpha — algo\n      needs: typo-name\n")
        self.assertEqual([], graph.frontier())
        self.assertIn("SDD019", codes(graph))

    def test_leaves_are_entries_nothing_waits_on(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(["hardening"], [e.feature for e in graph.leaves()])

    def test_successors_report_what_closing_an_entry_unblocks(self) -> None:
        graph = graph_of(NEW_FORMAT)
        self.assertEqual(("webhooks", "adapter"), graph.successors("jobs"))
        self.assertEqual((), graph.successors("hardening"))


class CriticalPathTests(unittest.TestCase):
    def test_weights_the_chain_by_size(self) -> None:
        graph = graph_of(NEW_FORMAT)
        path = graph.critical_path("Stage 2")
        self.assertEqual(["spike", "adapter"], [e.feature for e in path])
        self.assertEqual(4, sum(e.weight for e in path))

    def test_resolves_a_dependency_declared_later_in_the_file(self) -> None:
        """File order is not a valid order: the DP must sort topologically."""
        graph = graph_of(
            "- [ ] last — depende de la de abajo\n"
            "      needs: first · size: L\n"
            "- [ ] first — declarada después\n"
            "      size: L\n"
        )
        self.assertEqual(
            ["first", "last"], [e.feature for e in graph.critical_path()]
        )

    def test_an_absent_size_counts_as_medium(self) -> None:
        graph = graph_of("- [ ] alpha — sin size\n")
        self.assertEqual(
            sdd_roadmap.DEFAULT_WEIGHT, graph.by_feature["alpha"].weight
        )


class ValidationTests(unittest.TestCase):
    def test_duplicate_entry(self) -> None:
        graph = graph_of("- [ ] alpha — una\n- [ ] alpha — otra\n")
        self.assertIn("SDD018", codes(graph))

    def test_a_duplicate_cannot_make_the_views_contradict_the_graph(self) -> None:
        """`by_feature` keeps the first entry, so everything derived must too."""
        graph = graph_of("- [x] alpha — cerrada\n- [ ] alpha — duplicada abierta\n")
        self.assertTrue(graph.closed["alpha"])
        self.assertEqual([], [e.feature for e in graph.open_entries()])
        self.assertIn("SDD018", codes(graph))

    def test_a_duplicate_does_not_report_the_same_broken_edge_twice(self) -> None:
        graph = graph_of(
            "- [ ] alpha — una\n      needs: missing\n"
            "- [ ] alpha — otra\n      needs: missing\n"
        )
        self.assertEqual(1, codes(graph).count("SDD019"))

    def test_cycle_is_reported_and_terminates(self) -> None:
        graph = graph_of(
            "- [ ] alpha — a\n      needs: beta\n- [ ] beta — b\n      needs: alpha\n"
        )
        self.assertIn("SDD020", codes(graph))
        self.assertEqual(1, len(graph.cycles()))

    def test_a_cycle_is_reported_once_regardless_of_entry_point(self) -> None:
        graph = graph_of(
            "- [ ] alpha — a\n      needs: gamma\n"
            "- [ ] beta — b\n      needs: alpha\n"
            "- [ ] gamma — c\n      needs: beta\n"
        )
        self.assertEqual(1, len(graph.cycles()))
        self.assertEqual(("alpha", "gamma", "beta"), graph.cycles()[0])

    def test_a_cycle_leaves_entries_unscheduled_instead_of_looping(self) -> None:
        graph = graph_of(
            "- [ ] alpha — a\n      needs: beta\n"
            "- [ ] beta — b\n      needs: alpha\n"
            "- [ ] gamma — libre\n"
        )
        self.assertEqual([["gamma"]], [[e.feature for e in w] for w in graph.waves()])

    def test_closed_entry_with_an_open_dependency(self) -> None:
        graph = graph_of("- [x] alpha — cerrada\n      needs: beta\n- [ ] beta — abierta\n")
        self.assertIn("SDD021", codes(graph))

    def test_unknown_metadata_key_is_warned_not_silently_dropped(self) -> None:
        graph = graph_of("- [ ] alpha — algo\n      need: beta\n- [ ] beta — otra\n")
        self.assertIn("SDD022", codes(graph))

    def test_an_incidental_url_sub_line_is_not_read_as_metadata(self) -> None:
        """`https://…` is field-shaped; only a recognisable key makes it metadata."""
        graph = graph_of("- [ ] alpha — algo\n      https://example.com/plan\n")
        self.assertEqual([], codes(graph))
        self.assertEqual((), graph.by_feature["alpha"].unknown_keys)

    def test_an_unrelated_labelled_sub_line_stays_prose(self) -> None:
        graph = graph_of("- [ ] alpha — algo\n      nota: revisar con el equipo\n")
        self.assertEqual([], codes(graph))

    def test_invalid_size_and_kind(self) -> None:
        graph = graph_of("- [ ] alpha — algo\n      size: XL · kind: nope\n")
        self.assertEqual(["SDD022", "SDD022"], codes(graph))

    def test_stage_without_an_outcome(self) -> None:
        graph = graph_of("## Stage 1\n\n- [ ] alpha — algo\n")
        self.assertIn("SDD023", codes(graph))

    def test_stage_with_an_outcome_is_accepted(self) -> None:
        graph = graph_of("## Stage 1 — el dominio persiste\n\n- [ ] alpha — algo\n")
        self.assertEqual([], codes(graph))

    def test_a_well_formed_roadmap_reports_nothing(self) -> None:
        self.assertEqual([], codes(graph_of(NEW_FORMAT)))

    def test_the_shipped_template_validates_clean(self) -> None:
        """The template is the first roadmap every project gets — it must pass."""
        template = (ROOT / "templates" / "roadmap-template.md").read_text(
            encoding="utf-8"
        )
        graph = graph_of(template)
        self.assertEqual(
            [], [f.code for f in graph.validate() if f.severity == "ERROR"]
        )


class RenderingTests(unittest.TestCase):
    def test_hard_dependencies_are_solid_and_ordering_ones_dashed(self) -> None:
        diagram = sdd_roadmap.mermaid(graph_of(NEW_FORMAT))
        self.assertIn("-.->|informs-from|", diagram)
        self.assertRegex(diagram, r"n\d+ --> n\d+")

    def test_a_deferred_entry_gets_a_distinct_shape(self) -> None:
        diagram = sdd_roadmap.mermaid(graph_of(NEW_FORMAT))
        self.assertRegex(diagram, r'n\d+\("· ingress \(M\)"\)')

    def test_stage_filter_narrows_the_diagram(self) -> None:
        diagram = sdd_roadmap.mermaid(graph_of(NEW_FORMAT), stage="Stage 1")
        self.assertIn("domain", diagram)
        self.assertNotIn("adapter", diagram)

    def test_long_summaries_are_shortened(self) -> None:
        graph = graph_of(f"- [ ] alpha — {'x' * 400}\n")
        rendered = sdd_roadmap.render_entry(graph, graph.by_feature["alpha"])
        self.assertLess(len(rendered), 200)
        self.assertTrue(rendered.endswith("…"))

    def test_report_names_the_absence_of_a_graph_instead_of_faking_one(self) -> None:
        report = sdd_roadmap.render_report(graph_of(LEGACY_FORMAT))
        self.assertIn("Sin dependencias declaradas", report)
        self.assertNotIn("```mermaid", report)

    def test_report_covers_the_derived_views(self) -> None:
        report = sdd_roadmap.render_report(graph_of(NEW_FORMAT))
        for heading in ("Frontera", "Olas", "Camino crítico", "Aplazadas", "Grafo"):
            self.assertIn(heading, report)


class CommandLineTests(unittest.TestCase):
    def test_exit_code_is_nonzero_only_for_errors(self) -> None:
        clean = build(NEW_FORMAT)
        self.assertEqual(0, sdd_roadmap.main(["--root", str(clean), "validate"]))
        warned = build("## Stage 1\n\n- [ ] alpha — algo\n")
        self.assertEqual(0, sdd_roadmap.main(["--root", str(warned), "validate"]))
        broken = build("- [ ] alpha — algo\n      needs: missing\n")
        self.assertEqual(1, sdd_roadmap.main(["--root", str(broken), "validate"]))

    def test_a_missing_roadmap_is_an_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                1, sdd_roadmap.main(["--root", directory, "report"])
            )


if __name__ == "__main__":
    unittest.main()
