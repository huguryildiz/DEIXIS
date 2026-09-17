# P6 dilim 0 — Tablo doldurmayı eş zamanlı yapmak: uygulama planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ResearchFlow._table_fill` (backend/deixis/workflow/flow.py) bugün kanıt tablosunun kaynaklarını tek tek dolaşıp her `cell_extraction` model çağrısını bekliyor; D55'te 50 kaynaklı bir doldurma 506–576 saniye sürdü. Bu dilim kaynak çağrılarını, süreç genelinde tek ve çalışma zamanında ayarlanabilir bir üst sınır altında (başlangıç 6) eş zamanlı gönderir; sınır bir kota/hız-sınırı hatasında düşer (taban 1) ve o adım en fazla iki kez yeniden gönderilir; her kaynak adımı bugünkü gibi kendi `operation_key`'ini, kaydını ve doğrulamasını korur; duraklatma, iptal ve yeni bir kapsam revizyonu uçuştaki çağrıları düşürmeden (bitirilerek) doğru şekilde ele alınır; sınır 1 iken aynı kod yolu bugünküyle bayt bayt aynı çıktıyı üretir. Raporla (dilim 1) paylaşılacak sınırlayıcı, `backend/deixis/workflow/` altında bağımsız bir modülde yaşar; bu dilim raporla ilgili hiçbir şey inşa etmez.

**Architecture:** Yeni, küçük bir eş zamanlılık sınırlayıcısı (`workflow/concurrency.py::ModelCallLimiter`) hem "aynı anda en fazla N çağrı" kuralını hem de "bir `operation_key` aynı anda tek uçuş" kuralını taşır ve `reduce()` ile çalışma zamanında düşürülebilir. `ResearchFlow._table_fill`, `target["sources"]`'tan üretilen (kaynak, sütun-öbeği) işlerini bu sınırlayıcı üzerinden gönderir; gönderim öncesi bugünkü `_checkpoint` aynen çalışır (duraklatma/iptal/revizyon değişince yeni gönderim durur), ama artık uçuştaki işler iptal edilmez, bitirilmeye bırakılır ve kendi `run_steps` satırlarına yazılır; sonucun hücreye **uygulanması** ayrı, raise etmeyen bir kapı (`_fill_stopped`) ile kontrol edilir — bu da bugünkü sıralı davranışla (bir duraklatma/iptal anında hesaplanmış ama henüz kaydedilmemiş sonuç, çalışma devam/yeniden başlayana kadar hücreye yazılmaz) birebir örtüşür. Kota/hız sınırı sınıflandırması modeller katmanında yeni, küçük bir sezgisel denetleyicidir (`models/adapter.py::is_rate_limited`); hiçbir adaptör bugün yapılandırılmış bir "rate_limited" durumu döndürmüyor. Sınırlayıcı `FlowDeps`'e yeni bir alan olarak eklenir; üretimde `Settings.model_concurrency` (env `DEIXIS_MODEL_CONCURRENCY`, varsayılan 6) ile kurulur, testlerde varsayılan olarak 1'dir (bugünkü sıralı davranışı hiçbir mevcut test bozulmadan korumak için).

**Tech Stack:** Python 3.12 (uv, native arm64), asyncio (tek olay döngüsü, tek SQLite bağlantısı), pytest, gerçek model koşusu için Codex/Claude Code/Gemini/DeepSeek bağlantıları (`gpt-5.6-luna`).

**Spec:** docs/product/p6-report-design.md (§2 karar 7, §4 "Eş zamanlılık kuralları", §12.0, §13 R7)

## Global Constraints

