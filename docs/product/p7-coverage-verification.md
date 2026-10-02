# P7 Bağlantı kapsamı: modelsiz doğrulama

**Tarih:** 3 Ekim 2026. **Kapsam:** `docs/product/implementation-plan.md` satır 297'deki P7 çıkış koşulu. Her bağlantı için auth, model, kota ve hata satırları ayrı ayrı çıkarıldı. **Yöntem:** kod ve mevcut testler okundu, mevcut deterministik testler çalıştırıldı. Hiçbir yerde ağ, gerçek anahtar veya gerçek model kullanılmadı. Kodda ve testlerde değişiklik yapılmadı.

## Ne ölçüldü, ne yalnız okundu

- **Ölçüldü:** 21 test dosyası serial koşuldu (`-n 0`): 436 geçti, 1 kaldı. Kalan test `tests/test_builtin_embedding_flow.py::test_a_new_scope_revision_during_a_429_wait_cancels_the_run`. İlk koşuda `sqlite3.InterfaceError` verdi (`backend/deixis/workflow/store.py:764`). Aynı test tek başına iki kez geçti. Bu yüzden aralıklı (flaky) sayıyorum. Nedenini araştırmadım.
- **Yalnız okundu:** tablodaki "yalnız kodda" hücreleri. Kodda var, ama onu çalıştıran test yok.
- **Ölçülmedi:** gerçek sağlayıcı ve gerçek model davranışı. Testler sahte (fake) taşıma katmanı ve sahte adaptör kullanır. Geçen test iş akışı davranışını gösterir, canlı erişimi göstermez.

Hücre değerleri: **T** = testle kapalı, **K** = yalnız kodda var (test yok), **Y** = yok, **Ö** = ölçülmedi (gerçek çağrı gerekir).

## 1. Model bağlantıları

Dört adaptör var: `backend/deixis/api/app.py:596-601` (`codex`, `claude`, `gemini`, `deepseek`). Sözleşme `models/adapter.py` içindeki `ModelAdapter` protokolüdür.

Ortak kurallar, tüm adaptörlere uygulanır:

- **Model uyuşmazlığı:** `workflow/flow.py:5278`. Yanıtlayan model istenenle aynı değilse ve adaptör `requested_model_verified` demediyse çıktı kaydedilir ama kullanılmaz, çalışma `model_mismatch` ile durur. Testler sahte adaptörle: `tests/test_api_flow.py:710-719`, `tests/test_lineage_flow.py:1090`, `tests/test_report_flow.py:504`.
- **Kota/hız sınırı:** `is_rate_limited` (`models/adapter.py:57-68`) yalnız serbest metin hatasına regex uygular. Kodun kendi docstring'i "hiçbir adaptör yapılandırılmış kota durumu bildirmiyor" diyor. Yeniden gönderme yalnız sınırlayıcı (limiter) verilen adımlarda olur (`flow.py:5053`, `MAX_RATE_LIMIT_MODEL_RETRIES`). Testler: `tests/test_adapter_rate_limit.py:4-17` (regex), `tests/test_abstract_concurrency.py:217` (bir 429 sonrası yeniden gönderme).
- **Auth/anahtar yok:** her adaptörün `health()` ve `run_step()` sonucu `unavailable` + `delivery_class="before_send"` döner (Gemini ve DeepSeek: anahtar yoksa; Claude ve Codex: CLI yoksa).

