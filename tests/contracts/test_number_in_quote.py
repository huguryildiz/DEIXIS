"""D54: a table value whose number none of its quotes state is flagged for a person to check. SYNTHETIC values."""

from decimal import Decimal as D

from deixis.documents import ocr, pdf
from deixis.domain.numbers import numbers_in, unquoted_numbers
from deixis.storage.db import new_id
from deixis.workflow.tables import TableStore


def test_numbers_in_reads_decimals_thousands_and_dotted_identifiers():
    assert numbers_in("a 2.5 dB gain over 1,000 nodes, 0,5 s, IEEE 802.11") == {D("2.5"), D("1000"), D("0.5"), D("802.11")}
    assert numbers_in("version 1.2.3") == {D(1), D(2), D(3)}
    assert numbers_in("no numbers here") == set()
    assert numbers_in("-3 dB, .5 s, 1e-6 W, .5e-6 m, a range 2-5") == {D(3), D("0.5"), D("0.000001"), D("5e-7"), D(2), D(5)}


def test_a_number_the_quotes_do_not_state_is_named():
    quote = ["The protocol improves throughput by 2 dB over VBF."]
    assert unquoted_numbers({"number": 3, "unit": "dB"}, quote) == [D(3)]
    assert unquoted_numbers({"number": 2.0, "unit": "dB"}, quote) == []
    assert unquoted_numbers({"number": 2, "unit": "dB", "as_stated": "3 dB"}, quote) == [D(3)]
    assert unquoted_numbers({"text": "2 dB over VBF in 30 runs"}, quote) == [D(30)]
    assert unquoted_numbers({"text": "Throughput improves over VBF"}, quote) == []
    assert unquoted_numbers({"option_ids": ["opt_2"]}, quote) == []
    assert unquoted_numbers({"number": -3, "unit": "dB"}, ["a loss of -3 dB"]) == []
    assert unquoted_numbers({"number": 1e-12}, ["0"]) == [D("1e-12")]
    assert unquoted_numbers({"number": 1000000000001}, ["1000000000000 packets"]) == [D(1000000000001)]
    assert unquoted_numbers({"number": 0.1}, ["a ratio of 0.10"]) == []
    assert unquoted_numbers({"number": 5e-7}, ["a gap of .5e-6 m"]) == []
    assert unquoted_numbers({"number": 3}, ["up to 1e999 states"]) == [D(3)]
    assert unquoted_numbers({"number": 5}, [None]) == [D(5)]
    assert unquoted_numbers({"number": 123456789012345678901234567891}, ["123456789012345678901234567900"]) \
        == [D(123456789012345678901234567891)]
    assert unquoted_numbers({"number": 0.001}, ["a step of 1,000e-6 s"]) == []
    assert unquoted_numbers({"number": 6}, ["a rate of 1e\u22126"]) == [D(6)]
    assert unquoted_numbers({"number": 0.000001}, ["a rate of 1e\u22126"]) == []  # an invalid proposal's quote without located text


def test_the_table_flags_a_model_value_whose_number_is_in_no_quote(tmp_path):
    from test_evidence_tables import PACKET_SIZE, VALUE
    from test_ocr import library_with_scan

    store, rid, svid, aid, base = library_with_scan(tmp_path)
    read = ocr.merge(base, [ocr.OcrPage(2, "succeeded", "SYNTHETIC OCR text: packets of 128 bytes.")], ["eng"])
    store.reextract_asset(aid, read, read.extraction_version, pdf.chunk_page)
    passages = {p["physical_page"]: p["id"] for p in store.passages_for(svid)}
    run = store.create_run(rid, "answer", {"max_model_calls": 4}, None)
    step = store.step(run["id"], "cell", "model:cell_extraction")
    sti = new_id("sti")
    store.insert_step_input(step["id"], rid, run["id"], 0, {"step_input_id": sti, "task_type": "cell_extraction", "scope_revision": 1,
                            "skill_package_hash": "sha256:0"}, "base", "developer", "message", {})
    tables = TableStore(store)

    def flagged(page, anchor):
        tid = tables.create_table(rid, f"Packets {page}", [svid], None, None)
        cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
        tables.save_model_output(rid, tid, cid, svid, column_revision=1, state="value", value=VALUE, note=None, reading_depth="selected_sections",
                                 output_status="structurally_valid", run_id=run["id"], step_id=step["id"], step_input_id=sti,
                                 links=[{"passage_id": passages[page], "source_version_id": svid, "anchor_text": anchor, "anchor_match": "exact"}],
                                 model_connection="fake", resolved_model="fake-model", scope_revision=1, cell_version_at_request=None, recheck=False)
        return "number_not_in_quote" in tables.cell_view(rid, tid, cid, svid)["flags"]

    assert flagged(2, "packets of 128 bytes") is False
    assert flagged(1, "SYNTHETIC text layer page") is True