- Python 3.12 `uv` ile, venv native arm64: `python3 -c "import platform; print(platform.machine())"` → `arm64`.
- Backend testleri: `PYTHONPATH=backend uv run pytest` (tümü); odaklı: `PYTHONPATH=backend uv run pytest tests/test_table_fill_concurrency.py -q`.
- Tek SQLite bağlantısı API ve worker arasında paylaşılır; yazmalar kısa senkron işlemlerdir; bir işlem içinde asla `await` yok; UI'a görünen olaylar durumu tanımladıkları işlemle birlikte yazılır. Bu dilim bu kuralı bozmaz: model çağrısı (`await adapter.run_step(...)`) hiçbir zaman açık bir `transaction()` bloğunun içinde değildir — bugün de böyle, bu dilimden sonra da böyle (bkz. "Neden güvenli" altında task 4).
- Her adım `operation_key` ile anahtarlanmış bir satırdır; `succeeded` olmuş bir adım saklı çıktısını döner (replay). Bu dilim yeni bir kural eklemez, `ModelCallLimiter` bunu ek olarak (aynı anahtarın aynı anda iki kez gönderilmemesi) korur.
- Modele gönderilen her şey çağrıdan önce saklanır (`step_inputs`); modelin aracı yoktur; istenenden başka bir modelin çıktısı kaydedilir ama asla kullanılmaz (`model_mismatch`); şema onarımı sınırlıdır (`MAX_SCHEMA_REPAIRS = 1`, `backend/deixis/domain/rules.py:11`).
- Bu dilim şema/sözleşme değişikliği **gerektirmez**: yeni görev türü yok, `contracts/research/*.schema.json` değişmez, `skill_package_hash` değişmez, `tests/fixtures/research/*.json` ve `tests/fakes.py::valid_response` değişmez (yalnız `FakeAdapter`'a geriye dönük uyumlu yeni, varsayılanı etkisiz parametreler eklenir).
- Bu dilim migration **gerektirmez**: `runs.kind` listesinde `table_fill` zaten var, yeni tablo yok. En son migration bu not yazılırken `0033_work_source_keys.sql`'dir; bu dilim onu değiştirmez ve yeni bir numaralı dosya eklemez.
- Testler model bağımsızdır: `tests/fakes.py::FakeAdapter`, `create_app`'e enjekte edilen sahte bağlantılar. Gerçek model koşusu ölçüm görevinde `gpt-5.6-luna`'yı açıkça geçirir, kütüphanenin bir KOPYASI ve kendi `DEIXIS_DATA_DIR`'i ile, port 8799'da; canlı 8765 servisine dokunulmaz.
- Commit'ler doğrudan `main`'e gider: açıklayıcı İngilizce cümle, AI ilişkilendirmesi/ortak yazarlık yok, yalnız o görevin dosyaları `git commit -- <paths>` ile stage edilir (başka oturumlar aynı ağacı düzenliyor), sonra `git push origin main`.
- Bu dilimde alınan kalıcı karar `docs/decisions.md`'ye yürütme anındaki ilk boş D numarasıyla eklenir; bu not yazılırken en yüksek numara D59'dur, ama D57 iki kez talep edilmiş durumda — yürütmeden hemen önce `grep -n '^## D' docs/decisions.md | head -3` ile teyit edilmeli.

## Dosya yapısı

Yeni dosyalar:

- `backend/deixis/workflow/concurrency.py` — `ModelCallLimiter`: ayarlanabilir eş zamanlı çağrı sınırı ve `operation_key` başına tek-uçuş. Rapor (dilim 1) da bunu içe aktaracak; bu dilim raporla ilgili hiçbir şey eklemez.
- `tests/test_concurrency.py` — `ModelCallLimiter`'ın kendi birim testleri (üst sınır, `reduce()` tabanı, tek-uçuş).
- `tests/test_table_fill_concurrency.py` — `_table_fill`'in eş zamanlı davranışının testleri: sınıra uyma, sınır 1'de bugünküyle aynı çıktı, bir kaynağın hatası diğerlerini durdurmaz, duraklatma/iptal uçuştaki çağrıları bitirir ve doğru şekilde uygular/uygulamaz, hız sınırında sınır düşer ve en fazla iki kez yeniden gönderilir, hız sınırı olmayan bir hata yeniden gönderilmez.
- `scripts/p6_eval/measure_fill.py` — D55 kıyaslamasıyla aynı araştırmada, eş zamanlı hâlin süresini ölçen betik (yapısı `scripts/p4_eval/measure.py`'yi izler); dilim 1'in `scripts/p6_eval/measure_report.py`'siyle aynı dizini paylaşır.
- `docs/product/p6-slice0-fill-expectations.md` — koşudan önce donan süre beklentisi (P5 dilim 5 kuralı: beklenti sonuçtan önce yazılır).

Değiştirilecek dosyalar:

- `backend/deixis/config.py` — `Settings.model_concurrency: int = 6` alanı ve `load_settings()`'te `DEIXIS_MODEL_CONCURRENCY` okunması.
- `backend/deixis/domain/rules.py` — `MAX_RATE_LIMIT_MODEL_RETRIES = 2` sabiti (`MAX_SCHEMA_REPAIRS`in yanına).
- `backend/deixis/models/adapter.py` — `is_rate_limited(result: ModelStepResult) -> bool`: hiçbir adaptörün bugün yapılandırılmış bir hız-sınırı durumu vermemesi yüzünden gerekli, sezgisel (metin tabanlı) bir sınıflandırıcı.
- `backend/deixis/workflow/flow.py` — `FlowDeps.limiter` alanı; `_FillJob` veri sınıfı; `_call_adapter` (yeni, hız-sınırı yeniden gönderimi); `_model_step`'e `limiter` parametresi; `_extraction`'a `limiter` parametresi (yalnız `_table_fill` geçirir, `_cell_recheck` geçirmez); `_table_fill`'in eş zamanlı gönderim döngüsüyle yeniden yazılması; `_fill_jobs`, `_fill_stopped` yeni yardımcı metotlar.
- `backend/deixis/api/app.py` — `ModelCallLimiter(settings.model_concurrency)` kurulup `FlowDeps(...)`'e geçirilmesi.
- `tests/fakes.py` — `FakeAdapter`'a geriye dönük uyumlu `delay`, `before`, `fail` parametreleri ve `max_concurrent` sayacı (varsayılanları etkisiz; mevcut hiçbir testi değiştirmez).
- `tests/acceptance/fixture_server.py` — `Settings(...)` çağrısına `model_concurrency=1` eklenir (aksi hâlde `[slow-cells]` Playwright senaryosunun "aynı anda tek yazma" varsayımı üretimdeki varsayılan eş zamanlılıkla bozulur).
- `docs/decisions.md` — bu dilimin kalıcı kararı (yeni D numarası).
- `docs/product/p6-report-design.md` — §12 madde 0'ın durum satırı güncellenir.

## Task 1: `ModelCallLimiter`

**Files:**
- Create: `backend/deixis/workflow/concurrency.py`
- Test: `tests/test_concurrency.py`

**Interfaces:**
- Produces: `class ModelCallLimiter: def __init__(self, limit: int); @property def limit(self) -> int; async def reduce(self) -> int; async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_concurrency.py
import asyncio

import pytest

from deixis.workflow.concurrency import ModelCallLimiter


@pytest.mark.asyncio
async def test_at_most_limit_calls_run_at_once():
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


@pytest.mark.asyncio
async def test_reduce_halves_the_limit_with_a_floor_of_one():
    limiter = ModelCallLimiter(6)
    assert await limiter.reduce() == 3
    assert await limiter.reduce() == 1
    assert await limiter.reduce() == 1  # floor: never zero
    assert limiter.limit == 1


@pytest.mark.asyncio
async def test_reduce_lowers_the_ceiling_for_calls_still_waiting():
    limiter = ModelCallLimiter(2)
    started = []

    async def slow(name):
        started.append(name)
        await asyncio.sleep(0.05)
        return name

    first = asyncio.ensure_future(limiter.run("a", lambda: slow("a")))
    second = asyncio.ensure_future(limiter.run("b", lambda: slow("b")))
    await asyncio.sleep(0.01)  # both a and b hold a slot now
    await limiter.reduce()  # limit -> 1; a third call must wait for one of a, b to finish
    third = asyncio.ensure_future(limiter.run("c", lambda: slow("c")))
    await asyncio.sleep(0.01)
    assert "c" not in started  # c is still waiting: 2 are already in flight under a limit of 1
    await asyncio.gather(first, second, third)
    assert started == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_same_key_in_flight_is_never_sent_twice():
    limiter = ModelCallLimiter(4)
    calls = 0

    async def work():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return "value"

    results = await asyncio.gather(*(limiter.run("same-key", work) for _ in range(3)))
    assert results == ["value"] * 3 and calls == 1  # the second and third callers waited for the first's result
```

- [ ] **Step 2: Run it to confirm the failure**

Run: `PYTHONPATH=backend uv run pytest tests/test_concurrency.py -q`
Expected: `ModuleNotFoundError: No module named 'deixis.workflow.concurrency'`

- [ ] **Step 3: Implement the limiter**

```python
# backend/deixis/workflow/concurrency.py
"""Process-wide bound on concurrent model calls, shared by table fill (P6 slice 0) and, later, the report run.

A model call is send-then-wait: nothing about it needs the database connection while it is in flight (flow.py
never awaits inside a transaction), so several calls may be in flight at once as long as their number stays under
a limit that can drop at runtime, on a rate-limit response, without dropping calls already in flight.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class ModelCallLimiter:
    """Bounds how many model calls run at once and keeps one operation_key from running twice concurrently.

    The bound is process-wide and mutable: reduce() lowers it (floor 1) when a call comes back rate-limited; calls
    already granted a slot keep running, and the next call to wait for a slot sees the lower ceiling. run() is the
    only way to send a call through the limiter; a second call for a key already in flight waits for and returns
    the first call's outcome instead of sending its own.
    """

    def __init__(self, limit: int):
        self._limit = max(1, limit)
        self._in_flight = 0
        self._condition = asyncio.Condition()
        self._by_key: dict[str, asyncio.Task[Any]] = {}

    @property
    def limit(self) -> int:
        return self._limit

    async def reduce(self) -> int:
        async with self._condition:
            self._limit = max(1, self._limit // 2)
            self._condition.notify_all()
            return self._limit

    async def run(self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        existing = self._by_key.get(key)
        if existing is not None:
            return await existing
        task: asyncio.Task[T] = asyncio.ensure_future(self._run_one(factory))
        self._by_key[key] = task
        try:
            return await task
        finally:
            del self._by_key[key]

    async def _run_one(self, factory: Callable[[], Awaitable[T]]) -> T:
        async with self._condition:
            await self._condition.wait_for(lambda: self._in_flight < self._limit)
            self._in_flight += 1
        try:
            return await factory()
        finally:
            async with self._condition:
                self._in_flight -= 1
                self._condition.notify_all()
```

Note: `pytest-asyncio` must be available for the `@pytest.mark.asyncio` tests above. Check `pyproject.toml`/`uv.lock` first (`grep -n pytest-asyncio pyproject.toml`); if it is not a dependency, write these four tests with `asyncio.run(...)` wrapping a single `async def main(): ...` body instead of `@pytest.mark.asyncio`, matching how `tests/test_table_extraction.py::execute` drives the flow (`asyncio.run(lib.flow.execute(run["id"]))`) — do not add a new test dependency for this alone.

- [ ] **Step 4: Run it to confirm it passes**

Run: `PYTHONPATH=backend uv run pytest tests/test_concurrency.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/workflow/concurrency.py tests/test_concurrency.py
git commit -m "Add a process-wide, adjustable model-call concurrency limiter"
```

## Task 2: the concurrency setting and wiring

**Files:**
- Modify: `backend/deixis/config.py:21-56` (the `Settings` dataclass and `load_settings()`)
- Modify: `backend/deixis/api/app.py:279-350` (`create_app`)
- Modify: `backend/deixis/workflow/flow.py:20,132-140` (imports, `FlowDeps`)

**Interfaces:**
- Consumes: `ModelCallLimiter` from task 1.
- Produces: `Settings.model_concurrency: int`; `FlowDeps.limiter: ModelCallLimiter`.

- [ ] **Step 1: Add the setting**

In `backend/deixis/config.py`, add a field to `Settings` and read it in `load_settings()`:

```python
@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    model_concurrency: int = 6
```

```python
    return Settings(
        data_dir=default_data_dir(),
        host=os.environ.get("DEIXIS_HOST", "127.0.0.1"),
        port=int(os.environ.get("DEIXIS_PORT", "8765")),
        model_concurrency=max(1, int(os.environ.get("DEIXIS_MODEL_CONCURRENCY", "6") or "6")),
    )
```

- [ ] **Step 2: Give `FlowDeps` a limiter, defaulting to sequential (1) for every test and call site that does not set one**

In `backend/deixis/workflow/flow.py`, change the dataclasses import and `FlowDeps`:

```python
from dataclasses import dataclass, field
```

```python
@dataclass
class FlowDeps:
    settings: Settings
    store: Store
    adapters: dict[str, ModelAdapter]
    package: SkillPackage
    http: httpx.AsyncClient
    fetch_pdf: Callable[[str], Awaitable[fetch_module.FetchResult]] = fetch_module.fetch_pdf
    equations: Any = None  # workflow.equations.EquationService when the equation reader is set up (D52)
    limiter: ModelCallLimiter = field(default_factory=lambda: ModelCallLimiter(1))
```

Add the import near the other `deixis.workflow` imports:

```python
from deixis.workflow.concurrency import ModelCallLimiter
```

The default of 1 is deliberate: every existing test builds `FlowDeps(...)` without a `limiter` argument (see `tests/test_table_extraction.py::library`), and those tests script the fake adapter to mutate run state (pause, cancel) from inside one call, assuming the next source is not yet in flight. A default of 1 keeps every one of them passing unmodified; task 4's tests pass an explicit higher `limiter` to exercise real concurrency.

- [ ] **Step 3: Wire the real limiter into the running app**

In `backend/deixis/api/app.py`, inside `create_app`'s `lifespan`, change:

```python
        flow = ResearchFlow(FlowDeps(settings, store, adapter_map, package, http, fetcher or fetch_module.fetch_pdf, equations))
```

to:

```python
        flow = ResearchFlow(FlowDeps(settings, store, adapter_map, package, http, fetcher or fetch_module.fetch_pdf, equations,
                                     limiter=ModelCallLimiter(settings.model_concurrency)))
```

Add the import next to the other `deixis.workflow` imports in `app.py`:

```python
from deixis.workflow.concurrency import ModelCallLimiter
```

- [ ] **Step 4: Confirm nothing else broke**

Run: `PYTHONPATH=backend uv run pytest tests/test_table_extraction.py -q`
Expected: all pass, unchanged (this task only adds a default-valued field and one call site; `_table_fill` itself is not touched yet).

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/config.py backend/deixis/api/app.py backend/deixis/workflow/flow.py
git commit -m "Add a DEIXIS_MODEL_CONCURRENCY setting and wire a shared limiter into FlowDeps"
```

## Task 3: classify a rate-limited model call

**Files:**
- Modify: `backend/deixis/models/adapter.py:1-53` (imports, after `ModelStepResult`)
- Modify: `backend/deixis/domain/rules.py:11-13`
- Test: `tests/test_adapter_rate_limit.py`

**Interfaces:**
- Produces: `is_rate_limited(result: ModelStepResult) -> bool`; `MAX_RATE_LIMIT_MODEL_RETRIES: int` in `deixis.domain.rules`.

No adapter today reports a structured rate-limit status: `ModelStepResult.status` is one of `completed`, `failed`, `interrupted`, `unavailable`, `isolation_violation` (`backend/deixis/models/adapter.py:41-52`), and `gemini.py:120-121` already folds a 429 into `ModelStepResult("failed", error=f"HTTP {response.status_code}: ...")` — the digits are in the free-text error, not a field. Codex and Claude Code wrap CLI/SDK errors as free text too. This is unlike provider search rate limits, which providers/common.py classifies structurally (`SearchOutcome("rate_limited", ...)`, `MAX_RATE_LIMIT_RETRIES = 2`). Given that, this task adds a best-effort text classifier rather than touching every adapter; it is explicitly not a safety-relevant classification (a miss just means today's pause-on-any-failure behavior applies, which is always correct, just not optimized).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_adapter_rate_limit.py
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
```

- [ ] **Step 2: Run it to confirm the failure**

Run: `PYTHONPATH=backend uv run pytest tests/test_adapter_rate_limit.py -q`
Expected: `ImportError: cannot import name 'is_rate_limited'`

- [ ] **Step 3: Implement the classifier and the retry-count constant**

In `backend/deixis/models/adapter.py`, add `import re` to the imports and, right after the `ModelStepResult` dataclass, add:

```python
RATE_LIMIT_ERROR_RE = re.compile(r"\b(429|rate.?limit|too many requests|quota|resource_exhausted|resource has been exhausted)\b",
                                 re.IGNORECASE)


def is_rate_limited(result: ModelStepResult) -> bool:
    """Best-effort read of a failed call's free-text error as a provider rate limit or quota response.

    No adapter reports a structured rate-limit status today (unlike providers/common.py's search retries). A miss
    here only means the ordinary pause-on-failure path runs, which is always a correct (if less helpful) outcome.
    """
    return result.status == "failed" and bool(result.error) and bool(RATE_LIMIT_ERROR_RE.search(result.error))
```

In `backend/deixis/domain/rules.py`, add next to `MAX_SCHEMA_REPAIRS`:

```python
MAX_RATE_LIMIT_MODEL_RETRIES = 2  # extra resends of one model call after a rate-limited response, before it halts as today
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `PYTHONPATH=backend uv run pytest tests/test_adapter_rate_limit.py -q`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/deixis/models/adapter.py backend/deixis/domain/rules.py tests/test_adapter_rate_limit.py
git commit -m "Add a best-effort rate-limit classifier for model call results"
```

## Task 4: make `_table_fill` send its calls concurrently

**Files:**
- Modify: `backend/deixis/workflow/flow.py:743-777` (`_table_fill`), `:817-834` (`_extraction`), `:931-1028` (`_model_step`)

**Interfaces:**
- Consumes: `ModelCallLimiter` (task 1), `is_rate_limited`, `MAX_RATE_LIMIT_MODEL_RETRIES` (task 3), `FlowDeps.limiter` (task 2).
- Produces: `ResearchFlow._fill_jobs`, `ResearchFlow._fill_stopped`, `ResearchFlow._call_adapter`; `_extraction(..., limiter: ModelCallLimiter | None = None)`; `_model_step(..., limiter: ModelCallLimiter | None = None)`.

**Why this is safe under "one connection, short synchronous transactions, never await inside one":** every `Store`/`TableStore` write already happens inside `with transaction(self.conn): ...` blocks that contain no `await` (see `store.py:1-7`'s own docstring and e.g. `finish_step`, `complete_model_step`, `TableStore.save_model_output`). The only `await` in the whole call path is `await adapter.run_step(...)` (network I/O) and `await asyncio.sleep(...)` (task 4's new backoff), neither of which is inside a transaction. Because Python's asyncio is single-threaded and cooperative, two concurrently-running `_extraction()` calls can only ever interleave *between* transactions, never inside one — so running several of them as separate `asyncio.Task`s does not change the "one writer at a time" invariant; it only changes which task's turn it is between one `store.execute(...)` and the next. This is why running steps concurrently needs no new locking.

**Existing behavior this preserves (found while reading `tests/test_table_extraction.py`):**
- `test_cancel_during_a_fill_keeps_written_values_and_drops_the_call_in_progress`: a cell_extraction call that completes successfully *after* the run was cancelled (by the responder, mid-call) is still recorded as a `succeeded` step, but its answer is never written to a cell. `_checkpoint(run_id)` (called right after the call returns, before `_save_cells`) sees `status == "cancelled"` and raises before `_save_cells` runs.
- `test_pause_during_a_fill_writes_the_call_result_only_after_resume`: identical mechanism for `pause_requested` → `paused`; the succeeded step's cached output is only applied once the run resumes and `_extraction` returns the cached output without a new model call, and this time `_checkpoint` does not trip.
- So today, *neither* pause nor cancel applies an in-flight call's result immediately; both record the step and defer application — pause defers it to a future resume, cancel defers it forever (resume is refused for a cancelled run). Task 4 keeps this distinction exactly, just makes it correct when several calls are in flight instead of at most one.

- [ ] **Step 1: Write the failing tests (extend the fake adapter first)**

In `tests/fakes.py`, add `import asyncio` at the top, and extend `FakeAdapter` (every new parameter defaults to something that makes it behave exactly as it does today):

```python
class FakeAdapter:
    connection = "fake"

    def __init__(self, responder: Callable[[dict[str, Any]], str] = valid_response, ready: bool = True,
                 resolved_model: str | None = None, models: list[str] | None = None, efforts: list[str] | None = None,
                 delay: float = 0.0, before: Callable[[dict[str, Any]], None] | None = None,
                 fail: Callable[[dict[str, Any]], "ModelStepResult | None"] | None = None):
        self.responder = responder
        self.ready = ready
        self.resolved_model = resolved_model
        self.models = models
        self.efforts = efforts or []
        self.delay = delay
        self.before = before
        self.fail = fail
        self.calls: list[dict[str, Any]] = []
        self.sent_efforts: list[str | None] = []
        self.sent: list[tuple[str, str | None, str | None]] = []
        self.current = 0
        self.max_concurrent = 0

    async def health(self, refresh: bool = False) -> dict[str, Any]:
        status = {"connection": "fake", "ready": self.ready, "reason": None if self.ready else "fake not ready"}
        if self.models is not None:
            status["models"] = [{"id": m, "display_name": m, "is_default": False,
                                 "reasoning_efforts": [{"id": e, "description": ""} for e in self.efforts]} for m in self.models]
        return status

    async def run_step(self, base, developer, message, output_schema, requested_model, reasoning_effort=None) -> ModelStepResult:
        si = parse_step_input(message)
        self.calls.append(si)
        self.sent_efforts.append(reasoning_effort)
        self.sent.append((si["task_type"], requested_model, reasoning_effort))
        if self.before:
            self.before(si)
        self.current += 1
        self.max_concurrent = max(self.max_concurrent, self.current)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail and (result := self.fail(si)) is not None:
                return result
            return ModelStepResult("completed", raw_text=self.responder(si), resolved_model=self.resolved_model or requested_model)
        finally:
            self.current -= 1

    async def cancel(self) -> bool:
        return False

    async def close(self) -> None:
        pass
```

Run: `PYTHONPATH=backend uv run pytest tests/test_table_extraction.py tests/test_evidence_tables.py -q`
Expected: all still pass (every new parameter defaults to a no-op).

Now write `tests/test_table_fill_concurrency.py`:

```python
# tests/test_table_fill_concurrency.py
"""P6 slice 0: _table_fill sends its per-source cell_extraction calls concurrently under a shared, adjustable
limit. These are FakeAdapter tests; they show workflow behavior, not model quality.
"""

import asyncio
from types import SimpleNamespace

import pytest

from deixis.config import Settings
from deixis.domain import skill
from deixis.models.adapter import ModelStepResult
from deixis.storage import db
from deixis.storage.db import transaction
from deixis.workflow import flow as flow_module
from deixis.workflow.concurrency import ModelCallLimiter
from deixis.workflow.flow import FlowDeps, ResearchFlow
from deixis.workflow.store import Store
from deixis.workflow.tables import TableStore
from fakes import FakeAdapter, valid_response
from test_evidence_tables import PACKET_SIZE


def library_with_sources(path, n, limit, responder=valid_response, delay=0.0, before=None, fail=None):
    conn = db.connect(path / "library.sqlite")
    db.migrate(conn)
    store = Store(conn)
    rid = store.create_research("How large are packets?", "attached", "quick", [], "fake", "fake-model", None)
    svids = []
    for i in range(n):
        svid = store.create_upload_source(f"SYNTHETIC source {i:02d}")
        with transaction(conn):
            store._insert_passage(svid, None, "abstract", None, None, "user", None, None, f"SYNTHETIC abstract {i}: packets of {i} bytes.")
        store.add_to_corpus(rid, svid, "user_upload", selection_state="included", selection_origin="user")
        svids.append(svid)
    tables = TableStore(store)
    tid = tables.create_table(rid, "Packets", None, None, None)
    cid = tables.add_column(rid, tid, PACKET_SIZE, 1, None)
    adapter = FakeAdapter(responder, delay=delay, before=before, fail=fail)
    deps = FlowDeps(Settings(data_dir=path / "data", port=8765), store, {"fake": adapter}, skill.load_skill_package(), None,
                    limiter=ModelCallLimiter(limit))
    flow = ResearchFlow(deps)
    return SimpleNamespace(conn=conn, store=store, tables=tables, rid=rid, svids=svids, tid=tid, cid=cid, adapter=adapter, flow=flow)


def fill(lib):
    version = lib.tables.table_view(lib.rid, lib.tid)["table"]["version"]
    return lib.tables.request_fill(lib.rid, lib.tid, None, False, version, None)


def execute(lib, run):
    lib.store.update_run(run["id"], status="running")
    asyncio.run(lib.flow.execute(run["id"]))
    return lib.store.run(run["id"])


def cell_values(lib):
    view = lib.tables.table_view(lib.rid, lib.tid)
    return {c["source_version_id"]: (c["current"]["value"] if c["current"] else None) for c in view["cells"]}


def test_the_limit_bounds_concurrent_calls_and_matches_sequential_output(tmp_path):
    sequential = library_with_sources(tmp_path / "seq", 6, limit=1, delay=0.01)
    execute(sequential, fill(sequential))
    concurrent = library_with_sources(tmp_path / "con", 6, limit=3, delay=0.01)
    execute(concurrent, fill(concurrent))

    assert concurrent.adapter.max_concurrent > 1  # real concurrency happened
    assert concurrent.adapter.max_concurrent <= 3  # and stayed within the limit
    assert len(sequential.adapter.calls) == len(concurrent.adapter.calls) == 6
    assert cell_values(sequential) == cell_values(concurrent)  # limit 1 vs limit 3: the same cells, the same values


def test_one_sources_invalid_output_does_not_stop_the_others(tmp_path):
    def responder(si):
        if si["extraction_target"]["source_id"] == broken:
            return "not json"
        return valid_response(si)

    lib = library_with_sources(tmp_path, 4, limit=3, responder=responder)
    broken = lib.svids[1]
    run = execute(lib, fill(lib))
    assert run["status"] == "completed"
    values = cell_values(lib)
    assert values[broken] is None
    assert all(values[svid] is not None for svid in lib.svids if svid != broken)


def test_pause_lets_in_flight_calls_finish_and_applies_them_only_on_resume(tmp_path):
    holder = {"paused": False}

    def before(si):
        if not holder["paused"]:
            holder["paused"] = True
            holder["lib"].store.update_run(si["run_id"], event="run_pause_requested", status="pause_requested",
                                           pause_reason="user_requested")

    lib = library_with_sources(tmp_path, 6, limit=3, delay=0.02, before=before)
    holder["lib"] = lib
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "user_requested")
    assert len(lib.adapter.calls) == 3  # the second batch of 3 was never submitted
    assert all(v is None for v in cell_values(lib).values())  # the first batch's results are recorded but not applied yet
    steps = [s for s in lib.store.run_steps(run["id"]) if s["kind"] == "model:cell_extraction"]
    assert [s["status"] for s in steps] == ["succeeded"] * 3

    resumed = execute(lib, run)
    assert resumed["status"] == "completed"
    assert len(lib.adapter.calls) == 6  # the first 3 were not asked again; the last 3 are new calls
    assert all(v is not None for v in cell_values(lib).values())


def test_cancel_lets_in_flight_calls_finish_but_never_applies_them(tmp_path):
    holder = {"cancelled": False}

    def before(si):
        if not holder["cancelled"]:
            holder["cancelled"] = True
            holder["lib"].store.update_run(si["run_id"], event="run_cancelled", status="cancelled", pause_reason="user_cancelled")

    lib = library_with_sources(tmp_path, 6, limit=3, delay=0.02, before=before)
    holder["lib"] = lib
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("cancelled", "user_cancelled")
    assert len(lib.adapter.calls) == 3
    assert all(v is None for v in cell_values(lib).values())
    steps = [s for s in lib.store.run_steps(run["id"]) if s["kind"] == "model:cell_extraction"]
    assert [s["status"] for s in steps] == ["succeeded"] * 3  # recorded, permanently unapplied (resume is refused elsewhere)


def test_a_rate_limited_call_lowers_the_limit_and_is_resent_up_to_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)
    attempts = {"n": 0}

    def fail(si):
        attempts["n"] += 1
        return ModelStepResult("failed", error="HTTP 429: Too Many Requests") if attempts["n"] == 1 else None

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert run["status"] == "completed"
    assert attempts["n"] == 2  # one rate-limited attempt, one resend that succeeded
    assert lib.flow.deps.limiter.limit == 2  # halved once
    assert all(v is not None for v in cell_values(lib).values())


def test_a_rate_limit_that_never_clears_still_halts_like_today(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_module, "RATE_LIMIT_BACKOFF_SECONDS", 0)

    def fail(si):
        return ModelStepResult("failed", error="HTTP 429: Too Many Requests")

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert len(lib.adapter.calls) == 3  # 1 original + MAX_RATE_LIMIT_MODEL_RETRIES resends
    assert lib.flow.deps.limiter.limit == 1  # halved twice, floor 1


def test_a_non_rate_limit_failure_is_not_resent(tmp_path):
    def fail(si):
        return ModelStepResult("failed", error="ConnectError: timeout", delivery_class="after_send_unknown")

    lib = library_with_sources(tmp_path, 1, limit=4, fail=fail)
    run = execute(lib, fill(lib))
    assert (run["status"], run["pause_reason"]) == ("paused", "model_call_failed")
    assert len(lib.adapter.calls) == 1  # no resend: not classified as a rate limit
```

- [ ] **Step 2: Run the new file to confirm it fails**

Run: `PYTHONPATH=backend uv run pytest tests/test_table_fill_concurrency.py -q`
Expected: failures — `_table_fill` is still sequential and ignores `limiter`, `FlowDeps.limiter` does not exist yet in a form `_table_fill` reads, and `flow_module.RATE_LIMIT_BACKOFF_SECONDS` does not exist. (Tasks 1–3 must already be committed before this step; if they are not, you will also see `ModuleNotFoundError`/`ImportError` from those.)

- [ ] **Step 3: Implement — add `_FillJob`, `_call_adapter`, and thread `limiter` through `_model_step` and `_extraction`**

In `backend/deixis/workflow/flow.py`, add near the top, after the other module constants (after `FORMULATION_SYMBOLS`/`STOPWORDS`, before `formulation_score`):

```python
RATE_LIMIT_BACKOFF_SECONDS = 1.5  # matches the provider search retry backoff in providers/common.py
```

Add the import:

```python
from deixis.domain.rules import (MAX_ACTIVE_MODEL_CALLS, MAX_RATE_LIMIT_MODEL_RETRIES, MAX_SCHEMA_REPAIRS,
                                 MAX_TRANSIENT_NETWORK_RETRIES, SCREENING_BATCH, after_invalid_output,
                                 effective_reviewer, step_model)
from deixis.models.adapter import ModelAdapter, is_rate_limited
```

(`MAX_ACTIVE_MODEL_CALLS` is imported here only because it already exists unused in `domain/rules.py`; leave it alone — do not repurpose its value of 1 as the concurrency default, since it predates this feature and nothing references it. If the linter flags it as unused, drop it from this import instead of deleting it from `rules.py`.)

Replace `_model_step`'s two lines that start the model session and call the adapter (`backend/deixis/workflow/flow.py:978-979`):

```python
            session = self.store.start_model_session(rid, run_id, step["id"], payload["step_input_id"], connection, requested_model)
            result = await adapter.run_step(base, developer, message, schema, requested_model, reasoning_effort)
```

with:

```python
            session, result = await self._call_adapter(run_id, rid, step["id"], payload["step_input_id"], connection,
                                                        requested_model, adapter, base, developer, message, schema,
                                                        reasoning_effort, limiter)
```

Add `limiter: ModelCallLimiter | None = None` as the last parameter of `_model_step`'s signature (`flow.py:931-935`), and add this new method right above `_model_step`:

```python
    async def _call_adapter(self, run_id: str, rid: str, step_id: str, step_input_id: str, connection: str,
                            requested_model: str | None, adapter: ModelAdapter, base: str, developer: str, message: str,
                            schema: dict[str, Any], reasoning_effort: str | None,
                            limiter: ModelCallLimiter | None) -> tuple[str, ModelStepResult]:
        """Send one model call, resending under the limiter's lower ceiling when the response looks rate-limited
        (P6 slice 0, §4). Nothing sent to the model changes between resends, so the StepInput row already written
        is reused; each resend gets its own model_sessions row (model_session() already reads the latest one). A
        resend that is still rate-limited, or any other failure, is returned for the caller to record and, if it
        does not recover, halt on exactly as before. Passing limiter=None (every step but cell_extraction, for now)
        makes this a plain, unretried call, unchanged from today."""
        attempts = 0
        while True:
            session = self.store.start_model_session(rid, run_id, step_id, step_input_id, connection, requested_model)
            result = await adapter.run_step(base, developer, message, schema, requested_model, reasoning_effort)
            if limiter is None or result.status == "completed" or attempts >= MAX_RATE_LIMIT_MODEL_RETRIES or not is_rate_limited(result):
                return session, result
            attempts += 1
            self.store.finish_model_session(
                session, status=result.status, resolved_model=result.resolved_model, external_thread_id=result.external_thread_id,
                raw_output=result.raw_text, token_usage_json=result.token_usage, tool_item_types_json=result.tool_item_types,
            )
            await limiter.reduce()
            self._checkpoint(run_id)
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS * attempts)
```

Add the import for `ModelCallLimiter` and `ModelStepResult` at the top of `flow.py` (the module already imports `ModelAdapter` from the same place):

```python
from deixis.models.adapter import ModelAdapter, ModelStepResult, is_rate_limited
from deixis.workflow.concurrency import ModelCallLimiter
```

Now thread `limiter` through `_extraction` (`flow.py:817-834`). Add the parameter and pass it to the one `_model_step` call at the bottom:

```python
    async def _extraction(self, run: dict[str, Any], scope: dict[str, Any], key: str, svid: str, columns: list[dict[str, Any]],
                          limit: int, limiter: ModelCallLimiter | None = None) -> dict[str, Any] | None:
        """One cell extraction step for one source; None when the source has no stored text to give."""
        step = self.store.step(run["id"], key, "model:cell_extraction")
        if step["status"] == "succeeded":
            return step["output"]
        if step["status"] == "failed" and step["error_code"] == "invalid_model_output":
            return {"invalid": True, "step_input_id": step["output"]["step_input_id"], "issues": json.loads(step["error_json"] or "null")}
        available = self.store.passages_for(svid)
        if not available:
            return None
        given = await self._cell_passages(run, scope, key, svid, columns, available, limit)
        pages = {p["id"] for p in available if p["kind"] == "pdf_page"}
        target = {"table_id": run["target"]["table_id"], "source_id": svid, "columns": [extraction_column(c) for c in columns],
                  "passage_scope": {"given": len(given), "available": len(available),
                                    "all_pages_given": bool(pages) and pages <= {p["id"] for p in given}}}
        return await self._model_step(run, scope, key, "cell_extraction", source_ids=[svid], passage_rows=given,
                                      extraction_target=target, limiter=limiter)
```

`_cell_recheck`'s existing call to `_extraction` (`flow.py:788`) is left exactly as it is — it does not pass `limiter`, so it defaults to `None` and behaves exactly as today (no concurrency, no rate-limit resend). This is deliberate: this slice changes table fill only (§12 item 0 of the design note), not cell recheck.

- [ ] **Step 4: Rewrite `_table_fill`**

Replace the whole method (`flow.py:743-777`):

```python
    # ---- evidence tables ----------------------------------------------------------------
    async def _table_fill(self, run: dict[str, Any], scope: dict[str, Any]) -> None:
        """Fill the cells planned when the run was requested, sending several sources' calls at once (D37, P6 slice 0).

        A source's columns are asked together, at most MAX_COLUMNS_PER_CALL per call, and each call reads that source's
        passages only. A source without stored text gets 'inaccessible' from the system without a model call, written
        before any concurrent submission starts for it. Calls are sent through the run's shared limiter (FlowDeps.limiter):
        at most `limiter.limit` are in flight at once, and the same operation_key is never sent twice concurrently.
        `_checkpoint` still runs before every submission; once it stops new submissions (pause, cancel, or a newer scope
        revision), calls already in flight are left to finish and record their own step, but the run only *applies* a
        finished call's cells when `_fill_stopped` says the run is still on the revision it was sent for and not paused,
        cancelled or failed — matching today's rule that a pause or cancel never applies a result the moment it arrives,
        only (for a pause) on a later resume.
        """
        run_id, target = run["id"], run["target"]
        tables = TableStore(self.store)
        await self._read_equations(run, [planned["source_version_id"] for planned in target["sources"]])
        limiter = self.deps.limiter
        job_iter = self._fill_jobs(run, tables, target)
        pending: dict[asyncio.Task[dict[str, Any] | None], _FillJob] = {}
        stop: RunStopped | None = None

        def submit_more() -> None:
            nonlocal stop
            while stop is None and len(pending) < limiter.limit:
                try:
                    self._checkpoint(run_id, run["scope_revision"])
                except RunStopped as exc:
                    stop = exc
                    return
                job = next(job_iter, None)
                if job is None:
                    return

                async def call(job: _FillJob = job) -> dict[str, Any] | None:
                    return await self._extraction(run, scope, job.key, job.svid, job.columns, MAX_FILL_PASSAGES, limiter)

                pending[asyncio.ensure_future(limiter.run(job.key, call))] = job

        submit_more()
        while pending:
            done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                job = pending.pop(task)
                try:
                    output = task.result()
                except RunStopped as exc:
                    stop = stop or exc
                    continue
                if output is not None and not self._fill_stopped(run_id, run["scope_revision"]):
                    self._save_cells(run, output, job.cell_versions, recheck=False)
            submit_more()
        if stop is not None:
            raise stop

    def _fill_jobs(self, run: dict[str, Any], tables: TableStore, target: dict[str, Any]) -> Iterator["_FillJob"]:
        """Yield one job per (source, column-chunk) that still needs a model call, in table order; write a source's
        'inaccessible' cells synchronously as it is reached, exactly as the sequential code did (no model call, so it
        does not go through the limiter)."""
        for planned in target["sources"]:
            svid = planned["source_version_id"]
            columns = [c for c in self._live_columns(run, tables) if c["id"] in planned["column_ids"]]
            if not columns or svid not in tables.active_rows(target["table_id"]):
                continue  # the column or row was removed after the fill was requested
            if not self.store.passages_for(svid):
                step = self.store.step(run["id"], f"no_text:{svid}", "table_no_text")
                if step["status"] != "succeeded":
                    self.store.start_step(step["id"])
                    saved = [tables.save_no_text(run["research_id"], target["table_id"], c["id"], svid, column_revision=c["current_revision"],
                                                 run_id=run["id"], step_id=step["id"], scope_revision=run["scope_revision"]) for c in columns]
                    self.store.finish_step(step["id"], "succeeded", output={"source_version_id": svid, "cells": sum(s is not None for s in saved)})
                continue
            for index in range(0, len(planned["column_ids"]), MAX_COLUMNS_PER_CALL):
                chunk = [c for c in columns if c["id"] in planned["column_ids"][index:index + MAX_COLUMNS_PER_CALL]]
                if chunk:
                    yield _FillJob(f"cell_extraction:{svid}:{index // MAX_COLUMNS_PER_CALL}", svid, chunk, planned["cell_versions"])

    def _fill_stopped(self, run_id: str, scope_revision: int) -> bool:
        """Whether a table-fill call that just returned should still update its cell. A user pause (or any halt that
        leaves the run paused or failed) still applies its in-flight results normally; a cancel or a newer scope
        revision must not (T18) — its step stays recorded, but nothing it found reaches a cell."""
        run = self.store.run(run_id)
        if run["status"] in ("pause_requested", "paused", "cancelled", "failed"):
            return True
        return self.store.research(run["research_id"])["current_scope_revision"] != scope_revision
```

Add the small job record near the top of the "evidence tables" section (right before `_table_fill`):

```python
@dataclass
class _FillJob:
    key: str
    svid: str
    columns: list[dict[str, Any]]
    cell_versions: dict[str, int]
```

Add `Iterator` to the `typing` import at the top of the file:

```python
from typing import Any, Awaitable, Callable, Iterator
```

- [ ] **Step 5: Run the full test file**

Run: `PYTHONPATH=backend uv run pytest tests/test_table_fill_concurrency.py -q`
Expected: all pass.

- [ ] **Step 6: Run the whole existing table and flow suite to confirm nothing regressed**

Run: `PYTHONPATH=backend uv run pytest tests/test_table_extraction.py tests/test_evidence_tables.py tests/test_contracts.py -q`
Expected: all pass unchanged, including `test_pause_during_a_fill_writes_the_call_result_only_after_resume` and `test_cancel_during_a_fill_keeps_written_values_and_drops_the_call_in_progress`, which run with `FlowDeps`'s default `limiter=ModelCallLimiter(1)` and so should reproduce today's exact sequential behavior byte-for-byte.

- [ ] **Step 7: Run the full backend suite once**

Run: `PYTHONPATH=backend uv run pytest -q`
Expected: all pass. If collection fails on an unrelated, pre-existing environment issue, report the exact failure and run the largest justified subset instead (AGENTS.md verification matrix); do not claim a full pass you did not see.

- [ ] **Step 8: Commit**

```bash
git add backend/deixis/workflow/flow.py tests/fakes.py tests/test_table_fill_concurrency.py
git commit -m "Send table-fill cell extraction calls concurrently under a shared, adjustable limit"
```

## Task 5: acceptance harness — keep the scripted pause/resume/cancel demo deterministic

**Files:**
- Modify: `tests/acceptance/fixture_server.py:154-156`

**Interfaces:**
- Consumes: `Settings.model_concurrency` (task 2).

**Why:** `apps/web/e2e/acceptance.spec.ts`'s `'a table fill pauses, is reached from the tab bar, resumes, and cancels after a confirmation'` test (`[slow-cells]` marker, `tests/acceptance/fixture_server.py:100-101`: every `cell_extraction` call sleeps 1.5 s) scripts a fill over 4 sources and asserts an exact, one-at-a-time write count: `atPause < 4`, no new writes while paused, then `written().toHaveCount(atPause + 1)` right after Resume — one more cell, not several. `fixture_server.py` builds its own `Settings(...)` directly (not `load_settings()`, so `DEIXIS_MODEL_CONCURRENCY` is never read here) and calls `create_app(settings, ...)`, which — after task 2 — would default `FlowDeps.limiter` to `ModelCallLimiter(settings.model_concurrency)`, i.e. 6. With 4 sources at limit 6, all 4 would be sent essentially at once, so "one more write" after resume would become "all remaining writes at once", breaking this test's exact counts. Pin the fixture's own concurrency to 1 instead of touching the Playwright spec: the whole point of `[slow-cells]` is a narratable, one-step-at-a-time demo, which is what the acceptance suite wants to show regardless of what production concurrency is.

- [ ] **Step 1: Confirm the current assumption (read, do not run npm here)**

Read `apps/web/e2e/acceptance.spec.ts:584-625` (already quoted above) and `tests/acceptance/fixture_server.py:154-156` to confirm the exact call site:

```python
    settings = Settings(data_dir=args.data_dir, port=args.port)
    app = create_app(settings, adapters={"codex": ScriptedCodex()},
```

- [ ] **Step 2: Pin the fixture's concurrency to 1**

```python
    settings = Settings(data_dir=args.data_dir, port=args.port, model_concurrency=1)
    app = create_app(settings, adapters={"codex": ScriptedCodex()},
```

- [ ] **Step 3: Rebuild and run the acceptance suite**

Run:
```sh
cd apps/web && npm run build
DEIXIS_ACCEPTANCE_DIR=/tmp/deixis-acceptance npm run test:acceptance
```
Expected: the whole suite passes, including the `'Evidence table runs and templates'` describe block; report exactly what ran and whether anything besides this one line changed.

- [ ] **Step 4: Commit**

```bash
git add tests/acceptance/fixture_server.py
git commit -m "Keep the acceptance fixture's table fill sequential so its pause/resume demo stays exact"
```

## Task 6: measure it — expectations before the run

Per the P5 slice 5 rule (also followed by `docs/product/p6-slice1-report-expectations.md`), write and commit the expected range *before* running anything, then run and put raw numbers into ignored `.local/`.

**Files:**
- Create: `docs/product/p6-slice0-fill-expectations.md`
- Create: `scripts/p6_eval/measure_fill.py`

- [ ] **Step 1: Write and commit the expectations, before running anything**

`docs/product/p6-slice0-fill-expectations.md`:

```markdown
# P6 dilim 0 — doldurma süresi beklentisi (koşudan önce dondu)

D55'te aynı araştırmanın (50 dahil kaynak, `MAX_FILL_SOURCES = 25` yüzünden iki ayrı doldurma çalışması) sıralı
doldurması 506–576 saniye sürdü (~10–23 s/kaynak, sütun sayısına ve pasaj uzunluğuna göre değişerek).

Bu ölçüm aynı araştırmayı, aynı kütüphane kopyasını, `gpt-5.6-luna`'yı ve `DEIXIS_MODEL_CONCURRENCY=6`'yı kullanır.

- **Beklenen kazanç aralığı:** 25 kaynaklık bir doldurma çalışması için 100–260 saniye (kabaca D55'in 4–5'te
  biri ile 2'de biri arası; model çağrısı gecikmesi baskınsa ve sınır fiilen 6'da kalıyorsa daha kısa uca,
  şema onarımı/kota düşmesi sıksa daha uzun uca yaklaşır).
- **"Kazanç yok" eşiği:** toplam süre D55 sıralı ortalamasının (yaklaşık 540 s / 2 = 270 s tek doldurma başına)
  %80'inden daha az düşüyorsa (yani 216 s'nin altına inmiyorsa), darboğaz model-çağrısı kuyruklanması değildir;
  muhtemel adaylar: `_read_equations` (Marker/OCR, bu dilimde eş zamanlı değil ve `_table_fill`'den önce
  tamamlanır), PDF indirme/erişim gecikmesi, ya da hız sınırının pratikte 1'e düşüp kalması.
- **Ne ölçülmüyor:** hücre değerlerinin doğruluğu; bu yalnız yürütme süresidir (R7).

Ham sonuçlar `.local/p6-slice0-fill/` altına gider (repo'ya girmez); bu dosya sonuca göre yeniden yazılmaz.
```

Commit this file on its own before running anything:

```bash
git add docs/product/p6-slice0-fill-expectations.md
git commit -m "Freeze the P6 slice 0 table-fill duration expectation before measuring"
```

- [ ] **Step 2: Write the measurement script**

```python
# scripts/p6_eval/measure_fill.py
"""Compare table-fill duration with concurrency on against the D55 sequential baseline.

Run against a COPY of the library, its own DEIXIS_DATA_DIR, port 8799, gpt-5.6-luna. Never the live 8765 service.
Writes JSON with wall-clock duration and per-step timestamps to .local/p6-slice0-fill/ (ignored by git).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8799")
    parser.add_argument("--research-id", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--out", default=".local/p6-slice0-fill")
    args = parser.parse_args()

    Path(args.out).mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=args.base_url)
    table = client.get(f"/api/researches/{args.research_id}/tables/{args.table_id}").json()
    started = time.monotonic()
    run = client.post(f"/api/researches/{args.research_id}/tables/{args.table_id}/fill",
                      json={"expected_version": table["table"]["version"]}).json()
    run_id = run["id"]
    while True:
        current = client.get(f"/api/runs/{run_id}").json()
        if current["status"] not in ("queued", "running", "pause_requested"):
            break
        time.sleep(1.0)
    duration = time.monotonic() - started
    steps = [s for s in current["steps"] if s["kind"] == "model:cell_extraction"]
    result = {"run_id": run_id, "status": current["status"], "duration_seconds": duration, "cell_extraction_calls": len(steps),
             "step_timestamps": [{"operation_key": s["operation_key"], "started_at": s["started_at"], "finished_at": s["finished_at"]}
                                  for s in steps]}
    out_path = Path(args.out) / f"{run_id}.json"
    out_path.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it against a copy of the library**

```sh
cp -R ~/Library/Application\ Support/DEIXIS /tmp/deixis-p6-slice0-copy
DEIXIS_DATA_DIR=/tmp/deixis-p6-slice0-copy DEIXIS_PORT=8799 DEIXIS_MODEL_CONCURRENCY=6 \
  PYTHONPATH=backend uv run --no-sync python -m deixis serve --no-browser &
PYTHONPATH=backend uv run --no-sync python scripts/p6_eval/measure_fill.py \
  --base-url http://127.0.0.1:8799 --research-id <the D55 research id> --table-id <its table id>
```

Use the same research and table that D55's 50-source measurement used (find its id from the live library's Library view, then use the *copy*'s id, not the live one). Pass `gpt-5.6-luna` through the research's model settings before starting the fill, as the other D55 runs did.

- [ ] **Step 4: Compare against the frozen expectation**

Read the printed `duration_seconds` against the 100–260 s / 216 s-floor bands in `docs/product/p6-slice0-fill-expectations.md`. Do not edit that file to match the result; instead, add a short dated note to `docs/decisions.md`'s new entry (task 7) stating the measured number and which band it fell in.

- [ ] **Step 5: Commit the script only (results stay in `.local/`, already gitignored)**

```bash
git add scripts/p6_eval/measure_fill.py
git commit -m "Add a measurement script comparing concurrent table fill duration against the D55 baseline"
```

## Task 7: close the slice

**Files:**
- Modify: `docs/decisions.md`
- Modify: `docs/product/p6-report-design.md:282`

- [ ] **Step 1: Add the decision**

Immediately before editing, confirm the next free number:

```sh
grep -n '^## D' docs/decisions.md | head -3
```

Add a new entry at the very top of the decisions list (newest first), using the next free number (D60 as of this plan's writing, but re-check — D57 is currently claimed twice in the working tree per an earlier session, so do not assume D60 is still free):

```markdown
## D<NN> — Send table-fill cell extraction calls concurrently under a shared, adjustable limit

**Status:** Accepted. **Date:** <execution date>.

**Context:** `_table_fill` (backend/deixis/workflow/flow.py) read its planned sources one at a time and awaited each
`cell_extraction` model call; D55 measured 506–576 s for a 50-source fill. The report design note (P6, §2 decision
7, §4) requires this to become concurrent, independently of the report itself (§12 item 0), with a process-wide
adjustable limit shared with the future report run.

**Decision:** Add `ModelCallLimiter` (backend/deixis/workflow/concurrency.py): an adjustable, process-wide bound on
concurrent model calls with per-operation_key single-flight and a `reduce()` that halves the limit (floor 1) on a
rate-limited response. `_table_fill` submits its (source, column-chunk) jobs through it, respecting `_checkpoint`
before every submission; a pause, cancel or newer scope revision stops new submissions but lets calls already in
flight finish and record their own step, exactly as the existing sequential pause/cancel behavior already deferred
application of an in-flight result — only cancel/scope-revision defer it permanently, pause defers it to resume. A
rate-limited call is resent up to `MAX_RATE_LIMIT_MODEL_RETRIES = 2` times under the lowered limit before falling
back to today's pause. The limit is `Settings.model_concurrency` (env `DEIXIS_MODEL_CONCURRENCY`, default 6);
`FlowDeps.limiter` defaults to a limit of 1 so every existing test and call site that does not opt in keeps today's
exact sequential behavior. Measured duration for a 25-source fill at concurrency 6: <fill in from task 6>.

**Limits:** No adapter reports a structured rate-limit status; `is_rate_limited` (models/adapter.py) is a best-effort
text classifier, not a safety-relevant one — a miss simply keeps today's pause-on-failure behavior. Cell recheck
(`_cell_recheck`) is unchanged: it does not pass a limiter, so it stays sequential and unretried, matching this
slice's scope (table fill only). The report run (P6 slice 1) will share this same limiter; that plan was written
before this one and used placeholder names for it — reconcile `ModelCallLimiter`/`workflow/concurrency.py` there
before implementing slice 1.
```

- [ ] **Step 2: Update the design note's status line**

In `docs/product/p6-report-design.md`, the line for §12 item 0 currently reads (line 282):

```
0. **Eş zamanlı tablo doldurma (dilim 1'den önce, rapordan bağımsız).** `_table_fill` kaynak çağrılarını üst sınırlı eş zamanlı gönderir; kota hatasında sınır düşer; her kaynak adımı bugünkü gibi kendi kaydını yazar. Test: sahte adaptörle 12 kaynaklı doldurmada aynı anda açık çağrı sayısı sınırı aşmaz, bir kaynağın hatası diğerlerini durdurmaz, çıktı sıralı hâlle aynı. Ölçüm: D55'teki doldurma ile aynı kopyada süre karşılaştırması (506–576 s başlangıç).
```

Append a status clause to the end of that sentence (do not otherwise rewrite the paragraph — it stays the historical design statement):

```
 **Durum (<execution date>, D<NN>):** uygulandı. `workflow/concurrency.py::ModelCallLimiter`, `Settings.model_concurrency` (varsayılan 6, `DEIXIS_MODEL_CONCURRENCY`); ölçüm: <duration_seconds> s / 25 kaynak (bkz. docs/product/p6-slice0-fill-expectations.md).
```

- [ ] **Step 3: Final full-suite check and commit**

Run: `PYTHONPATH=backend uv run pytest -q`
Expected: all pass.

```bash
git add docs/decisions.md docs/product/p6-report-design.md
git commit -m "Record the D<NN> decision for concurrent table fill and update the P6 design note's status"
git push origin main
```

(Only push if the user has asked for this slice to be pushed now; otherwise stop after the commit and say so.)

## Self-review

Checked against the spec sections named above:

- **§2 karar 7** ("eş zamanlı model çağrısı... açık istek sayısı ayarlanabilir bir üst sınırla tutulur, başlangıç 6, kota hatasında sınır düşer ve kalanlar bekler, her adım kendi operation_key'ini... taşır, tablo doldurmanın eş zamanlı hâli rapordan bağımsızdır ve dilim 1'den önce yapılır"): covered by tasks 1, 2, 4; task 4's tests assert the limit is respected and rate limiting lowers it.
- **§4 "Eş zamanlılık kuralları"**: the five bullets (pause, cancel/scope-revision, same-key single-flight, crash/outcome_unknown, error classes) are covered by task 1 (single-flight), task 4 (`_fill_stopped`, `_checkpoint` placement, `_call_adapter`'s bounded resend), and by leaning on the existing, untouched `worker.py::recover()` for the crash case (task 4 does not change step/session recording, only when a task's *own* successful result gets applied, so `outcome_unknown` recovery is exactly as before).
- **§12.0**: the acceptance criteria in that paragraph (limit respected under a FakeAdapter with several sources, one source's failure does not stop the others, output matches the sequential path, duration measured against the D55 baseline) are each a named task-4/task-6 test or step.
- **§13 R7** (duration and cost measurement, expectations frozen before the run): task 6 follows this exactly, reusing the pattern from `docs/product/p6-slice1-report-expectations.md`.

Spec requirements I could not fully cover from code alone:

- The design note's "sınır 1 iken aynı hat aynı çıktıyı üretir" is verified by comparing final cell values and call counts (task 4, `test_the_limit_bounds_concurrent_calls_and_matches_sequential_output`), not by a byte-for-byte diff of every stored row (revision ids, timestamps and step_input ids necessarily differ between two separate library copies). This is the practical reading of "aynı çıktı" available without a much heavier test; flagged here rather than silently narrowed.
- §13's full R7 (queueing/quota wait time, token counts, cost) is only partly measurable from a single wall-clock run; task 6's script records step start/finish timestamps so a later pass can compute queueing time, but does not itself compute cost or token totals — that needs the same real-model harness `scripts/model_behavior/run_cases.py` already uses, which is out of this slice's scope.

## Açık noktalar

- **`MAX_ACTIVE_MODEL_CALLS = 1`** already exists, unused, in `domain/rules.py`. It looks like it could have been meant for exactly this feature but was never wired up, and its value (1) conflicts with the required default of 6. This plan does not touch or repurpose it; task 4 just notes it in a comment so the implementer does not silently reintroduce it as the concurrency default.
- **Rate-limit classification is heuristic.** `is_rate_limited` reads free text because no adapter (Codex, Claude Code, Gemini, DeepSeek) reports a structured rate-limit status for model calls today (only provider *search* rate limits are structured, in `providers/common.py`). A real Codex/Claude Code rate-limit message's exact wording was not verified against a live account in this planning pass; task 4's tests exercise the classifier only through `FakeAdapter.fail`. If real-model measurement (task 6) shows a genuine rate limit going unclassified, widen `RATE_LIMIT_ERROR_RE` rather than adding adapter-specific structured statuses in this slice.
- **`FlowDeps.limiter` default of 1 vs. production default of 6** is a deliberate asymmetry (kept every existing test passing without touching them) rather than something stated explicitly in the design note; it is the natural reading of "sınır 1 iken aynı hat aynı çıktıyı üretir" but is this plan's own choice about *where* that default lives.
- **Slice 1's placeholder note.** `docs/product/p6-slice1-report-run.md` (written before this plan, per its own text) says the report's concurrent turns will use "slice 0's limiter" with "placeholder names since slice 0 isn't written yet." This plan was told not to modify any file but its own, so that placeholder is not resolved here — whoever starts slice 1 should read this plan's Task 1 interface (`deixis.workflow.concurrency.ModelCallLimiter`, `.limit`, `.reduce()`, `.run(key, factory)`) and reconcile it there first.
- **Event ordering for the timeline.** `run_steps` rows are created the moment `_extraction` starts (inside the task, not at submission time), and under real concurrency (genuine network I/O) they are created in submission order because nothing before the first `await` really suspends; but `step_finished` events fire in completion order, which can now differ from source/table order. `EvidenceTable.tsx` was checked and renders fill progress from live cell/table state (`fill_estimate`, which cells have a value), not from the step event stream, so this does not need a frontend change for slice 0. `Transcript.tsx`'s run-timeline rendering for `table_fill` steps was not exhaustively checked line-by-line; if a future session sees a `table_fill` run's steps rendered out of table order there, it is this out-of-order-completion effect, not a bug in the data.