| Bağlantı | Auth / anahtar yok | Model eşleşmesi | Kota / hız sınırı | Hata / zaman aşımı | Yeniden deneme |
|---|---|---|---|---|---|
| **Codex** (`models/adapter.py:85-224`) | K: `health` CLI yok (`:125`), oturum yok `signed_in` (`:151`) | K: `started["model"]` okunur (`:160`); ortak denetim sahte adaptörle T | K: yalnız metin regex'i; Codex'e özgü gerçek mesaj Y | K: `RpcError/TimeoutError/OSError` → `unavailable` veya `failed` (`:147`, `:188`); T yok. Eşzamanlılık ve iptal: T (`tests/test_codex_concurrency.py:87`) | Yok (yalnız limiter) |
| **Claude** (`models/claude.py`) | `health`: giriş yok → `ready=false` K (`:107-108`); CLI yok K (`:70`); oturum açık yol T (`tests/test_claude_adapter.py:60`) | **Atlanıyor:** `requested_model_verified=True` hep verilir (`:170`, `:186`), eşleşme denetimi devre dışı. `resolved_model` yalnız kaydedilir. T yalnız bayrağın değerini sınar (`:82`) | K: `is_error` sonucu → `failed` (`:165-171`); T yok | K: zaman aşımı (`:147`, `:172`), `ClaudeSDKError` (`:176`); T yok. Araç çağrısı yasağı T (`:90`, `:106`) | Yok |
| **Gemini** (`models/gemini.py`) | T: anahtar yoksa istek gitmez (`tests/test_gemini_adapter.py:26`); reddedilen anahtar mesajı T (`:50`) | K: `resolved_model=modelVersion` (`:~130`). Gerçek yanıttaki sürüm eki ölçülmedi (Ö) | T: HTTP 429 `failed`, hata metni "HTTP 429: quota" (`:78-80`) | T: kesik yanıt `MAX_TOKENS`, kayıp yanıt `after_send_unknown` (`:75-87`). `ConnectError` → `unavailable` K | T: `health` bir kez yeniden dener (`:89`); `run_step` yeniden denemez |
| **DeepSeek** (`models/deepseek.py`) | T: `health` anahtarsız istek atmaz (`tests/test_deepseek_adapter.py:13`); `run_step` anahtarsız yolu K | K: `data.model or requested_model` (`:120`). `or` yüzünden alan boşsa uyuşmazlık görünmez | K: 429 metni regex'e girer; **402 "Insufficient Balance" regex'te yok**. Ayar ekranı bakiyesiz anahtarı kabul eder: T (`tests/test_settings_connections.py:86`) | `run_step`: `ConnectError`, `HTTPError`, 200 dışı, `finish_reason != stop` hepsi K (`:109-126`); T yok. `health` iki transport hatası T (`:54-77`) | T: `health` bir kez yeniden dener; `run_step` yok |

Model olarak **uygulanmamış** olanlar: OpenAI, Ollama, LM Studio. Üçü yalnız gömme (embedding) bağlantısıdır (`documents/embeddings.py:36-38`, `credentials.py:41`). `ModelAdapter` yazılmadı.

## 2. Gömme (embedding) bağlantıları

Seçenekler `documents/embeddings.py:38`: `gemini`, `builtin`, `openai`, `ollama`, `lm_studio`, `off`. Hata sınıfı `EmbeddingError` (`:49`), 429 bütçesi `RateBudget` (`:54`), ortak gönderim `_send` (`:114`).

| Bağlantı | Auth / anahtar yok | Model | Kota (429) | Hata / zaman aşımı |
|---|---|---|---|---|
| **Yerleşik (builtin)** | Anahtar gerekmez. Kurulu değilse seçenek reddedilir: T (`tests/test_builtin_embedding_flow.py:210`) | T: kurulum, bütünlük, runner (`tests/test_builtin_embedding_service.py`, `tests/test_builtin_embedding_runner.py`) | T: 429 beklenir, bütçeyi aşan 429 beklenmez, üç 429 adımı kısmi bitirir, duraklatma ve yeni revizyon beklemeyi keser (`tests/test_builtin_embedding_flow.py:272-346`). Bir test (`:331`) tam koşuda bir kez düştü (yukarı bak) | T: runner testleri |
| **Ollama / LM Studio** | Anahtarsız yerel kullanım T (`tests/test_semantic_retrieval.py:125-140`); kurulu/çalışıyor/gömme modeli listesi T (`tests/test_settings_connections.py:155-183`); kullanılamayan sağlayıcı reddedilir T (`:218`) | T: model listesi gömme/gömme-değil ayrımıyla (`:168`) | K: aynı `_send` yolu. Ollama'ya özgü 429 testi Y | Sunucu yanıt vermiyor yolu: yalnız `running=False` raporu T (`:170`); gömme sırasında kopma Y. Boyut uyuşmazlığı `same_dimension` (`:168`) testlerde yalnız builtin dosyalarında geçiyor, Ollama ile Y |
| **OpenAI** | Anahtar yoksa seçenek reddedilir T (`tests/test_settings_connections.py:218`); anahtar testi `testable=True` (`credentials.py:41`) | K: sabit model adı | K: aynı `_send` yolu | K |
| **Gemini gömme** | Aynı anahtar, model bağlantısıyla ortak | K | T: `Retry-Delay` okunur (`tests/test_builtin_embedding_flow.py:284`) | K |

## 3. Akademik sağlayıcılar

Kayıt: `backend/deixis/providers/registry.py:78-105`, on bağlayıcı: `openalex`, `semantic_scholar`, `crossref` (yalnız doğrulama, aranmaz), `arxiv`, `biorxiv` (OpenAlex üzerinden), `pubmed`, `ieee_xplore`, `scopus`, `core`, `serpapi`. Ortak HTTP katmanı `providers/common.py:136-195` (`send`): 429'da en çok 2 yeniden deneme, bekleme 10 sn'yi aşarsa deneme yok (`:19-20`, `:181-185`), 401/403 → `entitlement_missing` (anahtarlıysa) veya `auth_required` (`:189-191`), 4xx `rejected_not_executed`, 5xx `after_send_unknown`, zaman aşımı `timeout`, bağlantı reddi `before_send`.

