import asyncio

from deixis.workflow.concurrency import ModelCallLimiter


def test_at_most_limit_calls_run_at_once():
    async def main():
        limiter = ModelCallLimiter(2)
        current = 0
        peak = 0

        async def work():
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.02)
            current -= 1
            return "done"

        results = await asyncio.gather(*(limiter.run(f"k{i}", work) for i in range(5)))
        assert results == ["done"] * 5
        assert peak == 2

    asyncio.run(main())


def test_reduce_halves_the_limit_with_a_floor_of_one():
    async def main():
        limiter = ModelCallLimiter(6)
        assert await limiter.reduce() == 3
        assert await limiter.reduce() == 1
        assert await limiter.reduce() == 1
        assert limiter.limit == 1

    asyncio.run(main())


def test_reduce_lowers_the_ceiling_for_calls_still_waiting():
    async def main():
        limiter = ModelCallLimiter(2)
        started = []

        async def slow(name):
            started.append(name)
            await asyncio.sleep(0.05)
            return name

        first = asyncio.ensure_future(limiter.run("a", lambda: slow("a")))
        second = asyncio.ensure_future(limiter.run("b", lambda: slow("b")))
        await asyncio.sleep(0.01)
        await limiter.reduce()
        third = asyncio.ensure_future(limiter.run("c", lambda: slow("c")))
        await asyncio.sleep(0.01)
        assert "c" not in started
        await asyncio.gather(first, second, third)
        assert started == ["a", "b", "c"]

    asyncio.run(main())


def test_same_key_in_flight_is_never_sent_twice():
    async def main():
        limiter = ModelCallLimiter(4)
        calls = 0

        async def work():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            return "value"

        results = await asyncio.gather(*(limiter.run("same-key", work) for _ in range(3)))
        assert results == ["value"] * 3 and calls == 1

    asyncio.run(main())
