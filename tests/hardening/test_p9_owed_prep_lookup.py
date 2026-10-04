"""Synthetic preparation records and MockTransport only; no provider/model calls."""
import hashlib
import json

import httpx
import pytest

from scripts.p9_owed import prep_lookup as prep


@pytest.fixture(autouse=True)
def refuse_real_network(monkeypatch):
    async def refused(*args, **kwargs):
        raise AssertionError("tests must use httpx.MockTransport")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refused)


def work(wid="W1"):
    return {"id": f"https://openalex.org/{wid}", "doi": "https://doi.org/10.1234/synthetic",
            "ids": {"openalex": f"https://openalex.org/{wid}", "doi": "https://doi.org/10.1234/synthetic",
                    "pmid": "https://pubmed.ncbi.nlm.nih.gov/123", "arxiv": "2001.01234v2"},
            "display_name": "SYNTHETIC Control for Robots", "publication_year": 2020,
            "authorships": [{"author": {"display_name": "Ada Smith"}}],
            "primary_location": {"version": "publishedVersion"},
            "abstract_inverted_index": {"SYNTHETIC": [0], "control": [1], "text.": [2]}}


def crossref_item():
    return {"DOI": "10.1234/synthetic", "title": ["SYNTHETIC Control for Robots"],
            "author": [{"given": "Ada", "family": "Smith"}], "issued": {"date-parts": [[2020]]},
            "abstract": "<jats:p>Abstract: SYNTHETIC &amp; control.</jats:p>"}


def args(tmp_path, command="search", item="k6", cap=60, global_cap=60):
    values = [command, "--item", item, "--cap", str(cap), "--global-cap", str(global_cap),
              "--ledger", str(tmp_path / "ledger.jsonl"), "--out", str(tmp_path / f"{command}.json")]
    return values + {"search": ["--query", "SYNTHETIC control", "--per-page", "2"],
                     "ids": ["--ids", "W1,W2"], "crossref": ["--doi", "10.1234/synthetic"]}[command]


