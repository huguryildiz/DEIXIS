"""A reviewer model that writes citation handles into its reasons or notes: the reader sees source titles instead.
SYNTHETIC upload and scripted reviewer; this checks the displayed text, not review quality."""

import json
import re

from fastapi.testclient import TestClient

from fakes import FakeAdapter, envelope, valid_response
from test_api_flow import app_for, attached_research, run_to_end, session

HANDLE = re.compile(r"\b(?:psg_P|srv_S)\d+\b")


def reviewer(si):
    if si["task_type"] != "answer_review":
        return valid_response(si)
    passage, source = si["passages"][0]["passage_id"], si["sources"][0]["source_id"]
    padded = passage.replace("_P", "_P0")
    return json.dumps(envelope(si, "deixis.answer_review.v1") | {
        "reviews": [{"claim_label": c["claim_label"], "verdict": "supported", "reason": f"SYNTHETIC: {padded} states it."}
                    for c in si["claims_under_review"]],
        "notes": f"SYNTHETIC: only {source} was read.",
    })


def test_review_reasons_and_notes_show_titles_not_handles(tmp_path):
    adapter = FakeAdapter(responder=reviewer, models=["fake-model"])
    with TestClient(app_for(tmp_path, adapter)) as client:
        session(client)
        client.put("/api/settings/reviewer", json={"model_connection": "fake", "model": "fake-model"})
        view = run_to_end(client, attached_research(client), "answer")
        answer = view["answers"][0]
        assert answer["review"]["status"] == "completed"
        texts = [r["reason"] for r in answer["review"]["reviews"]] + [answer["review"]["notes"]]
        texts += [c["review"]["reason"] for c in answer["claims"] if c["review"]]
        assert texts and not any(HANDLE.search(text) for text in texts), texts
        assert all("“" in text for text in texts)