`not_configured`: `Connector.access_mode()` (`registry.py:68-71`). Anahtarı zorunlu olan dört bağlayıcı (`ieee_xplore`, `scopus`, `core`, `serpapi`) anahtarsızken aramaya girmez. Test: `tests/test_providers.py:410-420` (`available_providers`), `tests/test_source_routing.py:78-90` (yönlendirme). Çalışma düzeyi: `workflow/routing.py:46`.

Tüm on sağlayıcıya parametreli uygulanan testler (`tests/test_providers.py`, `ALL` listesi `:97`):

| Davranış | Test |
|---|---|
| Boş sonuç hata değil | `:328` |
| Kısa 429 yeniden denenir ve sayılır | `:334` |
| Uzun `retry-after` yeniden denenmez | `:370` |
| 401 sınıflandırılır, anahtar maskelenir | `:377` |
| 400, 503, bozuk gövde, bağlantı reddi, zaman aşımı sınıfları | `:386` |
| Sonuç sınırı sağlayıcı azamisine kırpılır | `:403` |
| Sayfalama: ilk sayfa, imleç, kısa sayfa, kod hatası | `:461-532` |
| Boş 200 gövde `parse_error` | `tests/test_p9_faults_providers.py:59` |
| Zaman aşımı, bozuk JSON, 5xx çalışmayı doğru nedenle durdurur | `:66`, `:75`, `:83` |

Sağlayıcıya özgü satırlar:

| Sağlayıcı | Auth / anahtar yok | Model alanı (yok) | Kota | Hata | Not |
|---|---|---|---|---|---|
| **openalex** | Anahtarsız çalışır; anahtar istenirse maskelenir T (`:377`) | n/a | T: ortak 429. Günlük bütçe tükenmesi bir kez gerçekte görüldü, `providers.env.example` notu; testle ayrı sınıflanmıyor | T ortak | İmleç sayfalama T (`:504`) |
| **semantic_scholar** | Anahtarsız çalışır | n/a | T: ortak 429; hız ayarlayıcı T (`tests/test_semantic_scholar_pacing.py`); toplu uç T (`tests/test_s2_bulk.py`) | T ortak | Offset en çok 1000 (`registry.py:83`) |
| **crossref** | Anahtarsız; yalnız doğrulama T (`tests/test_provider_roles.py:30-55`) | n/a | T ortak | T ortak | Aranmaz (D87) |
| **arxiv** | Anahtarsız | n/a | T: 406 hız sınırı sayılır ve yeniden denenir (`:349`), diğerlerinde düz hata (`:358`), 15/30 sn bekleme (`:363`) | T ortak | `page_gap=3.0` (`registry.py:90`) |
| **biorxiv** | OpenAlex'le aynı | n/a | T ortak | T ortak | OpenAlex ana makinesini paylaşır, istekler sıralı (D89) |
| **pubmed** | Anahtarsız; `NCBI_API_KEY` isteğe bağlı | n/a | T ortak | T: ESearch + EFetch kaydı (`:170`) | İki istek/arama (`requests_per_search=2`) |
| **ieee_xplore** | `not_configured` T (`:410-420`). `search()` kendisi anahtar denetlemez, boş `apikey` ile gider (`ieee_xplore.py:~66`); koruma yalnız kayıt defterinde | n/a | **T:** 403 + "Over Queries" başlığı → `rate_limited` (`:266`, `ieee_xplore.py:75-76`) | T ortak, kayıt T (`:210`) | Anahtar maskelenir T |
| **scopus** | `not_configured` T (`:418`) | n/a | T ortak 429 | T: gövdedeki `error` girdisi atlanır (`scopus.py:99`); COMPLETE görünüm yetki sondası 200/401/429/500/bağlantı T (`:280`) | Kuruluş ağı gerekir (D91); canlı yetki Ö |
| **core** | `not_configured` (kayıt: `key_required=True`) | n/a | T ortak 429 | T: tam metin düşürülür (`:296`) | Canlı Ö |
| **serpapi** | `not_configured` (kayıt: `key_required=True`) | n/a | **T:** 429 "arama bitti" yeniden denenmez (`:317`) | **T:** 200 içinde `error` boş sonuç sayılmaz, `failed` (`:322`) | Ücretli, `supplementary`, yalnız eski çalışma aratır |

## 4. Uygulanmamış veya eksik, ürün kapsamında olanlar