def ledger(tmp_path):
    return [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("command", ["search", "ids", "crossref"])
def test_success_uses_repo_provider_and_keyless_client(tmp_path, command, monkeypatch):
    monkeypatch.setenv("OPENALEX_API_KEY", "SECRET_MUST_NOT_BE_SENT")
    monkeypatch.setenv("CROSSREF_MAILTO", "private@example.invalid")
    seen = []
    def handler(request):
        seen.append(request)
        assert request.headers["user-agent"] == prep.USER_AGENT
        assert "authorization" not in request.headers
        assert "mailto" not in request.url.params and "api_key" not in request.url.params
        if command == "crossref":
            assert request.url.path.endswith("/10.1234/synthetic")
            return httpx.Response(200, json={"message": crossref_item()})
        if command == "search":
            assert request.url.params["search.title_and_abstract"] == "SYNTHETIC control"
            assert request.url.params["per_page"] == "2"
        else:
            assert request.url.params["filter"] == "openalex:W1|W2"
            assert request.url.params["per_page"] == "2"
        return httpx.Response(200, json={"results": [work()], "meta": {"count": 1}})
    assert prep.main(args(tmp_path, command), transport=httpx.MockTransport(handler)) == 0
    assert len(seen) == 1
    result = json.loads((tmp_path / f"{command}.json").read_text())
    record = result["records"][0]
    assert record["title"] == "SYNTHETIC Control for Robots"
    assert record["doi"] == "10.1234/synthetic"
    assert record["first_author"] == "Ada Smith"
    assert record["first_author_surname"] == "Smith" and record["year"] == 2020
    assert record["abstract_sha256"] == hashlib.sha256(record["abstract"].encode()).hexdigest()
    if command == "crossref":
        assert record["abstract"] == "SYNTHETIC & control."
        assert record["abstract_origin"] == "provider_crossref_jats"
        assert record["surname_basis"] == "provider_family"
    else:
        assert record["abstract"] == "SYNTHETIC control text."
        assert record["abstract_origin"] == "provider_openalex_inverted_index"
        assert record["identifiers"] == work()["ids"]
        assert record["openalex_id"] == "W1"
        assert record["surname_basis"] == "display_name_last_token"
    admission, row = ledger(tmp_path)
    assert admission["event"] == admission["outcome"] == "admitted" and admission["counted_attempts"] == 1
    assert row["request_id"] == admission["request_id"]
    assert row["counted_attempts"] == 0 and row["sent_attempts"] == 1
    assert row["http_status"] == 200 and row["outcome"] == "completed"
    assert row["utc_time"].endswith("+00:00")
    assert "SECRET" not in json.dumps(result) + json.dumps(row)


@pytest.mark.parametrize("command", ["search", "ids", "crossref"])
@pytest.mark.parametrize("failure,expected,status", [
    (429, "rate_limited", 429), (503, "failed", 503),
    ("timeout", "timeout", None), ("connect", "failed", None), (302, "failed", 302),
])
def test_failure_is_one_request_and_counted_without_retry(tmp_path, command, failure, expected, status, monkeypatch, capsys):
    seen = []
    async def no_sleep(*args):
        pytest.fail("provider retry slept")
    monkeypatch.setattr(prep.asyncio, "sleep", no_sleep)
    def handler(request):
        seen.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("SECRET_ERROR", request=request)
        if failure == "connect":
            raise httpx.ConnectTimeout("SECRET_ERROR", request=request)
        return httpx.Response(failure, text="SECRET_ERROR", headers={"Retry-After": "0", "Location": "https://example.invalid"})
    assert prep.main(args(tmp_path, command), transport=httpx.MockTransport(handler)) == 1
    assert len(seen) == 1
    admission, row = ledger(tmp_path)
    assert admission["counted_attempts"] == 1 and row["counted_attempts"] == 0
    assert row["sent_attempts"] == 1 and row["http_status"] == status and row["outcome"] == expected
    assert "SECRET_ERROR" not in (tmp_path / "ledger.jsonl").read_text()
    assert "SECRET_ERROR" not in capsys.readouterr().err


def test_caps_share_ledger_and_refusal_does_not_change_it(tmp_path, capsys):
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(429, headers={"Retry-After": "0"})
    transport = httpx.MockTransport(handler)
    assert prep.main(args(tmp_path, item="k6", cap=1, global_cap=2), transport=transport) == 1
    first_bytes = (tmp_path / "ledger.jsonl").read_bytes()
    assert prep.main(args(tmp_path, item="k6", cap=1, global_cap=2), transport=transport) == 1
    assert len(seen) == 1 and (tmp_path / "ledger.jsonl").read_bytes() == first_bytes
    assert prep.main(args(tmp_path, "crossref", item="l9", cap=1, global_cap=2), transport=transport) == 1
    final_bytes = (tmp_path / "ledger.jsonl").read_bytes()
    assert final_bytes.startswith(first_bytes)
    assert prep.main(args(tmp_path, item="k6", global_cap=2), transport=transport) == 1
    assert len(seen) == 2 and (tmp_path / "ledger.jsonl").read_bytes() == final_bytes
    capsys.readouterr()
    assert prep.main(["ledger-summary", "--ledger", str(tmp_path / "ledger.jsonl")]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "total_requests": 2, "admitted_requests": 2, "completed_requests": 2, "by_item": {"k6": 1, "l9": 1}}


def test_default_global_cap_of_sixty_refuses_before_send(tmp_path):
    path = tmp_path / "ledger.jsonl"
    contents = (json.dumps({"item": "l9", "counted_attempts": 1}) + "\n") * 60
    path.write_text(contents)
    argv = args(tmp_path)
    offset = argv.index("--global-cap")
    del argv[offset:offset + 2]
    assert prep.main(argv, transport=httpx.MockTransport(lambda r: pytest.fail("over cap sent"))) == 1
    assert path.read_text() == contents


def test_malformed_ledger_refuses_without_send_or_rewrite(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"item": "k6"}\n')
    assert prep.main(args(tmp_path), transport=httpx.MockTransport(lambda r: pytest.fail("invalid ledger sent"))) == 1
    assert path.read_text() == '{"item": "k6"}\n'


@pytest.mark.parametrize("command", ["search", "ids", "crossref"])
def test_empty_abstract_hash_is_unknown(tmp_path, command):
    item = crossref_item() if command == "crossref" else work()
    item.pop("abstract" if command == "crossref" else "abstract_inverted_index")
    payload = {"message": item} if command == "crossref" else {"results": [item]}
    assert prep.main(args(tmp_path, command), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) == 0
    record = json.loads((tmp_path / f"{command}.json").read_text())["records"][0]
    assert record["abstract"] is None and record["abstract_sha256"] is None and record["abstract_origin"] is None


def test_crossref_404_counts_one_zero_result(tmp_path):
    assert prep.main(args(tmp_path, "crossref", item="l9"), transport=httpx.MockTransport(lambda r: httpx.Response(404))) == 0
    assert ledger(tmp_path)[1]["outcome"] == "zero_results"


def test_supplied_text_cli_preserves_provider_hash_and_exact_2500_char_cut(tmp_path):
    abstract = "  SYNTHETIC α\n" + "é" * 2600 + "TAIL"
    record = {"title": "TITLE MUST NOT PREFIX PASSAGE", "abstract": abstract,
              "abstract_sha256": hashlib.sha256(abstract.encode()).hexdigest()}
    source, out = tmp_path / "record.json", tmp_path / "supplied.json"
    source.write_text(json.dumps({"records": [record]}))
    assert prep.main(["supplied-text", "--record", str(source), "--out", str(out)]) == 0
    enriched = json.loads(out.read_text())["records"][0]
    assert enriched["abstract"] == abstract
    assert enriched["provider_abstract_sha256"] == record["abstract_sha256"]
    assert enriched["supplied_text"] == abstract[:2500]
    assert enriched["supplied_text_sha256"] == hashlib.sha256(abstract[:2500].encode()).hexdigest()
    assert enriched["supplied_text_chars"] == 2500 and enriched["reading_depth"] == "abstract"
    assert not (tmp_path / "ledger.jsonl").exists()


@pytest.mark.parametrize("abstract", [None, "", " \n "])
def test_no_readable_abstract_means_no_assessment_text(abstract):
    result = prep.supplied_text({"title": "SYNTHETIC", "abstract": abstract})
    assert result["supplied_text"] is None and result["supplied_text_sha256"] is None
    assert result["reading_depth"] == "metadata_only"


def test_changed_provider_abstract_refuses_supplied_hash():
    with pytest.raises(prep.PrepError, match="provider_abstract_hash_mismatch"):
        prep.supplied_text({"abstract": "changed", "abstract_sha256": "old"})


@pytest.mark.parametrize("title,authors,year,status", [
    ("SYNTHÉTIC Control: for robots", ["Ada Smith"], 2020, "matched"),
    ("SYNTHETIC Control", ["Ada Smith"], 2021, "matched"),
    ("SYNTHETIC Control", ["Ada Jones", "Ben Smith"], 2020, "identity_unverified"),
    ("SYNTHETIC Control", ["Ada Smith"], 2019, "identity_unverified"),
    ("Other SYNTHETIC Control", ["Ada Smith"], 2020, "identity_unverified"),
    ("SYNTHETIC Control", [], 2020, "identity_unverified"),
])
def test_identity_cli_uses_title_head_first_author_and_allowed_years(tmp_path, title, authors, year, status, capsys):
    source = tmp_path / "identity.json"
    source.write_text(json.dumps({"title": title, "authors": authors, "year": year}))
    assert prep.main(["match-identity", "--record", str(source), "--match", "synthetic control",
                      "--first-author", "Smith", "--years", "2020,2021"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == status
    assert result["rule_source"].endswith(":title_tokens,g_nodes")


def test_empty_identity_rule_refuses():
    with pytest.raises(prep.PrepError, match="identity_rule_must_not_be_empty"):
        prep.match_identity({"title": "SYNTHETIC", "authors": ["Ada Smith"], "year": 2020}, "!!!", "Smith", [2020])


def test_admission_is_fsynced_before_transport(tmp_path, monkeypatch):
    real_fsync = prep.os.fsync
    synced = []

    def fsync(fd):
        real_fsync(fd)
        synced.append(True)

    monkeypatch.setattr(prep.os, "fsync", fsync)

    def handler(request):
        assert synced == [True]
        assert len(ledger(tmp_path)) == 1
        assert ledger(tmp_path)[0]["event"] == "admitted"
        return httpx.Response(200, json={"results": []})

    assert prep.main(args(tmp_path), transport=httpx.MockTransport(handler)) == 0
    assert len(synced) == 2


@pytest.mark.parametrize("global_limit", [False, True])
def test_process_dies_after_admission_still_consumes_cap(tmp_path, capsys, global_limit):
    class ProcessDied(BaseException):
        pass

    def dies(request):
        assert ledger(tmp_path)[0]["event"] == "admitted"
        raise ProcessDied()

    with pytest.raises(ProcessDied):
        prep.main(args(tmp_path), transport=httpx.MockTransport(dies))
    before = (tmp_path / "ledger.jsonl").read_bytes()
    assert len(ledger(tmp_path)) == 1
    refused_args = args(tmp_path, item="l9", global_cap=1) if global_limit else args(tmp_path, cap=1)
    assert prep.main(refused_args, transport=httpx.MockTransport(lambda _: pytest.fail("cap exceeded"))) == 1
    assert (tmp_path / "ledger.jsonl").read_bytes() == before
    capsys.readouterr()
    assert prep.main(["ledger-summary", "--ledger", str(tmp_path / "ledger.jsonl")]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "total_requests": 1, "admitted_requests": 1, "completed_requests": 0, "by_item": {"k6": 1, "l9": 0}}


def test_transport_exception_records_outcome_without_releasing_admission(tmp_path):
    def dies(request):
        raise RuntimeError("SECRET_EXCEPTION")

    assert prep.main(args(tmp_path), transport=httpx.MockTransport(dies)) == 1
    admission, outcome = ledger(tmp_path)
    assert admission["event"] == "admitted" and outcome["outcome"] == "error_RuntimeError"
    assert outcome["request_id"] == admission["request_id"]
    assert "SECRET_EXCEPTION" not in (tmp_path / "ledger.jsonl").read_text()
    assert prep.main(args(tmp_path, cap=1), transport=httpx.MockTransport(lambda _: pytest.fail("cap exceeded"))) == 1


@pytest.mark.parametrize("failure", ["open", "fsync"])
def test_admission_append_failure_sends_nothing(tmp_path, monkeypatch, failure):
    if failure == "open":
        (tmp_path / "ledger.jsonl").mkdir()
    else:
        def fails(fd):
            raise OSError("SYNTHETIC fsync failure")
        monkeypatch.setattr(prep.os, "fsync", fails)
    assert prep.main(args(tmp_path), transport=httpx.MockTransport(lambda _: pytest.fail("unpersisted admission sent"))) == 1


def test_outcome_append_failure_keeps_admission_used(tmp_path, monkeypatch):
    real_append = prep.append_ledger

    def append(path, entry):
        if entry["event"] == "outcome":
            raise prep.PrepError("ledger_append_failed")
        real_append(path, entry)

    monkeypatch.setattr(prep, "append_ledger", append)
    assert prep.main(args(tmp_path), transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))) == 1
    assert len(ledger(tmp_path)) == 1
    assert prep.main(args(tmp_path, cap=1), transport=httpx.MockTransport(lambda _: pytest.fail("cap exceeded"))) == 1


@pytest.mark.parametrize("defect", ["orphan", "duplicate", "wrong_item"])
def test_invalid_outcome_ledger_refuses_before_send(tmp_path, defect):
    admitted = {"event": "admitted", "outcome": "admitted", "item": "k6",
                "request_id": "synthetic-request", "counted_attempts": 1}
    outcome = dict(admitted, event="outcome", outcome="completed", counted_attempts=0)
    rows = [admitted, outcome]
    if defect == "orphan":
        rows = [outcome]
    elif defect == "duplicate":
        rows.append(outcome)
    else:
        outcome["item"] = "l9"
    contents = "".join(json.dumps(row) + "\n" for row in rows)
    path = tmp_path / "ledger.jsonl"
    path.write_text(contents)
    assert prep.main(args(tmp_path), transport=httpx.MockTransport(lambda _: pytest.fail("invalid ledger sent"))) == 1
    assert path.read_text() == contents
