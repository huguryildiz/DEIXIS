# SW dilim 31 — `legacy` arama akışının kaldırılması (plan)

**Tarih:** 30 Eylül 2026. **Karar:** D117 (sahip: "bizim sw default olmalı", "artık legacy vs olmamalı"). **Başlangıç:**
`389c344` (`sw` varsayılan, `legacy` yalnız `DEIXIS_SEARCH_WORKFLOW=legacy` ile seçilebilir). **Sıra:** P6 dilim 1'in P9
partisi `main`'e girdikten sonra, çünkü P9 `flow.py`, `domain/contracts.py`, `Transcript.tsx` ve `step-input.schema.json`
dosyalarına dokunuyor. **Plan denetimi:** Sol (`gpt-6-sol` · high) dokuz tur; 1–8. turların yüksek bulguları
belgeye işlendi, 9. tur "yüksek engel açısından uygulamaya hazır" (`.local/sw-slice31-plan-review/`).

## Hedef

Yeni hiçbir araştırma `legacy` keşif yolundan geçmez ve o yolun kodu, sözleşmeleri, yöntem satırları ve testleri
kaldırılır. Kütüphanede `legacy` olarak saklanmış araştırmalar açılmaya, geçmiş adımlarını göstermeye ve kendi derlemleri
üzerinde cevap vermeye devam eder.

## Eski `legacy` araştırmaları (Sol r1'den sonra)

İlke: **keşif yürütmesi kalkar, eski kaydı okuma kalır.** `legacy` diye saklanmış bir araştırma için:

1. **Açma ve geçmiş.** `views.py`'nin eski koşudan `run.plan`'ı (`model:search_plan` çıktısı) ve tarama notlarını
   (`model:screening`) üreten kodu, `Transcript.tsx`'in bunları çizen kısmı ve `labels.ts` eşlemeleri kalır.
   `queue_context` yalnız `sw` kapsamında çağrılmaya devam eder (eski araştırmada kuyruk sekmesi yok).
2. **Cevap.** Cevap koşusu eski araştırmada bugünkü gibi çalışır: `legacy` kapsamında saklı `search_plan`
   kavramlarını pasaj sıralamasında okuyan kod (`flow.py` ~4259) ve el yazımı pasaj kotası (`_criterion_phrases`,
   ~2485) **kalır**, "yalnız saklı `legacy` kaydını okur" yorumuyla. Kaldırılan yalnız keşif dalıdır.
