from deixis.models.adapter import ModelStepResult, is_rate_limited


def test_a_completed_result_is_never_rate_limited():
    assert not is_rate_limited(ModelStepResult("completed", raw_text="{}"))


def test_an_http_429_error_is_rate_limited():
    assert is_rate_limited(ModelStepResult("failed", error="HTTP 429: Too Many Requests"))


def test_free_text_rate_limit_and_quota_wording_is_recognized():
    assert is_rate_limited(ModelStepResult("failed", error="rate_limit_error: please slow down"))
    assert is_rate_limited(ModelStepResult("failed", error="Resource has been exhausted (e.g. check quota)."))


def test_an_unrelated_failure_is_not_rate_limited():
    assert not is_rate_limited(ModelStepResult("failed", error="ConnectError: timeout", delivery_class="after_send_unknown"))
    assert not is_rate_limited(ModelStepResult("unavailable", error="GEMINI_API_KEY is not set"))
