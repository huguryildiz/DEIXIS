# P7 Bağlantı kapsamı: modelsiz doğrulama

Tarih: 3 Ekim 2026. Kapsam: `docs/product/implementation-plan.md:297` P7 çıkış koşulu. Ana matris bu worktree'nin `3b7bd31` koduna aittir. Sonraki dört kapanış ayrı bölümde gösterilir. Kod ve testler okundu. Bu düzeltmede test çalıştırılmadı; ağ, gerçek anahtar veya gerçek model kullanılmadı. Yalnız bu belge düzenlendi.

## Ölçüm ve kanıt sınırı

- İlk yazarın ilk koşusu 21 dosyada `-n 0` ile 436 geçiş ve bir hata bildirdi. Komut listesi tutulmadı; saklanmış log yoktur. Bildirilen `sqlite3.InterfaceError` ve aynı testin iki ayrı geçişi bu incelemede doğrulanmadı. Aralıklı hata veya SQLite yarışı tanısı konamaz.
- 3 Ekim D172 sonrası tam pytest sonucu: 8.525 geçti, 0 başarısız, 2 atlandı (`DEIXIS-pxall/docs/decisions.md:18`). Bu, D172'de kayıtlı sonuçtur; burada yeniden üretilmedi.
- Tablolar kod ve test okumasına dayanır. Testin varlığı burada başarılı yürütme anlamına gelmez.
- Bu incelemede canlı sağlayıcı ve model davranışı ölçülmedi. D172'nin canlı Claude CLI kontrolü kapanış bölümünde belirtilir. Sahte taşıma katmanı ve adaptörler canlı erişimi veya bilimsel doğruluğu kanıtlamaz.

Hücre değerleri: T = belirtilen davranış için deterministik test var; burada koşulmadı. K = kod var, incelenen testlerde bu yol gösterilmedi. Y = incelenen uygulamada yok. Ö = canlı davranış ölçülmedi. n/a = uygulanmaz. `backend/deixis/` altındaki yollar aşağıda tam yazılır.

## 1. Model bağlantıları

Dört adaptör var: `codex`, `claude`, `gemini`, `deepseek` (`backend/deixis/api/app.py:596`). Sözleşme `backend/deixis/models/adapter.py:71` içindeki `ModelAdapter` protokolüdür.

Ortak kurallar, tüm adaptörlere uygulanır:

- Model uyuşmazlığı: çıktı kaydedilir ama kullanılmaz. `resolved_model` farklıysa ve `requested_model_verified` yanlışsa adım `model_mismatch` ile durur (`backend/deixis/workflow/flow.py:5278`). Sahte adaptör testleri: `tests/test_api_flow.py:719`, `tests/test_lineage_flow.py:1090`, `tests/test_report_flow.py:504`.
- Kota/hız sınırı: `is_rate_limited` serbest hata metnine regex uygular. Kota ile geçici hız sınırını ayırmaz (`backend/deixis/models/adapter.py:62`). İş akışı yalnız limiter verilen çağrıları sınırlı sayıda yeniden gönderir (`backend/deixis/workflow/flow.py:5052`). Testler: `tests/test_adapter_rate_limit.py:8`, `tests/test_abstract_concurrency.py:217`.
- Bağlantı hazır değilse sağlık kontrolü `ready=False` ve `reason` döndürür (`backend/deixis/models/adapter.py:118`, `backend/deixis/models/gemini.py:70`). İş akışı `run_step()` çağırmadan `model_connection_not_ready` ile durur (`backend/deixis/workflow/flow.py:5107`). Doğrudan `run_step()` gönderim öncesi hatada `unavailable` ve `before_send` döndürebilir.
- Zaman aşımı yeniden göndermesi ayrı bir yoldur. Codex biçimindeki `client_timeout`, bütçe varsa `abstract_screening` ve `fulltext_adjudication` için bir kez yeniden gönderilir (`backend/deixis/workflow/flow.py:115`, `backend/deixis/workflow/flow.py:185`, `backend/deixis/workflow/flow.py:5268`). Başarılı toparlanma testi: `tests/test_adjudication_flow.py:724`.

