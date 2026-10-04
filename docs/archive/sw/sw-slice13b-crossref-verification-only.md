# SW dilim 13b — Crossref aramadan çıkar, doğrulamada kalır: uygulama planı

**Tarih:** 22 Eylül 2026. **Durum:** yazıldı, uygulanmadı. **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; bu dilim ana planda yoktur). **Karar:** D87. **Önkoşul:** 13 (koşuldu); 13a'dan bağımsız. **Tür:** Kur (ölçülmedi). **Uygulayan:** Opus · medium. **İnceleme:** toplu (13b + 13c + 13d birlikte, `gpt-5.6-sol` · high).

**Sahibin kararı (22 Eylül 2026):** Crossref yalnızca elde DOI/künye varken doğrulama ve yayıncı bağlantısı için kullanılır; arama OpenAlex + Semantic Scholar ile gider. Yedek olarak arama ("öbürleri cevap vermezse Crossref") **kabul edilmedi** (D87'deki gerekçe).

**Goal:** Üçüncü duman koşusunda Crossref'in iki sorgusu 4.000 kayıt getirdi; 3.438'i başka sağlayıcının bulmadığı iş, 1.977'si özetsiz ve hepsi Semantic Scholar'ın hız sınırlı özet aramasına gitti (705 sn). Kod aşamasından sonra bu 3.438 işin 51'i aday oldu. Bu dilimden sonra `sw` keşfi Crossref'e sorgu derlemez; `record_lookup:crossref` (DOI'si bilinen kaydın künyesi ve bağlantıları) ve `documents/acquisition.py`'deki DOI denetimleri olduğu gibi kalır.

**Architecture:** `providers/registry.py::Connector`'a `searchable: bool = True`; Crossref `searchable=False`. `providers/query_compiler.py` (`compile_queries`, `compile_block_queries`) ve `flow._discovery`'nin sağlayıcı listesi `searchable` olmayanı atlar. `api/app.py::available_providers()` arama sağlayıcılarını verirken Crossref'i **arama** listesinden düşürür; bağlantı ayarları ekranında Crossref "doğrulama" rolüyle görünmeye devam eder. `legacy` akış: `search_plan` model adımına sunulan sağlayıcı listesi de `searchable` süzgecinden geçer (kural: `legacy` araştırmalar çalışmaya devam eder; Crossref'i adlayan eski bir plan çıktısı saklı adımdan okunur ve sürdürülen koşuda **yeniden aranmaz**, arama adımı `provider_not_searchable` ile `skipped` yazar).

## Global constraints

- Kayıt silinmez: mevcut araştırmaların Crossref'ten gelen kayıtları, `search_runs` satırları ve protokol kayıtları aynen kalır.
- `record_lookup:crossref`, `pdf_discovery` ve DOI doğrulama yolları **değişmez**; testleri değişmez.
- Ürün koduna sağlayıcı adına bağlı özel dal yazılmaz: süzgeç `Connector.searchable` üzerinden, `flow` sağlayıcı adı söylemez (dilim 05 kuralı).
- Arayüz: bağlantı listesinde Crossref'in rolü "künye doğrulama" olarak etiketlenir (`labels.ts` / `i18n.ts`); başka arayüz değişikliği yok.
- Başlamadan kontrol et: D87 yazıldı; migration yok.

## Dosya yapısı

Değişecek: `backend/deixis/providers/registry.py`, `providers/query_compiler.py`, `workflow/flow.py` (`_discovery` sağlayıcı listesi, arama adımının `skipped` yolu), `api/app.py` (`available_providers`, bağlantı görünümü `role`), `apps/web/src/{labels.ts,i18n.ts}` (rol etiketi), `tests/test_query_compiler.py` (varsa; yoksa `tests/test_provider_records.py`), yeni `tests/test_provider_roles.py`, `docs/decisions.md` (D87 Status), `sw-status.md`.

## Task 1: bağlayıcı rolü

- `Connector.searchable` (varsayılan `True`), Crossref `False`. `available_providers()` → aranabilirler; yeni `verification_providers()` → Crossref gibi olanlar (bağlantı görünümü için).

- [ ] **Tests first:** `available_providers()` Crossref'i içermez; bağlantı görünümü Crossref'i `role: "verification"` ile gösterir; öbür bağlayıcıların rolü `search`.

## Task 2: sorgu derleme ve keşif

- `compile_queries` / `compile_block_queries` `enabled_providers`'dan aranamayanı düşürür (çağıran değil, derleyici; `PLAIN_PROVIDERS` sabiti kalır, Semantic Scholar hâlâ düz sorgu alır).
- `flow._discovery`: sürdürülen bir koşunun saklı planı Crossref sorgusu taşıyorsa arama adımı `skipped` / `provider_not_searchable` yazar, koşu devam eder (D18 kalıbı).

- [ ] **Tests first:** `sw` keşfinde derlenen sorgularda Crossref yok, OpenAlex ve Semantic Scholar var; `legacy` planında sunulan sağlayıcı listesinde Crossref yok; saklı Crossref sorgusu taşıyan koşu sürdürülünce `skipped` yazar ve `completed` olur; `record_lookup:crossref` testleri değişmeden geçer.

## Task 3: kapanış

- Tam pytest, `npm run build && npm run lint`, D87 Status → implemented, satır 13b, tek commit, push.

## Ölçülmedi

Crossref'siz geri çağrım kaybı (yalnızca Crossref'in bulacağı işler); 13c'den sonraki ölçüm adımında aynı konu iki kez koşulup kod aşamasının tuttuğu adaylar karşılaştırılır.
