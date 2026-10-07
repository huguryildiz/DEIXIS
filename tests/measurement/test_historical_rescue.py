"""Historical benchmark rescue is independent of product discovery."""
from scripts.benchmark.replay_ranking import historical_inspection_order

RESCUE_EMBEDDING_TOP = 50

# ---- the rescue arm --------------------------------------------------------------------------

def rescue(code_position, embedding_rank):
    """One record at a named place in the code order and in the embedding, inside a pool of 400."""
    ids = [f"r{i:03d}" for i in range(400)]
    target = ids[code_position - 1]
    # Every other record sits far down the embedding, so only the named one can meet the second condition.
    embedding = {rid: (float(position + RESCUE_EMBEDDING_TOP + 1), True) for position, rid in enumerate(ids)}
    embedding[target] = (float(embedding_rank), True)
    return historical_inspection_order(list(ids), list(ids), embedding), target


def test_a_record_is_rescued_only_when_it_is_outside_the_code_top_and_inside_the_embedding_top():
    (order, rescued), target = rescue(201, 50)
    assert rescued == [target] and order[0] == target


def test_a_record_inside_the_code_top_is_not_rescued_however_high_the_embedding_puts_it():
    (order, rescued), target = rescue(200, 1)
    assert rescued == [] and order[0] != target


def test_a_record_below_the_embedding_top_is_not_rescued_however_low_the_code_order_puts_it():
    (order, rescued), target = rescue(399, 51)
    assert rescued == []


def test_without_an_embedding_the_fused_order_stands_and_nobody_is_rescued():
    fused = ["a", "b", "c"]
    assert historical_inspection_order(fused, fused, None) == (["a", "b", "c"], [])


def test_a_record_without_a_stored_similarity_is_not_rescued_by_the_tail_rank_it_shares():
    """The embedding has no authority (SW8.2): a record the embedding never scored cannot enter through it."""
    ids = [f"r{i:03d}" for i in range(300)]
    embedding = {rid: (299.5, False) for rid in ids}
    embedding[ids[0]] = (1.0, True)
    order, rescued = historical_inspection_order(list(ids), list(ids), embedding)
    assert rescued == [] and order == ids


def test_several_rescued_records_come_in_embedding_order():
    ids = [f"r{i:03d}" for i in range(300)]
    embedding = {rid: (float(position + 1), True) for position, rid in enumerate(ids)}
    embedding["r250"], embedding["r260"] = (3.0, True), (2.0, True)
    order, rescued = historical_inspection_order(list(ids), list(ids), embedding)
    assert rescued == ["r260", "r250"] and order[:2] == ["r260", "r250"]
    assert order[2:] == [rid for rid in ids if rid not in ("r250", "r260")]