| Bağlantı | Auth / anahtar yok | Model eşleşmesi | Kota / hız sınırı | Hata / zaman aşımı | Yeniden deneme |
|---|---|---|---|---|---|
| Codex | K: CLI yok, oturum yok (`backend/deixis/models/adapter.py:118`, `backend/deixis/models/adapter.py:151`) | K: `started.get("model")` (`backend/deixis/models/adapter.py:173`); ortak denetim T | K: metin regex'i; canlı hata Ö | K: sağlık, başlatma ve tur hataları (`backend/deixis/models/adapter.py:147`, `backend/deixis/models/adapter.py:170`, `backend/deixis/models/adapter.py:188`). Eşzamanlılık ve iptal T (`tests/test_codex_concurrency.py:87`) | Adaptörde yok. İş akışında limiter ve ayrı timeout yolu var |
| Claude | K: CLI ve oturum yok (`backend/deixis/models/claude.py:70`, `backend/deixis/models/claude.py:107`). Oturum açık yol T (`tests/test_claude_adapter.py:60`) | K: doğrulama bayrağı koşulsuz doğru (`backend/deixis/models/claude.py:186`). T: seçici, effort, kapalı fallback ve somut yanıt modeli (`tests/test_claude_adapter.py:79`, `tests/test_claude_adapter.py:85`); uyuşmazlık yolu gösterilmiyor | K: `is_error` → `failed` (`backend/deixis/models/claude.py:165`) | K: timeout ve SDK hatası (`backend/deixis/models/claude.py:172`, `backend/deixis/models/claude.py:176`). Araç sınırı T (`tests/test_claude_adapter.py:90`, `tests/test_claude_adapter.py:106`) | Adaptörde yok; ortak limiter yolu koşullu |
| Gemini | T: anahtarsız sağlık kontrolü ve reddedilen anahtar (`tests/test_gemini_adapter.py:26`, `tests/test_gemini_adapter.py:50`). Anahtarsız `run_step` K (`backend/deixis/models/gemini.py:111`) | T: `modelVersion` çıkarılır (`backend/deixis/models/gemini.py:132`, `tests/test_gemini_adapter.py:67`). Sürüm ekiyle eşitlik K; canlı biçim Ö | T: HTTP 429 → `failed` (`tests/test_gemini_adapter.py:79`) | T: kesik yanıt ve ReadTimeout (`tests/test_gemini_adapter.py:75`). ConnectError K (`backend/deixis/models/gemini.py:122`) | Sağlık kontrolünde bir transport tekrarı T (`tests/test_gemini_adapter.py:89`). `run_step` tekrarı yok; ortak limiter koşullu |
| DeepSeek | T: anahtarsız sağlık kontrolü (`tests/test_deepseek_adapter.py:13`). Anahtarsız `run_step` K (`backend/deixis/models/deepseek.py:89`). Anahtar sondasında 402 → `failed`, `no_credit` değil (`backend/deixis/credentials.py:165`, `backend/deixis/credentials.py:178`). `tests/test_settings_connections.py:86` OpenAI testidir | T: bildirilen model (`tests/test_deepseek_adapter.py:46`). K: eksik model istenen kimliğe çevrilir (`backend/deixis/models/deepseek.py:120`) | K: 429 regex'e girer; 402 `Insufficient Balance` girmez (`backend/deixis/models/deepseek.py:115`, `backend/deixis/models/adapter.py:57`) | K: `run_step` transport, HTTP ve bitiş hataları (`backend/deixis/models/deepseek.py:109`). Sağlık kontrolü transport yolları T (`tests/test_deepseek_adapter.py:54`, `tests/test_deepseek_adapter.py:68`) | Sağlık kontrolünde bir transport tekrarı T. `run_step` tekrarı yok; ortak limiter koşullu |

