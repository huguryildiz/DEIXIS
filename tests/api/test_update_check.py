"""P10 M3: the version check asks GitHub's release list once a day, sends nothing that names the person, offers only a
newer release (a pre-release only to a pre-release build), builds its own link, shows nothing on a failure, and sends
nothing when it is off. The release lists are SYNTHETIC; no request leaves the test."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from deixis.runtime import update_check
from deixis.storage import db
from deixis.workflow.run.store import Store


def release(tag, draft=False, prerelease=True, url="https://example.invalid/elsewhere"):
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease, "html_url": url}


def test_only_a_newer_offered_release_counts():
    listed = [release("v0.1.1"), release("v0.1.3", draft=True), release("v0.1.2"), release("v0.2.0-rc.1"),
              release("nightly"), {"tag_name": 5}, "SYNTHETIC"]
    assert update_check.newest(listed, "0.1.1") == "0.1.2"  # the draft, the rc, junk and the same version are skipped
    assert update_check.newest(listed, "0.1.2") is None
    assert update_check.newest(listed, "0.2.0-rc.0") == "0.2.0-rc.1"  # an rc build is offered the next rc
    # Python's metadata writes an rc build as 0.10.0rc1: it is offered the next rc and the release, not the same rc.
    assert update_check.newest([release("v0.10.0-rc.1"), release("v0.10.0-rc.2")], "0.10.0rc1") == "0.10.0-rc.2"
    assert update_check.newest([release("v0.10.0-rc.1"), release("v0.10.0")], "0.10.0rc1") == "0.10.0"
    assert update_check.newest([release("v0.10.0")], "0.9.9") == "0.10.0"  # by number, not by text
    assert update_check.newest([release("v0.10.0-rc.2")], "0.10.0") is None
    assert update_check.newest([release("v01.2.3"), release("v1.2.3-rc.01")], "0.1.1") is None  # not semantic versions
    assert update_check.newest(listed, "unknown") is None


def library(tmp_path):
    conn = db.connect(tmp_path / "library.sqlite")
    db.migrate(conn)
    return Store(conn)


def checker(store, handler, now):
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    make = lambda: httpx.AsyncClient(headers=update_check.HEADERS, follow_redirects=False,
                                     transport=httpx.MockTransport(respond))
    return update_check.UpdateCheck(store, "0.1.1", make, lambda: now[0]), seen


def test_a_daily_check_sends_no_identity_keeps_its_answer_and_builds_the_link(tmp_path):
    store = library(tmp_path)
    store.set_setting(update_check.SETTING, "on")
    now = [datetime(2026, 11, 7, 9, tzinfo=timezone.utc)]
    check, seen = checker(store, lambda r: httpx.Response(200, json=[release("v0.1.2")]), now)
    asyncio.run(check.check_if_due())
    asyncio.run(check.check_if_due())  # within the day: no second request, also after a restart (stored time)
    assert len(seen) == 1
    sent = seen[0]
    assert str(sent.url) == update_check.RELEASES_URL and sent.method == "GET"
    assert sent.headers["user-agent"] == "DEIXIS" and "authorization" not in sent.headers and "cookie" not in sent.headers
    shown = update_check.view(store, "0.1.1")
    assert shown["latest"] == {"version": "0.1.2", "url": "https://github.com/huguryildiz/DEIXIS/releases/tag/v0.1.2"}
    assert update_check.view(store, "0.1.2")["latest"] is None  # once updated, the stored answer is no longer shown
    now[0] += timedelta(hours=25)
    asyncio.run(check.check_if_due())
    assert len(seen) == 2


def test_shutdown_cancels_a_stalled_request_at_once(tmp_path):
    store = library(tmp_path)
    store.set_setting(update_check.SETTING, "on")

    async def scenario():
        stalled = asyncio.Event()

        async def hang(request):
            stalled.set()
            await asyncio.sleep(60)

        make = lambda: httpx.AsyncClient(transport=httpx.MockTransport(hang))
        check = update_check.UpdateCheck(store, "0.1.1", make)
        stop = asyncio.Event()
        loop = asyncio.create_task(check.run_forever(stop))
        check.soon()
        await asyncio.wait_for(stalled.wait(), 5)
        started = asyncio.get_running_loop().time()
        stop.set()
        await check.close(loop)
        check.soon()  # after close nothing starts
        assert asyncio.get_running_loop().time() - started < 1 and check._task.done() and loop.done()

    asyncio.run(scenario())


def test_a_failure_shows_nothing_waits_a_day_too_and_off_sends_nothing(tmp_path):
    store = library(tmp_path)
    now = [datetime(2026, 11, 7, 9, tzinfo=timezone.utc)]
    answers = iter([httpx.Response(403, json={"message": "rate limited"}), httpx.Response(200, content=b"{not json"),
                    httpx.Response(200, json={"message": "SYNTHETIC object, not a list"}),
                    httpx.Response(200, content=b"[" + b" " * (update_check.MAX_BYTES + 10) + b"]"),
                    httpx.Response(302, headers={"location": "https://example.invalid/"})])
    store.set_setting(update_check.SETTING, "on")
    for sent in range(1, 6):
        check, seen = checker(store, lambda r: next(answers), now)  # a new checker each time: a restart
        asyncio.run(check.check_if_due())
        asyncio.run(check.check_if_due())  # a failed attempt still waits a day, across a restart too
        assert len(seen) == 1
        assert update_check.view(store, "0.1.1") | {"enabled": None} == {"enabled": None, "current": "0.1.1", "checked_at": None, "latest": None}
        now[0] += timedelta(hours=24)

    def network_down(request):
        raise httpx.ConnectError("SYNTHETIC offline")

    check, seen = checker(store, network_down, now)
    asyncio.run(check.check_if_due())
    assert len(seen) == 1 and update_check.view(store, "0.1.1")["checked_at"] is None
    now[0] += timedelta(hours=24)
    store.set_setting(update_check.SETTING, "off")
    check, seen = checker(store, lambda r: httpx.Response(200, json=[]), now)
    asyncio.run(check.check_if_due())
    assert seen == [] and update_check.view(store, "0.1.1")["enabled"] is False
    store.conn.execute("DELETE FROM app_settings WHERE key = ?", (update_check.SETTING,))
    assert update_check.enabled(store) is False  # a run from the repository: off unless turned on