3. **Eski araştırmada keşif tarafı kapalıdır (tek kural, tek koruma).** Backend'de tek bir koruma fonksiyonu
   (`legacy_research_read_only(scope)`), koşunun **saklı kapsam revizyonuna** bakar ve `legacy` ise 409
   `legacy_research_read_only` döner. **Keşif tarafı koşular** tam olarak `discovery`, `fulltext_fetch` ve `fulltext_adjudication`
   türleridir; öbür türler (`answer`, `pdf_collection`, `pdf_ocr`, `table_columns`, `table_fill`, `cell_recheck`,
   `research_title`, `report`) eski araştırmada açık kalır ve bu kuralın hiçbir yerine girmez. Uygulandığı yerler:
   `start_run` (yalnız bu üç tür; bugünkü `legacy` 422'leri bu 409'la değiştirilir, kaldırılmaz), `resume` (koşu bu
   üç türdense), `retry_failed` (bugün yalnız `discovery` kabul ediyor, `Store.queue_failed_search_retry`; eski
   araştırmada 409), kapsam düzenleme, `protocol-approval`, `term-suggestions`, `search-query-choice` ve
   keşfi kuyruğa alan başka her uç (uygulama sırasında `rg -n "start_run\|queue_run\|requeue" backend/deixis/api` ile
   listelenir, liste D'ye yazılır). Arayüz: iki "Search again" girişi (`ResearchView.tsx` ~500 ve ~574) ve kapsam
   düzenleme formu (`PdfReadiness.tsx` ~147) eski araştırmada gizlenir; yerlerinde tek satır: "Bu araştırma eski arama
   yöntemiyle yapıldı; yeniden aramak için yeni bir araştırma başlatın." `hasQueue` kapısı `sw`'ye bağlı **kalır**
   (backend `queue_context`'i `legacy` için reddediyor). **Koruma store katmanında da vardır (kapalı başarısızlık):** uçlar tek tek
   sayılsa da biri unutulmasın diye `Store`'da kapsam revizyonu açan her yol (`revise_scope` ~420, `/seed`'in kullandığı
   tohum yolu ~508–565 ve `INSERT INTO scope_revisions` yapan başka her fonksiyon; `create_research` hariç, o yeni
   araştırmayı hep `sw` açar) ve bir koşunun durumunu `queued` ya da `running` yapan her Store yolu: `create_run` ~654, `queue_failed_search_retry` ~727, sürdürme ve yeniden kuyruklama yolları ve durumu dinamik yazan `update_run` ~711 (işçi koşuyu bu yoldan `running` yapıyor, `worker.py` ~102). Uygulama, `runs` tablosunun `status` sütununa yazan her SQL'i (`rg -n "UPDATE runs|INSERT INTO runs" backend/deixis`) listeler ve her birinin ya korumadan geçtiğini ya da yalnız `cancelled` / `failed` / `completed` / `paused` gibi durduran durumlar yazdığını gösterir; bu liste D'ye yazılır. üç keşif türü için `legacy` kapsamında
   `LegacyResearchReadOnly` yükseltir; `create_run`'da bu denetim idempotency anahtarının erken dönüşünden **önce**
   çalışır (yoksa önceden kullanılmış bir `legacy` keşif anahtarı eski koşuyu 409'suz geri verirdi); API bunu 409 `legacy_research_read_only`'ye çevirir. Böylece `/seed` (PDF
   tohumu ekleme ya da değiştirme) eski araştırmada 409 döner ve arayüzdeki PDF seçimi girişi (`ResearchView.tsx` ~477)
   de öbür üç giriş gibi gizlenir; eski cevap `stale_scope` işareti almaz. Test: `/seed` ve arayüzdeki PDF seçimi eski
   araştırmada kapalı; store yolları doğrudan çağrıldığında da hata; önceden kullanılmış bir `legacy` keşif idempotency anahtarıyla `create_run` da, eski bir `discovery` koşusu için `queue_failed_search_retry` ve sürdürme yolu da, `update_run(..., status='running')` da doğrudan çağrıldığında hata verir; kuyruk API'leri eski araştırmada bugünkü reddini korur. Görünüm, bu kararı arayüze `research.read_only_reason`
   alanıyla verir; arayüz bayrağı kendisi çıkarmaz. (İlk öneri olan "yeni revizyon `sw` açılır" bırakıldı: kapsam
   düzenleme eski satırı `search_workflow` dahil kopyalıyor, seçimler araştırma düzeyinde ve yalnız `stale_scope`
   işaretleniyor; bunları `sw` kuyruğuna taşımak ayrı bir tasarım ister.)
4. **Yarım kalmış eski keşif koşuları.** Temizlik `Worker.recover`'dan **sonra**, ilk koşu seçilmeden önce çalışır
   (`recover` `running` ve `pause_requested` koşuları `paused` / `outcome_unknown` yapıyor; temizlik ondan önce koşsaydı
   bir `pause_requested` koşu `paused`'a düşer ve 409 yüzünden sürdürülemez hâlde kalırdı). `legacy` kapsamındaki
   keşif tarafı koşulardan (3. maddedeki üç tür; `pdf_ocr` ve öbürleri dokunulmaz) `queued`, `paused` ve `recover`'ın bıraktığı her yarım durumdakini (`running`,
   `pause_requested` dahil) `cancelled` yapar ve `reason: legacy_workflow_removed` olayını aynı işlemde yazar. Cevap
   koşuları bu kuralın dışındadır. Test: her dört başlangıç durumu için recover → temizlik sırası sonunda koşu
   `cancelled` ve olay yazılmış.
5. **Ayar.** `DEIXIS_SEARCH_WORKFLOW` artık okunmaz; `.env`'de kalırsa (hangi değerle olursa olsun) başlangıçta bir kez
   uyarı basılır, hata verilmez. Böylece `serve`, `backup` ve `restore` eski `.env` dosyalarıyla açılmaya devam eder.

## Kaldırılacaklar

Keşif ajanının haritasına göre (30 Eylül; satır numaraları `389c344` öncesi kod):

**İlke (6. turdan sonra):** yalnız `legacy` keşfini **yürüten** kod silinir. `legacy` kapsamında bir şeyi **reddeden,
atlayan ya da yalnız okuyan** her koruma ve dal kalır (kuyruk bağlamı reddi, seçim türetmeme kuralı, tam metin
kuyruklama korumaları, görünüm dalları); bunlar eski kaydı `sw` kararlarından korur.

- **`workflow/flow.py`:** `search_plan` model adımı ve açıklama isteği işleme (keşfin `legacy` dalı), `_search`
  (sayfasız tek istek), `screening` toplu adım döngüsü ve `apply_screening_proposal` çağrısı, `supported_tasks` içindeki
  `search_plan` ve `screening`. **Kalır:** `_skip_unsearchable` (`sw`'nin `_search_round`'u çağırıyor, ~2249),
  `_screening` (`sw` model taraması, `_overlap` kullanır), `_queue_fulltext_adjudication` / `person_reading_on` /
  `_queue_fulltext_fetch`'teki `legacy` erken dönüşleri, cevap tarafının eski kaydı okuyan dalları (2. madde).
- **`api/app.py`:** `effort_limits` dalları. `legacy` için `fulltext_fetch` / `fulltext_adjudication` retleri kalkmaz,
  3. maddedeki 409'a dönüşür.
- **Diğer modüller:** `protocol.py`'nin `legacy` gövde varyantları ve `rule_table_version: "legacy"` (yalnız yeni
  protokol yazımında; saklı protokolleri okuyan kod kalır); `domain/rules.py`'de `effort_limits`'in `legacy` dalı;
  `domain/skill.py`'nin görev eşlemesindeki `search_plan` ve `screening`; `store.apply_screening_proposal`; `create_research` /
  `scope.setdefault` varsayılanları (`sw` olur). **Kalır:** `providers/registry.py`'nin `legacy` dalı (`search_providers` ~131, eski araştırmanın sağlayıcı listesini
  görünüme ve Transcript'e verir); `queue.py`'nin `legacy` kuyruk bağlamı reddi (~95),
  `decisions.py`'nin eski araştırmada seçim türetmeme kuralı (~341), `prisma_s.py`, `waiting.py`, `expansion.py`,
  `views.py`'deki `legacy` dalları (okuma ya da ret); `SCREENING_BATCH` (`protocol.py` onu `sw` protokolüne yazıyor) ve
  `EffortBudget.max_candidates` (`flow.py` `sw` koşusunda da okuyor). Kalan her dal uygulama sırasında `rg` ile
  listelenir ve "okur / reddeder / atlar" diye etiketlenir; bu üçünden birine girmeyen dal silinir.
- **Ayar:** `Settings.search_workflow` alanı (yukarıdaki 5. madde).
- **Sözleşmeler ve yöntem paketi:** `search-plan.schema.json`, `screening-proposal.schema.json` ve
  `domain/contracts.py`'deki karşılıkları (`_check_search_plan` dahil); `ClarificationRequest` başka kullanıcısı yoksa;
  `methods/deixis-research/SKILL.md`'nin `search_plan` ve `screening` satırları ve `source-grounded-answer.md`'nin
  yalnız bu adımlara ait bölümleri. `skill_package_hash` değişir; yeni değer D'ye yazılır.
- **Arayüz:** `Home.tsx`'teki `sw` kapısı sadeleşir (yeni araştırma hep `sw`); `ResearchView.tsx`'te `hasQueue` ve
  `keyTerms` kapıları **kalır** (eski araştırma için), `api.ts` türü `'legacy' | 'sw'` olarak kalır (saklı kayıt). `Transcript.tsx` ve `labels.ts`'teki `model:search_plan` / `model:screening` eşlemeleri **kalır**: saklanmış
  eski koşular onlarla çizilir. PDF'le başlayan araştırmalarda kuyruk sekmesinin görünüp görünmeyeceği ayrıca denetlenir
  (`views.py` şimdi `hasQueue`'yu `sw`'ye bağlıyor).

## Kalacaklar

- Cevap koşusu (`_inspect`, `grounded_answer`, `answer_review`, sıralama), PDF koleksiyonu koşusu (`pdf_collection`),
  `uploaded_seed`. Bunlar bayrağı okumuyor.
- Veritabanı: `scope_revisions.search_workflow` sütunu kalır (migration'lar ileri yönlü; SQLite'ta varsayılanı değiştirmek
  tablo yeniden kurmayı gerektirir, gerekmez). Yeni migration yok, ancak bir test eski `legacy` satırının açıldığını
  doğrular.
- `providers/query_compiler.py`'deki `STRATEGIES = ("legacy", "compact_openalex_v1")`: bu bir sorgu derleme stratejisi,
  iş akışı bayrağı değil. Kapsam dışı; ayrıca sorulur.

## Testler

- Yalnız `legacy` davranışını sınayanlar silinir ya da `sw`'ye çevrilir: `tests/fakes.py`'nin `search_plan` /
  `screening` sahteleri, `test_api_flow.py`, `test_provider_flow.py`, `test_provider_roles.py`, `test_contracts.py`,
  `test_skill_package.py`, `test_effort_limits.py`, `test_protocol_record.py`, `test_search_paging.py`,
  `test_expansion_flow.py`, `test_backup.py`, `test_zotero.py` (D117'de `search_workflow="legacy"` sabitlenenler dahil).
  Her silinen testin sınadığı davranış ya `sw`'de karşılığıyla korunur ya da listede "artık yok" diye yazılır.
- Fikstürler: `tests/fixtures/research/{step-inputs,fake-outputs}.json`, `tests/model_behavior/cases.json`.
- Playwright: `tests/acceptance/fixture_server.py`'nin varsayılanı `sw`; `acceptance.spec.ts` (A–G) `sw` betikleriyle
  yeniden yazılır; `[rate-limit]`, `[model-down]`, `[invent-locator]` işaretleri `sw` yolunda da çalışmalı.
- Yeni testler (her biri ayrı): (a) saklı bir `legacy` araştırması API'de ve tarayıcıda (Playwright) açılır, plan ve
  tarama notları görünür; (b) cevap koşusu eski araştırmada saklı `search_plan` kavramlarıyla çalışır; (c) 3. maddedeki
  her uç (`start_run`'ın üç keşif türü, bu türlerden bir koşunun `resume`'u, `retry_failed`, kapsam düzenleme,
  `protocol-approval`, `term-suggestions`, `search-query-choice`) eski araştırmada 409 döner; cevap koşusunun
  `resume`'u ile `pdf_ocr` ve tablo/rapor koşuları eski araştırmada çalışır; `/seed` 409 döner; arayüzde dört giriş (iki "Search again", kapsam formu, PDF seçimi) gizli, açıklama satırı görünür, kuyruk sekmesi yok; (d) başlangıçta `queued`,
  `running` ve `paused` eski keşif koşuları `cancelled` olur ve olay aynı işlemde yazılır, (e)
  `.env`'de `DEIXIS_SEARCH_WORKFLOW=legacy` varken `serve`, `backup`, `restore` açılır ve uyarı basılır.
- Playwright `[model-down]` işareti şimdi yalnız kaldırılacak `screening` çağrısında hata üretiyor
  (`fixture_server.py` ~350); `sw`'nin bir model adımına taşınır.

## Belgeler

`CLAUDE.md` "Runs and steps" (keşif koşusunun `sw` adımları), `README.md`, gerekiyorsa `AGENTS.md`; D-kaydı (sıradaki
boş numara) kaldırmayı, yeni `skill_package_hash`'i ve silinen testlerin listesini yazar; satır 31 `sw-status.md`'ye.

## Denetimler

Tam pytest (bilinen bellek sınırı hatası dışında), `npm run build`, `npm run lint` (uyarı 17'yi geçmez), Playwright tam
koşu, `git diff --check`, yeni migration yok, `uv.lock` değişmez. Kalan her `legacy` geçişi `rg -n "legacy"` ile
listelenir ve her biri gerekçelendirilir (eski kayıt okuma, sorgu stratejisi, tarih belgeleri).

## Ölçülmeyecek

Bu dilim ürün kalitesini ölçmez; D114'ün tıp bulguları (daha az referans denemesine atıf, yüksek model oturumu sayısı)
geçerliliğini korur.