DeepSeek anahtar sondası model listesini ister; HTTP 402 `failed` döner (`backend/deixis/credentials.py:165`, `backend/deixis/credentials.py:178`). Başarılı/reddedilen DeepSeek anahtarı testi `tests/test_settings_connections.py:94`'tedir. Bakiyesiz anahtarı saklama testi `OPENAI_API_KEY` kullanır (`tests/test_settings_connections.py:86`); DeepSeek kapsamı sayılmaz. Uygulanmamış model bağlantılarının listesi bölüm 4'tedir.

## 2. Gömme (embedding) bağlantıları

Seçenekler: `gemini`, `builtin`, `openai`, `ollama`, `lm_studio`, `off` (`backend/deixis/documents/embeddings.py:38`). HTTP yolları `_send` ve `RateBudget` kullanır (`backend/deixis/documents/embeddings.py:54`, `backend/deixis/documents/embeddings.py:114`). `off` çağrı yapmayan seçimdir (`tests/test_settings_connections.py:232`).

| Bağlantı | Auth / anahtar yok | Model | Kota (429) | Hata / zaman aşımı |
|---|---|---|---|---|
| Yerleşik (builtin) | Anahtar gerekmez; kurulu değilse seçim reddedilir T (`tests/test_builtin_embedding_flow.py:210`) | T: kurulum ve dosya bütünlüğü (`tests/test_builtin_embedding_service.py:80`, `tests/test_builtin_embedding_runner.py:66`) | n/a: `_send` kullanılmaz (`backend/deixis/documents/embeddings.py:274`) | T: runner ölümü, timeout ve bozuk yanıt (`tests/test_builtin_embedding_runner.py:192`, `tests/test_builtin_embedding_runner.py:221`, `tests/test_builtin_embedding_runner.py:249`) |
| Ollama | T: anahtarsız başarılı gömme; URL portu 11434 (`tests/test_semantic_retrieval.py:127`, `tests/test_semantic_retrieval.py:139`) | T: gömme modeli ayrımı (`tests/test_settings_connections.py:168`) | K: ortak HTTP yolu (`backend/deixis/documents/embeddings.py:289`); sağlayıcıya özgü test gösterilmedi | K: kopma ve boyut denetimi; Ollama hata testi gösterilmedi |
| LM Studio | T: kurulu değil, durmuş, model listesi boş (`tests/test_settings_connections.py:170`, `tests/test_settings_connections.py:223`). Başarılı anahtarsız gömme K | K: ortak yerel model yolu (`backend/deixis/documents/embeddings.py:311`) | K: ortak HTTP yolu (`backend/deixis/documents/embeddings.py:289`) | K: gömme sırasında kopma ve boyut hatası gösterilmedi |
| OpenAI | T: anahtarsız seçim reddi (`tests/test_settings_connections.py:225`) | K: sabit model (`backend/deixis/documents/embeddings.py:308`) | K: ortak HTTP yolu (`backend/deixis/documents/embeddings.py:288`) | K: bu gömme yoluna özgü hata testi gösterilmedi |
| Gemini gömme | T: anahtarsız seçenek kullanılamaz (`tests/test_settings_connections.py:222`); doğrudan anahtar denetimi K (`backend/deixis/documents/embeddings.py:282`) | T: seçilen model (`tests/test_settings_connections.py:231`) | T: bekleme, bütçe, üç tekrar sonrası dördüncü 429, pause ve revizyon iptali (`tests/test_builtin_embedding_flow.py:272`, `tests/test_builtin_embedding_flow.py:284`, `tests/test_builtin_embedding_flow.py:299`, `tests/test_builtin_embedding_flow.py:321`, `tests/test_builtin_embedding_flow.py:331`) | T: ConnectError ve boyut uyuşmazlığı (`tests/test_builtin_embedding_flow.py:834`, `tests/test_builtin_embedding_flow.py:849`) |

