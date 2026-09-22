# SW dilim 13d — Kod aşamasının hızı: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; bu dilim ana planda yoktur). **Karar:** yok (davranış değişmez). **Önkoşul:** 13 (koşuldu); 13a–13c'den bağımsız. **Tür:** Kur. **Uygulayan:** Opus · medium. **İnceleme:** toplu (13b + 13c + 13d).

**Goal:** Üçüncü duman koşusunda `code:abstract_stage` 177 sn, `code:criterion` 89 sn sürdü; ikisi de olay döngüsü iş parçacığında eşzamanlı koşuyor, bu sürede API yanıt veremiyor (yoklamalar ~25 sn'de bir yanıtlandı) ve dilim 13'ün duraklamasına zemin hazırladı. `research_view` `fe7c31d` ile 37 → 7,2 sn'ye indi; kalan 7 sn'nin ~2,3'ü `views.py`'deki sürüm sıralama döngüsü (her kayıt için bütün listeyi tarayan iç içe döngü). Bu dilimden sonra: aynı veritabanında `code:abstract_stage` ≤ 20 sn, `code:criterion` ≤ 15 sn, `research_view` ≤ 3 sn (hedef; ölçülür ve yazılır), **çıktı bayt bayt aynı** (adım çıktısı, `stage_decisions`, `selections`).

**Architecture:** Önce ölç, sonra değiştir. Uygulayan `.local/sw-smoke-2026-09-22/data-3/library.sqlite`'ın bir **kopyası** üzerinde (salt okunur açılır, kopyalanır) `cProfile` ile üç işlevi profiller ve ilk üç sıcak noktayı dilim satırına yazar. Bilinen adaylar: `_write_abstract_codes` her yazım için `decisions.current` + `decisions.record` + `store.source(svid)` ve iş başına `derive_selection` (binlerce kısa işlem); `views.research_view`'daki `ordered` döngüsü (O(n²)); `code:criterion`'daki sayım sorguları. Düzeltme yolu: araştırma genelinde birkaç sorguyla okuma, tek işlemde toplu yazma (`executemany`), `work_id` → kayıtlar sözlüğüyle sıralama. Yeni indeks gerekiyorsa migration `0048`.

## Global constraints

- **Davranış değişmez:** aynı girdiyle aynı `stage_decisions`, `selections`, adım çıktısı, olaylar. Kanıt: `tests/determinism_stages.py` kalıbıyla, düzeltmeden önce alınan çıktı sonrakiyle karşılaştırılır (test, sahte veriyle; gerçek veritabanı depoya girmez).
- Olay döngüsü kuralı korunur: yazılar kısa eşzamanlı işlemler, `await` yok. `asyncio.to_thread` ile arka plana alma **yapılmaz** (tek SQLite bağlantısı olay döngüsü iş parçacığında; store iş parçacığı güvenli değil).
- Canlı kütüphane ve 8765 açılmaz; `data-3` yalnızca kopyalanarak okunur.

## Dosya yapısı

Değişecek: `backend/deixis/workflow/flow.py` (`_abstract_code_stage`, `_write_abstract_codes`), `workflow/decisions.py` (toplu `record` / `derive_selection` yolu), `workflow/criterion.py` (sayım), `workflow/views.py` (sıralama), gerekirse `storage/migrations/0048_*.sql`, `tests/test_abstract_flow.py` (çıktı eşitliği), yeni `tests/test_code_stage_scaling.py` (sorgu sayısı kayıt sayısıyla büyümez; `tests/test_view_scaling.py` kalıbı), `sw-status.md`.

## Task 1: ölç

- Profil çıktıları `.local/sw-code-stage-2026-09-22/` altına; ilk üç sıcak nokta satıra.

## Task 2: düzelt, çıktı aynı kalarak

- [ ] **Tests first:** sorgu sayısı 30 ve 90 kayıtta aynı (izleme geri çağrısı); düzeltme öncesi/sonrası adım çıktısı ve karar satırları eşit; insan kararı atlanır, `HumanDecisionStands` yutulmaz (mevcut testler).

## Task 3: kapanış

- Aynı kopya veritabanında süreleri yeniden ölç ve satıra yaz (önce/sonra); tam pytest; tek commit; push.

## Ölçülmedi

Başka makine ve başka konu; `criterion` sayımının sağlayıcı payı (ağ) — bu dilim yalnızca yerel hesabı ölçer.
