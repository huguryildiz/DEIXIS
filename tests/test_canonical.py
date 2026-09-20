"""Canonical form and hashing: the same content gives the same digest whatever order it arrives in (SW14.4)."""

import math

import pytest

from deixis.domain.canonical import canonical_json, canonical_rows, sha256_hex, unordered_pair


def test_key_order_does_not_change_the_digest():
    assert sha256_hex({"a": 1, "b": 2}) == sha256_hex({"b": 2, "a": 1})


def test_rows_sorted_by_their_identifier_give_one_digest():
    rows = [{"id": "b", "score": 2}, {"id": "a", "score": 1}]
    assert sha256_hex(canonical_rows(rows, "id")) == sha256_hex(canonical_rows(list(reversed(rows)), "id"))
    assert [r["id"] for r in canonical_rows(rows, "id")] == ["a", "b"]


def test_a_row_without_the_key_is_an_error():
    with pytest.raises(KeyError):
        canonical_rows([{"id": "a"}, {"score": 1}], "id")


def test_a_set_hashes_as_its_sorted_list():
    assert sha256_hex({"b", "a"}) == sha256_hex(["a", "b"])
    assert canonical_json(frozenset({"b", "a"})) == '["a","b"]'


def test_a_tuple_hashes_as_a_list():
    assert canonical_json(("a", "b")) == '["a","b"]'


def test_the_same_text_written_two_ways_hashes_once():
    assert sha256_hex("ü") == sha256_hex("ü")  # NFC and NFD "ü"
    assert sha256_hex({"ü": 1}) == sha256_hex({"ü": 1})


def test_separators_carry_no_space_and_non_ascii_is_not_escaped():
    assert canonical_json({"q": "dolanıklık", "n": [1, 2]}) == '{"n":[1,2],"q":"dolanıklık"}'


def test_a_number_that_is_not_a_number_is_refused():
    with pytest.raises(ValueError):
        canonical_json(float("nan"))
    with pytest.raises(ValueError):
        canonical_json({"x": math.inf})


def test_a_pair_hashes_the_same_either_way_round():
    assert unordered_pair("b", "a") == ("a", "b")
    assert unordered_pair("a", "b") == ("a", "b")