Gemini bekleme süresini `Retry-After` başlığından veya gövdedeki `RetryInfo.retryDelay` alanından okur (`backend/deixis/documents/embeddings.py:94`). `Retry-Delay` başlığı yoktur. Dosya adı builtin olsa da yukarıdaki HTTP testleri Gemini'yi seçer (`tests/test_builtin_embedding_flow.py:274`, `tests/test_builtin_embedding_flow.py:333`).

## 3. Akademik sağlayıcılar

Kayıtta on bağlayıcı var (`backend/deixis/providers/registry.py:78`). Ortak `send` varsayılan olarak 429'da en çok iki tekrar yapar. Sayısal `Retry-After` için varsayılan tavan 10 saniyedir (`backend/deixis/providers/common.py:136`, `backend/deixis/providers/common.py:198`). arXiv bu tavanı 30 saniyeye çıkarır (`backend/deixis/providers/arxiv.py:32`, `backend/deixis/providers/arxiv.py:92`). Başlık yoksa yapılandırılmış backoff çarpanı kullanılır; bu dal tavan uygulamaz (`backend/deixis/providers/common.py:200`). Semantic Scholar başlangıçta 15 saniye bekler (`backend/deixis/providers/semantic_scholar.py:46`). SerpApi 429'u yeniden denemez (`tests/test_providers.py:317`).

Ortak katman 401/403'ü erişim moduna göre `entitlement_missing` veya `auth_required` sayar. Diğer 4xx için `rejected_not_executed`, 5xx için `after_send_unknown` verir. Bağlantı reddi `before_send`, yanıt zaman aşımı `timeout` olur (`backend/deixis/providers/common.py:171`, `backend/deixis/providers/common.py:189`).

IEEE Xplore, Scopus, CORE ve SerpApi anahtarsızken kayıt defterinde `not_configured` olur (`backend/deixis/providers/registry.py:68`, `backend/deixis/providers/registry.py:95`). Bu koruma sağlayıcı seçimine ve yönlendirmeye aittir (`tests/test_providers.py:410`, `tests/test_source_routing.py:78`, `backend/deixis/workflow/routing.py:46`). `3b7bd31` içindeki doğrudan `search()` çağrılarını korumaz. Sonraki düzeltme kapanış bölümündedir.

Arama adaptörü kapsamı aşağıdadır. `ALL` on sağlayıcıdır (`tests/test_providers.py:93`). Bu kapsam aktif DOI lookup yollarının yerine geçmez.

| Davranış | Sağlayıcı kapsamı ve test |
|---|---|
| Boş sonuç; 60 saniyelik `Retry-After`; 401 ve maskeleme | On adaptör (`tests/test_providers.py:328`, `tests/test_providers.py:370`, `tests/test_providers.py:377`) |
| 400, 503, bozuk gövde, bağlantı reddi, timeout; sonuç sınırı | On adaptör (`tests/test_providers.py:386`, `tests/test_providers.py:403`) |
| Kısa 429 tekrarı ve sayımı | SerpApi dışındaki dokuz adaptör (`tests/test_providers.py:333`) |
| İmleçsiz istek ve ilk sayfa | On adaptör (`tests/test_providers.py:460`, `tests/test_providers.py:470`) |
| Sonraki sayfa, kısa sayfa, son imleç, hatalı offset | Ayrı alt kümeler; SerpApi tek sayfa (`tests/test_providers.py:487`, `tests/test_providers.py:495`, `tests/test_providers.py:503`, `tests/test_providers.py:515`, `tests/test_providers.py:520`) |
| Boş HTTP 200 gövde → `parse_error` | On adaptör (`tests/test_p9_faults_providers.py:58`) |

