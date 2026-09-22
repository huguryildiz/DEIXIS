# SW dilim 13c — Efora göre toplama sınırı ve sağlayıcı bekleme kuralı: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; bu dilim ana planda yoktur). **Karar:** D88. **Önkoşul:** 13b (Crossref çıkmadan ölçüm anlamsız). **Tür:** Kur (ölçülmedi). **Uygulayan:** Opus · medium. **İnceleme:** toplu (13b + 13c + 13d).

**Sahibin kararı (22 Eylül 2026):** hedef süreler hızlı 5 dk, standart 10 dk, derin 15 dk. **Zaman sınırı konmaz**; toplanan kayıt sayısı ve sağlayıcı beklemesi efora göre kademelenir, süreler sonra ölçülür ve sabitler ölçüme göre ayarlanır.

**Goal:** Bugün üç efor da her sorguyu 2.000 kayda kadar sayfalıyor (`SW_READ_LIMIT`); efor yalnızca modelin kaç iş okuduğunu ayırıyor. Üçüncü koşuda 28 dakikanın ~20'si sağlayıcılarda geçti. Bu dilimden sonra: (1) sorgu başına okuma sınırı efora göre `{"quick": 400, "standard": 1000, "detailed": 2000}` (elle seçildi, ölçülmedi); (2) hız sınırı / zaman aşımı beklemesi efora göre: `quick` beklemez (429 alan sayfa ya da özet arama partisi o okumayı bitirir, kayıtlar `unread` / `abstract_not_found` sayılır), `standard` bugünkü sınırlı yeniden denemeyi bir kez yapar, `detailed` bugünkü gibi; (3) atlanan sağlayıcı arama ya da arama adımında `stop_reason` / `status` ile kaydedilir, sessiz olmaz; (4) protokol kaydının `thresholds.search_read` alanı efor değerlerini taşır.

**Architecture:** `domain/rules.py`: `SW_READ_LIMIT` → `SW_READ_LIMIT = {"quick": 400, "standard": 1000, "detailed": 2000}` ve `PROVIDER_WAIT = {"quick": 0, "standard": 1, "detailed": MAX_RATE_LIMIT_RETRIES}` (yeniden deneme sayısı). `flow` bu ikisini `scope["effort"]` ile okur (`_request_allowance`, `_stop_reason`, sayfalı okuma, `lookups.py`'nin parti döngüsü). `providers/common.py::request`'e `max_rate_limit_retries` parametresi (varsayılan bugünkü sabit; `legacy` istekleri aynı kalır).

## Global constraints

- `legacy` akış değişmez: tek sayfa, bugünkü yeniden deneme.
- Hiçbir kayıt silinmez; okunmayan sayılır (`unread_count`, dilim 04c).
- Sabitler tek yerde, adlı; protokol `thresholds`'a yazılır. Arayüzdeki derinlik açıklaması (`Home.tsx` `effortOptions`) dilim 20'nin plan notundaki gibi zaten yanlış; bu dilim yalnızca sayıları güncel sabitten türetir, metin tasarımına girmez.
- Süre ölçülmez (bu dilimde koşu yok). Ölçüm adımı dilimden sonra ayrı: üç efor × bir konu, Sonnet'e verilir, süreler `sw-status.md`'ye ve D88'in altına yazılır.
- Başlamadan kontrol et: D88 yazıldı; migration yok.

## Dosya yapısı

Değişecek: `backend/deixis/domain/rules.py`, `workflow/flow.py` (`_request_allowance`, `_stop_reason`, `_search_page`, `_discovery`), `workflow/lookups.py`, `workflow/protocol.py` (`thresholds.search_read`), `providers/common.py`, `apps/web/src/Home.tsx` (yalnızca sayı), `tests/test_search_paging.py`, `tests/test_lookups*.py`, yeni `tests/test_effort_limits.py`, `docs/decisions.md` (D88 Status), `sw-status.md`.

## Task 1: efora göre okuma sınırı

- [ ] **Tests first:** `quick` sorgusu 400'de `read_limit` ile durur ve `unread_count` doğru; `detailed` 2.000'de; `_request_allowance` efora göre küçülür; protokol kaydı efor değerini taşır; `legacy` tek sayfa.

## Task 2: efora göre bekleme

- [ ] **Tests first:** `quick`'te 429 alan sayfa `page_failed` ile okumayı bitirir, kayıtlar `unread` sayılır, koşu devam eder ve `completed` olur; `quick`'te 429 alan özet arama partisi `rate_limited` yazar, o partinin kayıtları `abstract_not_found`, sonraki parti denenir; `standard` bir kez bekler; `detailed` bugünkü sayı; `legacy` isteği aynı.

## Task 3: kapanış

- Tam pytest, build + lint (Home.tsx), D88 Status, satır 13c, tek commit, push.

## Ölçülmedi

Süreler; sınırların geri çağrıma etkisi; `quick`'te beklememenin kaç kaydı `abstract_not_found` bıraktığı. Ölçüm adımı: 13d'den sonra, üç efor, bir konu.
