from deixis.workflow.lineage.edges import (
    EDGE_STATES, Edge, EdgeFrom, EdgeTo, derive_edges, edge_counts, edge_state,
    unexpected_no_citation_edge, unassessed_edges,
)


def test_edge_four_states():
    frm = EdgeFrom("a", "wa", frozenset({"W1", "W2"}))
    assert edge_state(EdgeTo("b", "wb", False, frozenset({"W1"})), frm) == "not_read"
    assert edge_state(EdgeTo("b", "wb", True, frozenset({"W2"})), frm) == "present"
    assert edge_state(EdgeTo("b", "wb", True, frozenset()), frm) == "absent_in_read_list"
    assert edge_state(EdgeTo("b", "wb", True, frozenset()), EdgeFrom("a", "wa", frozenset())) == "unresolved"
    assert edge_state(EdgeTo("b", "wb", False, frozenset()), EdgeFrom("a", "wa", frozenset())) == "not_read"


def test_openalex_id_normalization_in_edges():
    assert edge_state(EdgeTo("b", "wb", True, frozenset({" https://openalex.org/w123 "})),
                      EdgeFrom("a", "wa", frozenset({"W123"}))) == "present"
    assert edge_state(EdgeTo("b", "wb", True, frozenset({"w123"})),
                      EdgeFrom("a", "wa", frozenset({" https://openalex.org/W123 "}))) == "present"
    assert edge_state(EdgeTo("b", "wb", True, frozenset()),
                      EdgeFrom("a", "wa", frozenset({" "}))) == "unresolved"


def test_unexpected_no_citation_edge_only_for_absent_in_read_list():
    assert {state: unexpected_no_citation_edge(state) for state in EDGE_STATES} == {
        "present": False, "absent_in_read_list": True, "unresolved": False, "not_read": False}
    assert not unexpected_no_citation_edge("unknown")


def test_derive_edges_skips_same_version_and_same_work_in_input_order():
    tos = (EdgeTo("b", "wb", False, frozenset()), EdgeTo("a", "wa", True, frozenset({"W2"})))
    froms = (EdgeFrom("a2", "wa", frozenset({"W1"})), EdgeFrom("b", "wb", frozenset({"W2"})),
             EdgeFrom("a", "wa", frozenset({"W1"})))
    assert derive_edges(tos, iter(froms)) == (Edge("b", "a2", "not_read"), Edge("b", "a", "not_read"),
                                            Edge("a", "b", "present"))
    assert derive_edges((EdgeTo("same", "wa", True, frozenset()),),
                        (EdgeFrom("same", "different", frozenset()),)) == ()


def test_edge_counts_always_carry_all_four_keys():
    assert edge_counts(()) == dict.fromkeys(EDGE_STATES, 0)
    assert edge_counts((Edge("b", "a", "present"), Edge("c", "a", "present"))) == {
        "present": 2, "absent_in_read_list": 0, "unresolved": 0, "not_read": 0}


def test_present_edge_without_mention_is_unassessed_and_never_a_candidate():
    edge = Edge("b", "a", "present")
    assert unassessed_edges((edge, Edge("c", "a", "not_read")), frozenset(), frozenset({"b", "c"})) == (edge,)
    assert not hasattr(edge, "mention_passage_ids")


def test_unassessed_edges_skip_candidate_and_excluded_pairs():
    edges = (Edge("b", "a", "present"), Edge("c", "a", "present"), Edge("d", "a", "present"))
    assert unassessed_edges(edges, frozenset({("a", "b")}), frozenset({"b", "c", "d"}),
                            frozenset({("a", "c")})) == (edges[2],)


def test_unscanned_target_edge_is_not_unassessed_but_scanned_without_mention_is():
    edges = (Edge("unscanned", "a", "present"), Edge("scanned", "a", "present"))
    assert unassessed_edges(edges, frozenset(), frozenset({"scanned"})) == (edges[1],)
    assert unassessed_edges(edges, frozenset(), frozenset()) == ()


def test_edge_alone_creates_no_candidate():
    from deixis.workflow.lineage.candidates import LineageWork, find_candidates
    from deixis.workflow.lineage.mentions import PassageText

    a = LineageWork("a", "wa", 0, "Short title", ("Smith",), 2015, (), False,
                    frozenset(), frozenset({"W1"}), ())
    f = LineageWork("f", "wf", 1, "Numbered citation", ("Jones",), 2020, (), True,
                    frozenset({"W1"}), frozenset({"W2"}), (PassageText("pf", "pdf_page", "See [1]", 1),))
    assert edge_state(EdgeTo("f", "wf", True, f.referenced_ids), EdgeFrom("a", "wa", a.openalex_ids)) == "present"
    assert find_candidates((a, f)).candidates == ()