P9 çalışma düzeyi timeout, bozuk JSON ve 5xx testleri ayrı kapsamdadır (`tests/test_p9_faults_providers.py:66`, `tests/test_p9_faults_providers.py:75`, `tests/test_p9_faults_providers.py:83`). `fault_run` dört sağlayıcılı fixture kullanır: OpenAlex, Semantic Scholar, bioRxiv ve SerpApi (`tests/test_p9_faults_providers.py:49`, `tests/test_search_parallelism.py:41`). On sağlayıcının tüm iş akışını doğruladığı söylenemez.

Sağlayıcıya özgü satırlar:

| Sağlayıcı | Auth / anahtar yok | Kota | Hata ve etkin yol |
|---|---|---|---|
| OpenAlex | İsteğe bağlı anahtar (`backend/deixis/providers/registry.py:79`); 401 ve maskeleme T | T: ortak arama 429 | T: ortak arama testleri; imleç sonu (`tests/test_providers.py:504`) |
| Semantic Scholar | İsteğe bağlı anahtar (`backend/deixis/providers/registry.py:83`) | T: ortak 429 ve pacing (`tests/test_semantic_scholar_pacing.py`) | T: ortak arama ve bulk testleri (`tests/test_s2_bulk.py`) |
| Crossref | Anahtarsız (`backend/deixis/providers/lookup.py:124`) | Arama 429 T; aktif lookup için ortak kod K | Aktif yol `lookup.crossref_work` (`backend/deixis/workflow/lookups.py:349`). DOI kodlama, 404 → `not_found`, 500 ve JATS testleri T (`tests/test_record_lookups.py:151`, `tests/test_record_lookups.py:158`, `tests/test_record_lookups.py:164`, `tests/test_record_lookups.py:169`) |
| arXiv | Anahtarsız (`backend/deixis/providers/registry.py:90`) | T: 406, 15/30 saniye backoff (`tests/test_providers.py:349`, `tests/test_providers.py:363`) | T: ortak arama testleri; sayfalar arası 3 saniye (`backend/deixis/providers/registry.py:90`) |
| bioRxiv | OpenAlex anahtarı isteğe bağlı (`backend/deixis/providers/registry.py:91`) | T: ortak arama 429 | T: ortak arama testleri; OpenAlex üzerinden arar |
| PubMed | `NCBI_API_KEY` isteğe bağlı (`backend/deixis/providers/registry.py:94`) | T: ortak arama 429 | T: ESearch ve EFetch (`tests/test_providers.py:170`); normal aramada iki istek |
| IEEE Xplore | Kayıtta anahtar zorunlu; doğrudan aramada boş anahtar gönderilir (`backend/deixis/providers/ieee_xplore.py:69`) | T: 403 `Over Queries` → `rate_limited` (`tests/test_providers.py:266`, `backend/deixis/providers/ieee_xplore.py:76`) | T: ortak arama ve kayıt testleri (`tests/test_providers.py:210`) |
| Scopus | Kayıtta `not_configured` T (`tests/test_providers.py:418`); doğrudan aramada boş başlık (`backend/deixis/providers/scopus.py:89`) | Arama 429 T; aktif lookup için ortak kod K | Aktif DOI yolu `lookup.scopus_abstract` (`backend/deixis/workflow/lookups.py:413`). COMPLETE, anahtar maskeleme, boş sonuç, 401 ve farklı DOI testleri T (`tests/test_record_lookups.py:555`, `tests/test_record_lookups.py:565`, `tests/test_record_lookups.py:573`). Yetki sondası T (`tests/test_providers.py:280`); canlı yetki Ö |
| CORE | Kayıtta anahtar zorunlu; doğrudan aramada boş Bearer (`backend/deixis/providers/core.py:77`) | T: ortak arama 429 | T: ortak arama; tam metin düşürülür (`tests/test_providers.py:296`) |
| SerpApi | Kayıtta anahtar zorunlu; doğrudan aramada boş anahtar (`backend/deixis/providers/serpapi.py:63`) | T: 429 tekrarlanmaz (`tests/test_providers.py:317`) | T: HTTP 200 içindeki `error`, sonuç yoksa ve "no results" ifadesi değilse başarısızlıktır; tanınan sonuçsuz yanıt `zero_results` döner (`backend/deixis/providers/serpapi.py:80`, `tests/test_providers.py:322`); snippet abstract sayılmaz (`tests/test_providers.py:308`) |