1. **Eklenti (connector) sözleşmesi uygulanmadı.** `docs/product/README.md:13` "kullanıcı tanımlı bir bağlayıcı sözleşmesiyle kaynak ekleyebilir" diyor. Kodda yalnız sabit `CONNECTORS` sözlüğü var (`registry.py:78`); yükleme noktası, şema, sürüm kuralı ve test yok. Yeni sağlayıcı eklemek kod değişikliğidir.
2. **Ollama, LM Studio, OpenAI model bağlantısı olarak yok.** Yalnız gömme (bölüm 2).
3. **Zotero** arama kaynağı değil, içe aktarma (`providers/zotero.py`); P7 listesinde değil, burada yalnız anıldı.
4. **Google Scholar** yalnız SerpApi üzerinden, tamamlayıcı (`supplementary`).

## 5. Boşluklar

| No | Boşluk | Kanıt | Önem |
|---|---|---|---|
| G1 | Eklenti sözleşmesi yok (4.1) | `registry.py:78` | P7 çıkış koşulunu doğrudan açık bırakır |
| G2 | Claude için model eşleşme denetimi fiilen kapalı: `requested_model_verified=True` her zaman | `claude.py:170,186`; `flow.py:5278` | Yanlış modelin çıktısı kullanılabilir. Alias doğru çözülüyor mu, yalnız gerçek çağrıyla bilinir (Ö) |
| G3 | Codex adaptörünün auth, model, hata yolları için birim test yok; yalnız eşzamanlılık ve iptal testi var | `tests/test_codex_concurrency.py` tek kapsam | Giriş yok, CLI yok, `RpcError`, zaman aşımı yolları yalnız kodda |
| G4 | DeepSeek `run_step` hata yolları testsiz: 200 dışı, zaman aşımı, `finish_reason`, anahtarsız | `deepseek.py:88-126` | Bakiye bitince 402 mesajı kota regex'ine girmez; bakiye bitişi "kota" değil genel hata olarak durur |
| G5 | Claude `is_error`, zaman aşımı, CLI yok, oturum yok testsiz | `claude.py:70,107,147,165` | Yalnız kodda |
| G6 | Model kotası yalnız serbest metin regex'iyle sınıflanır; adaptöre özgü gerçek hata metni örneği testte yok; kota ile hız sınırı ayrılmıyor | `adapter.py:57-68` | Yanlış negatif yalnız yardımcı olmayan duraklamaya yol açar (kod yorumu), yeniden gönderme yalnız limiter'lı adımlarda |
| G7 | Gemini `modelVersion` ile istenen model kimliği eşleşmeyebilir; gerçek yanıtta ölçülmedi | `gemini.py:~130`, `flow.py:5278` | Eşleşmezse her adım `model_mismatch` verir. Ö |
| G8 | Sağlayıcı kotası: günlük bütçe ile kısa hız sınırı çoğu sağlayıcıda ayrılmıyor; yalnız IEEE (403 başlığı) ve SerpApi (yeniden deneme yok) özel | `common.py:180-188`; commit 5b616e5 "quota-versus-rate-limit classifier" kapatılmamış diyor | Kullanıcıya "bekle" mi "bitti" mi dendiği belirsiz |
| G9 | `ieee_xplore.search()` anahtarsız çağrılırsa boş anahtarla ağa gider; koruma yalnız kayıt defterinde. Diğer üç anahtarlı modülü bu açıdan okumadım | `ieee_xplore.py:~66` | Doğrudan çağrı yolu testsiz |
| G10 | IEEE, Scopus, CORE, SerpApi canlı anahtarla ölçülmedi (kural gereği) | tüm tablo | Gerçek yanıt şekilleri sahte fixture'a dayanıyor |
| G11 | Ollama/LM Studio gömmede sunucu kopması, 429, boyut uyuşmazlığı testsiz | `embeddings.py:114,168` | Yalnız builtin için var |
| G12 | Aralıklı test: `test_a_new_scope_revision_during_a_429_wait_cancels_the_run` bir koşuda `sqlite3.InterfaceError` verdi, tek başına iki kez geçti | `store.py:764` | Paylaşılan SQLite bağlantısı ve iş parçacığı yarışı olabilir. Nedeni incelenmedi |

## 6. Sonuç

P7 çıkış koşulu **karşılanmadı**. Dört model bağlantısının ve on sağlayıcının matrisi çıkarıldı; sağlayıcı hata sınıflaması iyi testli, model adaptörleri zayıf testli. Eklenti sözleşmesi uygulanmadı, bu yüzden "ürün kapsamındaki uygulanmamış bağlantılar açık listeli" kısmı bu belgeyle (bölüm 4) kapanıyor ama "her etkin bağlantı ayrı doğrulanmış" kısmı G2 ile G7 için gerçek model çağrısı gerektiriyor ve burada yapılmadı.