Bu sağlayıcılarda yanıtlayan model alanı n/a'dır. Crossref arama dışıdır (`backend/deixis/providers/registry.py:87`). Yeni SW sorgularında Scopus, CORE ve SerpApi arama dışıdır (`backend/deixis/providers/registry.py:97`). Eski discovery oluşturma ve sürdürme reddedilir (`tests/test_legacy_removal.py:122`, `tests/test_legacy_removal.py:126`). Ancak routing öncesinde saklanmış SW sorguları CORE/SerpApi'yi koruyabilir (`backend/deixis/providers/registry.py:133`). "Yalnız legacy arar" açıklaması güncel erişilebilirliği göstermez.

## 4. Uygulanmamış veya eksik, ürün kapsamında olanlar

1. Eklenti sözleşmesi uygulanmadı. Ürün bu sözleşmeyle kaynak eklemeyi öngörür (`docs/product/README.md:13`). Uygulama sabit `CONNECTORS` sözlüğü kullanır (`backend/deixis/providers/registry.py:78`). Yeni bağlayıcı yükleme noktası, şema ve sürüm kuralı gösterilmedi.
2. `/api/connections` şu dokuz model bağlantısını uygulanmamış olarak gösterir: `kimi`, `grok`, `copilot`, `glm`, `muse_spark`, `muse_glimmer`, `ollama`, `qwen`, `mistral` (`backend/deixis/api/app.py:800`). Her biri `ready=False` ve `Adapter not implemented in this version` gerekçesiyle listelenir. Hepsi bu kapsam listesine dahildir.
3. OpenAI ve LM Studio için de araştırma `ModelAdapter`'ı yok (`backend/deixis/api/app.py:596`). OpenAI, Ollama ve LM Studio gömme seçenekleridir (`backend/deixis/documents/embeddings.py:36`, `backend/deixis/documents/embeddings.py:38`). Gömme desteği model adaptörü desteği değildir.
4. Zotero içe aktarma yoludur (`backend/deixis/providers/zotero.py:1`). Google Scholar ayrı bağlayıcı değildir; SerpApi `google_scholar` motorunu kullanır (`backend/deixis/providers/serpapi.py:63`).

## Kapatılanlar (3 Ekim, D172)

D172 dört düzeltme grubunu kaydeder (`DEIXIS-pxall/docs/decisions.md:5`). Düzeltmeler komşu `/Users/huguryildiz/Documents/GitHub/DEIXIS-pxall` worktree'sinde okundu. Aşağıdaki `DEIXIS-pxall/...` referansları oraya aittir. Bu belge worktree'sinde D172 kodu yoktur. Yeni testler okundu, burada çalıştırılmadı.

1. Codex adaptör yolları için `tests/test_codex_adapter_paths.py` eklendi. Parametrelerle toplam 30 test vardır. CLI/oturum yokluğu, model kimliği, ortak uyuşmazlık reddi, RPC/transport hataları, timeout ve süreç çıkışı kapsanır (`DEIXIS-pxall/tests/test_codex_adapter_paths.py:80`, `DEIXIS-pxall/tests/test_codex_adapter_paths.py:125`, `DEIXIS-pxall/tests/test_codex_adapter_paths.py:178`, `DEIXIS-pxall/tests/test_codex_adapter_paths.py:194`). G3'ün test yokluğu kapandı.
2. Claude yanıtlayan modeli aynı oturumun kataloğundaki kimlikle karşılaştırır. `[1m]` gibi bağlam ekleri karşılaştırmada yok sayılır; bildirilen kimlik saklanır (`DEIXIS-pxall/backend/deixis/models/claude.py:33`, `DEIXIS-pxall/backend/deixis/models/claude.py:157`, `DEIXIS-pxall/backend/deixis/models/claude.py:206`). Uyuşmazlık, eksik kimlik ve hata yolları için testler vardır (`DEIXIS-pxall/tests/test_claude_adapter.py:160`, `DEIXIS-pxall/tests/test_claude_adapter.py:189`, `DEIXIS-pxall/tests/test_claude_adapter.py:209`, `DEIXIS-pxall/tests/test_claude_adapter.py:243`, `DEIXIS-pxall/tests/test_claude_adapter.py:255`). 3 Ekim canlı CLI kontrolünde `default` ve `sonnet` tamamlandı; model doğrulaması doğru döndü (`DEIXIS-pxall/docs/decisions.md:18`). Bu sonuç burada yeniden ölçülmedi. G2 ve G5'in belirtilen boşlukları kapandı.
3. DeepSeek `run_step` HTTP 402'yi kota olarak tanıtır. Eksik model kimliği `None` kalır. Geçersiz yanıt JSON'u `failed` ve `after_send_unknown` döner (`DEIXIS-pxall/backend/deixis/models/deepseek.py:116`, `DEIXIS-pxall/backend/deixis/models/deepseek.py:118`, `DEIXIS-pxall/backend/deixis/models/deepseek.py:125`). Anahtar, HTTP/transport, JSON, kimlik ve bitiş testleri G4'ün belirtilen yollarını kapsar (`DEIXIS-pxall/tests/test_deepseek_adapter.py:104`, `DEIXIS-pxall/tests/test_deepseek_adapter.py:133`, `DEIXIS-pxall/tests/test_deepseek_adapter.py:153`, `DEIXIS-pxall/tests/test_deepseek_adapter.py:167`, `DEIXIS-pxall/tests/test_deepseek_adapter.py:183`, `DEIXIS-pxall/tests/test_deepseek_adapter.py:199`). Bu düzeltme anahtar sondasının 402 durumunu `no_credit` yapmaz.
4. IEEE Xplore, Scopus, CORE ve SerpApi `search()` anahtarsızken hiçbir istek göndermeden `not_configured` ve `before_send` döner (`DEIXIS-pxall/backend/deixis/providers/ieee_xplore.py:67`, `DEIXIS-pxall/backend/deixis/providers/scopus.py:85`, `DEIXIS-pxall/backend/deixis/providers/core.py:73`, `DEIXIS-pxall/backend/deixis/providers/serpapi.py:60`). Dört sağlayıcı için `None` ve boş anahtar testi vardır (`DEIXIS-pxall/tests/test_providers.py:423`). G9'un doğrudan arama açığı kapandı.

## 5. Boşluklar

| No | Boşluk | Kanıt | Önem |
|---|---|---|---|
| G1 | Eklenti sözleşmesi uygulanmadı | `docs/product/README.md:13`, `backend/deixis/providers/registry.py:78` | Açık ürün işi |
| G2 | `3b7bd31` Claude bayrağı koşulsuz doğru | `backend/deixis/models/claude.py:186` | Kapalı (D172): oturum kataloğuyla doğrulama ve uyuşmazlık testleri var; canlı CLI kontrolü geçti |
| G3 | `3b7bd31` Codex auth/model/hata test boşluğu | `backend/deixis/models/adapter.py:170`, `tests/test_codex_concurrency.py:87` | Kapalı (D172): adaptör yolları için 30 test var; kayıtlı tam koşu 8.525/0, burada tekrarlanmadı |
| G4 | `3b7bd31` DeepSeek hata testleri, 402 ve eksik kimlik boşlukları | `backend/deixis/models/deepseek.py:115`, `backend/deixis/models/deepseek.py:120` | Kapalı (D172): belirtilen kod ve test boşlukları kapandı; anahtar sondası ayrı yoldur |
| G5 | `3b7bd31` Claude CLI/oturum/timeout/SDK test boşlukları | `backend/deixis/models/claude.py:70`, `backend/deixis/models/claude.py:172` | Kapalı (D172): hata yolu testleri var; kayıtlı tam koşu burada tekrarlanmadı |
| G6 | Model kota sınıflaması metin regex'idir; kota ve hız sınırı ayrılmaz | `backend/deixis/models/adapter.py:62` | Açık. Yeni sentetik mesaj testleri canlı hata biçimlerini kanıtlamaz. Limiter tekrarları ile timeout tekrarları ayrıdır |
| G7 | Gemini sürümlü `modelVersion` için eşitlik kuralı | `backend/deixis/models/gemini.py:132`, `backend/deixis/workflow/flow.py:5278`, `tests/test_gemini_adapter.py:67` | Çıkarma T; sürüm uyuşmazlığı için adaptör/iş akışı testi gösterilmedi. Kural deterministik testle sınanabilir; canlı çağrı gerçek biçimi ölçer |
| G8 | Sağlayıcı günlük kota ve geçici hız sınırı ortak sınıfa düşebilir | `backend/deixis/providers/common.py:180`, `backend/deixis/providers/ieee_xplore.py:76`, `tests/test_providers.py:317` | Açık. IEEE ve SerpApi özel davranışı tam ayrım sağlamaz |
| G9 | `3b7bd31` dört anahtarlı adaptör doğrudan boş anahtarla gönderir | Bölüm 3'te dört ayrı kod yolu | Kapalı (D172): IEEE anahtarsız çağrı boşluğu ve diğer üç sağlayıcı isteksiz `not_configured` korumasıyla kapandı |
| G10 | Canlı IEEE/Scopus/CORE/SerpApi erişimi ölçülmedi | Bölüm 3'ün sentetik testleri | Canlı kapsam Ö; test geçişi gerçek yetki veya yanıt biçimi değildir |
| G11 | Ollama/LM Studio kopma, 429 ve boyut hatası kapsamı gösterilmedi | `backend/deixis/documents/embeddings.py:114`, `backend/deixis/documents/embeddings.py:168`, `backend/deixis/documents/embeddings.py:289` | Açık. Gemini için ilgili testler var (`tests/test_builtin_embedding_flow.py:272`, `tests/test_builtin_embedding_flow.py:834`, `tests/test_builtin_embedding_flow.py:849`). LM Studio başarılı gömme yolu da gösterilmedi |
| G12 | Revizyon/429 testinde hata ve iki başarılı tekrar bildirildi | `tests/test_builtin_embedding_flow.py:331`; tam komut/log yok | Doğrulanmamış tarihsel rapor. Aralıklı hata veya yarış tanısı konulmadı |

## 6. Sonuç

P7 çıkış koşulu karşılanmış sayılmaz. Etkin yolların test kapsamı ve uygulanmamış bağlantılar ayrı listelidir. Eklenti sözleşmesi, Gemini sürüm eşitliği, yerel gömme yolları ve kota ayrımı açık kalır. D172'de G2–G5 ve G9 kapandı. Kod ve testler pxall'da okundu; kayıtlı tam pytest sonucu 8.525 geçiş, 0 hata ve 2 atlanan testtir. Bu worktree'ye aktarım ve testlerin yeniden yürütülmesi bu düzenlemenin kapsamı dışındadır. G7 deterministik uyuşmazlık testleriyle sınanabilir. Canlı çağrı sağlayıcı davranışını ölçer; koşulsuz doğrulama bayrağının güvenilirliğini kanıtlamaz.
