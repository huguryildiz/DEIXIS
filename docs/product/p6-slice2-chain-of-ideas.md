# P6 dilim 2 — Chain of Ideas: alan tabanı ve kanıta bağlı gelişim çizgileri

**Tarih:** 17 Eylül 2026. **Durum:** Taslak; sahibin yanıtı bekleniyor. Bu notta henüz kabul edilmiş bir tasarım yok; §18'deki sorular kapanmadan uygulamaya başlanmaz. Kod değişmedi.

**Kısaca:** Bu dilim, sahibin 14 Eylül 2026'da seçtiği sentez yöntemi olan Chain of Ideas'ın (Li ve ark. 2024) ilk iki adımını DEIXIS'e getirir: bir sorunun alanındaki temel çalışma, önemli derlemeler ve yakın çalışmalardan bir **alan tabanı** kurmak; sonra dahil edilen kaynakları kanıta bağlı **gelişim çizgileriyle** (kim hangi problemi ele aldı, neyi kurdu/değiştirdi, hangi belirsizliği bıraktı) birbirine bağlamak. Alan tabanı tamamen koddan gelir, model çağrısı gerekmez; sinyaller zaten saklı olan atıf sayısı (`cited_by_count`, migration 0005) ile taramanın kendi kararıdır. Çizgi düğümleri, P5'teki kanıt tablosunun üç yeni sütunudur ve `cell_extraction` adımıyla bugünkü gibi alıntılı doldurulur. Çizgi bağları ise yeni bir model adımıdır (`chain_links`): kod önce hangi sonraki çalışmanın hangi önceki çalışmayı metninde andığını bulur (yazar soyadı + yıl eşleştirmesiyle, tam-eşleşme garantisi olmadan), sonra yalnız bu aday çiftler modele verilir ve model her çift için ya bir ilişki türü ve destek yazar ya da "ilişki yok" der. Zincirler bağlı bileşen olarak koddan kurulur; bir zincirin ucunda kalan ve peşine düşülmemiş belirsizlik, P6 rapor tasarımının VI. bölümüne (`docs/product/p6-report-design.md`) dördüncü aday türü olarak koddan üretilir. Bu not, o rapor tasarımının §12'de bıraktığı yeri doldurur.

## 0. Chain of Ideas makalesi: ne okundu, hangi derinlikte

Makale doğrudan PDF olarak okunmadı; PDF içeriği ikili/sıkıştırılmış geldi ve metne çevrilemedi (`arxiv.org/pdf/2410.13185v5`). İki otomatik getirme yapıldı:

1. `arxiv.org/abs/2410.13185v5`: yalnız özet ve meta veri sayfası döndü, yöntem ayrıntısı yoktu.
2. `arxiv.org/html/2410.13185v5`: makalenin HTML tam metni bir özetleme aracıyla okunup soru odaklı bir özet olarak geri geldi (zincir kurma algoritması, genişletme/derinleştirme, novelty check, ajan mimarisi, sabit parametreler).

Bu, makalenin ham metnini satır satır okumakla aynı değildir: aktarılan alıntılar ("a CoI, represented as {I₋ₘ→⋯→I₀→⋯→Iₙ}...", "preset value or we encounter a milestone paper (>1,000 citations)" gibi) bir özetleme modelinin seçtiği parçalardır, benim doğrudan doğruladığım cümleler değildir. Aşağıdaki sayılar bu ikinci kaynaktan geliyor ve **uygulamadan önce makalenin resmî deposundan (`github.com/DAMO-NLP-SG/CoI-Agent`) ya da PDF'in kendisinden bir kez daha doğrulanmalı**: zincir başına en fazla 5 çalışma, konu başına 3 dal/zincir, çapa çalışma ileri yönde en az 1.000 atıflı bir "milestone paper"a ya da sabit uzunluğa ulaşınca durur, geriye doğru genişleme LLM'in referans listesini okuyup "en ilgili" önceki çalışmayı seçmesiyle olur, "widening" birden çok zincirden çıkan fikirlerin ikili karşılaştırmayla elenmesi, "deepening" tek zincir içinde adım adım konsolidasyon, novelty-checker hiç kaynak bulunamayınca `True` (özgün) döner ve bu iki `CoI-Agent` kod incelemesiyle zaten örtüşüyor (README'deki "CoI-Agent implementation inspection" bölümü, `agents.py#L467-L493`). Model olarak GPT-4o (ana) ve GPT-4o-mini (özetleme) kullanıldığı, bunun "çok ajanlı" değil sıralı rol oynayan tek-model-ailesi bir yürütme olduğu bildirildi.

Bu notun tasarımı, makalenin bu özetlenmiş okuması ile README/`research-methods.md`'deki daha önce yapılmış (ve zaten kabul edilmiş) kod incelemesine dayanıyor; makalenin ölçüm sonuçları (50 konu, insan değerlendirmesi vb.) hiç okunmadı ve bu notta kullanılmadı. **Devralınmayan** kısımlar zaten README'de karara bağlanmıştı ve bu not onları tekrar açmıyor: sabit zincir uzunluğu/dal sayısı, "kaynak yoksa özgündür" ikili novelty çıktısı, çok ajanlı mimari.

## 1. Kodda bugün olan

| Parça | Doğrulanan durum | Bu dilim için anlamı |
|---|---|---|
| `workflow/flow.py::_discovery` | `search_plan` model adımı → `query_compiler.compile_queries` derlenmiş sorguları üretir → sağlayıcı aramaları → `screening`. Kavramlar (`concepts`) `core` ve isteğe bağlı ailelerden oluşur; `adjacent_field` yalnız başka aile yokken kullanılır (D44). | Alan tabanı için "temel çalışma" ve "derleme" araması yeni bir model kavramı değil, koddan tetiklenen ek sorgu varyantlarıdır (§4.1). |
| `providers/query_compiler.py`, `query_rules.py` | Sorgular koddan derleniyor (D44); her sağlayıcının söz dizimi kuralı ayrı dosyada. `openalex_query_shape_issues` OpenAlex'in üç ve üzeri zorunlu terimi reddettiğini gösteriyor. | Sağlayıcıya özgü bir "review filtresi" ya da "atıf sırasına göre sırala" bugün **yok**; eklenmesi gerekiyor (§4.1). |
| `providers/openalex.py` | `SELECT` listesi `cited_by_count`'u zaten çekiyor (aynı çağrı, ek maliyet yok); `referenced_works` **çekilmiyor**. `ProviderRecord.identifiers` yalnız OpenAlex kaydının kendi `ids` alanından geliyor; başka sağlayıcıdan bulunan bir kaydın OpenAlex kimliği yok. | Atıf kenarı (kim kimi anıyor) eklemek "aynı çağrıya bir alan eklemek" kadar ucuz, ama yalnız her iki uçta da OpenAlex kökenli bir `source_version` varsa çözülebiliyor (§4.1). |
| `storage/migrations/0005_cited_by_count.sql` | `source_versions.cited_by_count`, `cited_by_count_at`; sağlayıcının bildirdiği sayı ve tarih, `source_version` başına (work başına değil). | Alan tabanının "atıf sayısı" temeli hazır; hangi tarihte, hangi sürüm için olduğu ayrıca gösterilmeli. |
| D45, D46, D48 (iş/sürüm aileleri) | Bir çalışmanın (`work`) birden çok `source_version`'ı (ön baskı, yayımlanmış, kullanıcı yüklemesi) olabilir; D48'den sonra yayımlanmış sürüm başı çeker, tarama ve seçim başa bağlı. `works.source_key` (D59) her işe kütüphane genelinde tek, sabit bir kısa anahtar veriyor (`Nakano13` gibi), `workflow/source_keys.py`. | Bir çizgi düğümü **iş** düzeyindedir (D48'in "preprint ve yayımlanmış hâli tek düğüm" kuralıyla örtüşüyor), ama kanıt tablosunun satırı **sürüm** düzeyinde (D37/D38: `(column, source_version)`). Düğüm kimliği pratikte tablo satırının anahtarı olan `source_version_id` üzerinden gider; iki sürümü olan bir iş, tabloda başının sürümüyle tek satırdır (D48), yani zaten tek düğüm olur. |
| P5 dilim 1 kanıt tablosu (`workflow/tables.py`, migration 0019/0020) | Sütun/hücre/revizyon/kanıt zinciri tamam: `evidence_cells`, `cell_revisions` (append-only, `model_fill`/`model_proposal`/`human_edit`/…), `cell_evidence_links` (yalnız o sürümün pasajı, tetikleyiciyle denetlenir). `cell_extraction` adımı kaynak başına bir çağrı yapar, 8 sütuna kadar birlikte. | Çizgi düğüm hücreleri (problem/kurulan-değişen/bırakılan belirsizlik) bu makineyi aynen kullanır; yeni tablo veya yeni revizyon türü gerekmez. |
| `domain/contracts.py::locate_anchor`, `_check_cells`, `_passages_quoting` | Alıntı, verilen pasajın metninde birebir/normalize/bulanık aranıyor; bulunamayan alıntı tek onarıma gidiyor. `_passages_quoting` aynı alıntının başka pasajda geçtiğini bulup onarım mesajına ekliyor. | Çizgi bağının "sonraki çalışmanın pasajında önceki çalışmayı andığı" kuralı aynı `locate_anchor` mekanizmasıyla denetlenebilir; yeni bir anchor türü gerekmez. |
| `domain/skill.py::RUNTIME_FILES`, `package_hash` | Görev türü → yüklenen dosya listesi eşlemesi burada; her görev `SKILL.md` + kendi referans dosyasını (bazen phrasebank) alır. Hash yalnız `RUNTIME_FILES`'ta adı geçen dosyalardan hesaplanıyor. | `chain_links` yeni bir `task_type` olarak buraya eklenir; `references/synthesis.md` yeni dosya olarak pakete girer ve hash değişir (T13). |
| `methods/deixis-research/SKILL.md` | Bugün açıkça yasaklıyor: "Literature synthesis across idea chains… are **not available**… do not offer them as claims, not even as `analyst_inference`; name them in `unanswered_aspects` instead." | Bu dilim bu yasağı **kaldırmaz**, daraltır: yalnız `chain_links` ve ilgili rapor bölümleri (III, VI, VII) için açılır; sıradan `grounded_answer` için yasak aynen kalır (rapor tasarımı §7'nin VI/VII gevşetmesiyle aynı örüntü). |
| `methods/deixis-research/references/evidence-table.md` | Hücre durumları (`value`/`unknown`/`not_applicable`/`not_found_in_inspected_scope`), dört biçim (`choice`/`number_unit`/`yes_no`/`text`, 500 karakter), alıntı kuralı, `passage_scope`, `text_source` (`text_layer`/`marker`/`ocr`) etiketi. | Üç yeni sütun (`text` biçiminde) bu dosyanın kapsamına aynen girer; yeni bir talimat dosyası gerekmez, `synthesis.md`'de yalnız sütunların adları ve amacı anlatılır. |
| `contracts/research/step-input.schema.json`, `evidence-cell-draft.schema.json`, `grounded-answer-draft.schema.json`, `common.schema.json` | Kimlik desenleri (`srv_`, `psg_`, `col_`, `cel_`…), zarf alanları (`step_input_id`, `scope_revision`, `skill_package_hash`), `extraction_target`/`passage_scope`, `citation_anchors` deseni burada. | Yeni şema (`chain-links-draft.schema.json`) ve `step-input.schema.json`'a `chain_target` eklenmesi bu kalıpları birebir izler (§8). |
| `docs/product/p6-report-design.md` §3, §6, §7, §12 | Rapor iskeleti kabul edildi (kod değişmedi): III "Background and Taxonomy", VI "Candidate Unanswered Aspects" (üç tür: `stated_limitation`, `conflicting_evidence`, `corpus_absence`; `report_gaps.kind` **kapalı liste değil**), VII "Future Directions". §12 madde 2 bu dilimi tanımlıyor: III'e "alanın gelişimi" alt bölümü, VI'ya dördüncü aday türü, VII'nin çizgilerden türemesi, çizgi görünümü. | Bu not, o notun bıraktığı boşluğu dolduruyor; rapor çalışması (dilim 1) henüz kodda yok, bu yüzden §15'te bağımlılık ayrıca yazıldı. |
| `docs/methods/domain-example.md` Task 1 | Alan tabanı için istenen ayrıntı: tam atıf, DOI, yıl, atıf sayısı kaynağı, önemin gerekçesi, sistem/mekanizma, matematiksel formülasyon, gösterilen bulgular, sınırlamalar, önerilen gelecek çalışma, her sınırlama için tam PDF sayfası/bölümü. "En ünlü" bir olgu değildir; seçim atıf sayısı, kurucu etki, derleme sıklığı ya da doğrudan uygunluktan hangisine dayandığını söylemelidir. | Bu, §4.1'deki `basis_json` alanlarının doğrudan kaynağı. |
| `AGENTS.md`, `.impeccable.md` | "Never overstate", kanıt sınırlarını ayrı tut, tek ana ajan, çok ajanlı sistem yok, kullanıcı seçimi model önerisinden üstün, PDF/pasaj kaynak sınırları. Arayüz: pill yalnız kısa durum için, hiyerarşi düz, hareket yalnız canlı işi gösterir. | Çizgi görünümü ve bağ düzenlemesi bu kurallara tabidir (§6.6). |

## 2. Senaryolar

### S1. Alan tabanı hesaplanır

Kullanıcı bir rapor ya da çizgi görünümü ister (ya da §18 soru 3'ün cevabına göre discovery ile otomatik başlar). Kod, arama planının çekirdek kavramıyla iki ek sorgu varyantı dener (atıf sırasına göre, review filtresiyle; §4.1), sonra dahil edilen ve taranan kayıtlar üzerinden dört yuvaya (`foundational`, `review`, `close_primary`, `close_adjacent`) aday listeler; her adaya en az bir `basis` (atıf sayısı + tarih, korpus içi atıf sıklığı, çekirdek sorgudaki sıra, taramanın kendi include kararı) iliştirir. Model çağrısı yoktur. Sonuç, evidence tablosunun üstünde ayrı bir "Field baseline" bölümü olarak görünür; her satırın yanında hangi temelle seçildiği yazar.

### S2. Düğüm hücreleri doldurulur

Kullanıcı ya da rapor akışı üç yeni sütunu ("problem addressed", "established or changed", "uncertainty left") tabloya ekler (mevcut `table_columns`/`add_column` akışıyla, model önerisi ya da kullanıcı eklemesi). `cell_fill` bugünkü gibi çalışır; her hücre alıntılıdır, okuma derinliği ayrı görünür.

### S3. Çizgi bağları önerilir

Kullanıcı "Find development links" der (ya da rapor akışı otomatik çağırır). Kod önce her tam metinli, dahil edilmiş sonraki-çalışma için pasajlarını tarar ve önceki çalışmaların yazar soyadı + yıl (veya soyadı yoksa başlık sözcüğü) örüntüsünü arar; eşleşen her çift "aday" olur. `chain_links` adımı, sonraki çalışma başına bir çağrıyla, yalnız o çalışmanın adaylarını alır ve her biri için ya bir ilişki (tür, ne değişti, destek türü, alıntı) ya da "ilişki yok" döner. Kod, alıntının gerçekten sonraki çalışmanın pasajında bulunduğunu, versiyonların tekilleştiğini, yıl sırasının makul olduğunu ve döngü oluşmadığını denetler.

### S4. Zincirler kurulur, uç belirsizlikler bulunur

Kod, kabul edilen bağları bağlı bileşenlere ayırır; dallanma noktaları ve çapraz bağlar korunur, izole kalan işler "yerleştirilemedi" listesinde görünür. Bir düğümün "bırakılan belirsizlik" hücresi varsa ve hiçbir giden bağ `continues_predecessor_uncertainty` işaretini taşımıyorsa (yalnız tam metinli düğümler için), bu bir "zincir ucu belirsizliği" adayı olur.

### S5. Rapor bunları kullanır

Rapor (dilim 1) çalıştığında III bir "alanın gelişimi" alt bölümü yazar (yalnız kabul edilmiş bağlardan), VI zincir ucu belirsizliklerini dördüncü aday türü olarak listeler, VII bu adaylardan yön türetir.

### S6. İnsan bir bağı düzeltir

Kullanıcı yanlış bir bağı siler, türünü değiştirir ya da alıntısız yeni bir bağ ekler (§18 soru 5). Bu düzenleme, hücre düzenlemesi gibi (D37) kalıcıdır ve sonraki `chain_links` çalışması onu ezmez; yalnız yeni bir öneri üretir.

## 3. Kurallar (devralınan, pazarlıksız)

- Bir bağ hiçbir zaman yalnız kronolojiden ya da yalnız bir atıftan **türetilmez**. Her bağ ya kaynaklı destektir (genelde sonraki çalışmanın öncekini anlattığı bir pasaj) ya da açıkça "analist çıkarımı" etiketlidir.
- Rakip dallar ve çapraz bağlar korunur; tek zorlanmış çizgi yanlıştır.
- Zincir ve aday sayısı soruya, kapsama ve bütçeye göre ölçeklenir; sabit sayı yoktur (CoI-Agent'ın sabit zincir uzunluğu ve fikir sayısı devralınmaz).
- CoI-Agent'ın ikili novelty çıktısı ve "kaynak yoksa özgündür" davranışı devralınmaz.
- Bir işin ön baskısı ve yayımlanmış hâli tek düğümdür (D48 ile zaten tutarlı).
- Okuma derinliği görünür kalır; bir özet, "yöntemde ne değişti" gibi ayrıntılı bir hücreyi destekleyemez.
- Tek ana ajan; model araçsız çalışır (mevcut mimari kısıtı).
- Farklı deney koşullarında ters sonuçlar, hizalanmadan çelişki sayılmaz (T11); bu, `corrects_or_contradicts` ilişkisinin `what_changed` alanında koşul farkını açıkça yazmasını gerektirir (§10).

## 4. Tasarım kararları

Görevin önerdiği altı maddelik ayrışmayı aşağıda madde madde değerlendirdim; çoğunu benimsiyorum, üç yerde koddan gelen somut bir nedenle daralttım ya da değiştirdim.

### 4.1 Alan tabanı — benimsendi, mekanizma değiştirildi

Önerilen taslak "arama planına ek bir kavram ailesi" öneriyordu. Bunun yerine **modelin arama planına dokunmadan, koddan tetiklenen iki ek sorgu varyantı** öneriyorum, çünkü D44'ten beri sorgu metnini model değil kod yazıyor; yeni bir kavram ailesi eklemek modelin zaten iyi çalışan çekirdek/aile ayrımına yeni bir serbest alan sokar ve `search-plan.schema.json`'ı (v2) tekrar sürümlemeyi gerektirir. Bunun yerine:

1. **`core_by_citation`**: `query_compiler`'ın zaten ürettiği çekirdek-yalnız sorgu, OpenAlex'e `sort=cited_by_count:desc` parametresiyle gönderilir (yalnız OpenAlex; öteki sağlayıcılarda düz sırayla kalır, D30'daki "Most relevant" sıralamasına dokunmadan).
2. **`core_reviews`**: aynı çekirdek sorgu, OpenAlex'e bir `review` türü filtresiyle gönderilir. **Doğrulanmadı:** OpenAlex'in `type` alanının bir `review` değeri taşıyıp taşımadığı bu oturumda canlı bir istekle kontrol edilmedi; uygulamadan önce doğrulanmalı, yoksa bu varyant atlanır ve derleme sıklığı sinyaline daha çok yaslanılır.

Bu iki varyant `query_rules.py`'ye değil `flow.py::_discovery`'ye eklenir (sorgu metni değişmiyor, yalnız istek parametresi), `openalex.py::search_works`'ün zaten aldığı `works_filter` parametresi kullanılır.

**Atıf kenarı bulgusu:** `openalex.py`'nin `SELECT` listesi `referenced_works`'ü çekmiyor; eklemek aynı isteğe bir alan eklemekten ibarettir, **ek bir API çağrısı gerektirmez**. Ama bir kenarı ("A, B'yi anıyor") kütüphanedeki başka bir kayda bağlamak için B'nin OpenAlex kimliğinin bilinmesi gerekir; bu yalnız B de OpenAlex üzerinden bulunmuşsa (`provider_record_id`'si OpenAlex kimliğidir) mümkündür. Başka sağlayıcıdan (Crossref, Semantic Scholar…) bulunan bir kayıt için `identifiers` sözlüğünde OpenAlex kimliği yoktur (`providers/common.py::ProviderRecord`); bu kenarları çözmek ek bir toplu OpenAlex arama gerektirir ki bu ek maliyettir. Öneri: yalnız **her iki ucu da OpenAlex kökenli** olan kenarları hesapla (ek çağrı yok), ötekini "çözülemedi" bırak.

Kod, hiçbir model çağrısı yapmadan dört yuvaya aday atar ve her birine gerekçesini yazar (domain-example.md Task 1'in istediği gibi, atıf sayısı ile "kurucu etki"yi karıştırmadan):

| Yuva | Sinyal(ler) | `basis_json` örneği |
|---|---|---|
| `foundational` | `cited_by_count` en yüksek olan(lar) (kendi `source_version`'ında, D48'in baş sürümünde) | `{"kind": "citation_count", "count": 812, "provider": "openalex", "at": "2026-09-17"}` |
| `review` | tür `review` sorgu varyantından gelen ve taramada dahil edilen | `{"kind": "review_query_match"}, {"kind": "citation_count", ...}` |
| `close_primary` / `close_adjacent` | taramanın kendi include kararı + çekirdek sorgudaki sıra (BM25/embedding, D30) | `{"kind": "screening_included"}, {"kind": "core_query_rank", "rank": 2}` |
| (genel, edinilebiliyorsa) | korpus içi atıf sıklığı: kaç dahil iş bunu `referenced_works`'ünde anıyor | `{"kind": "corpus_citation_frequency", "count": 4, "denominator": 9, "resolved": "openalex_only"}` |

Hiçbir yuva "en ünlü/en önemli" diye tek bir cümleye indirgenmez; ekranda her zaman en az bir `basis` gösterilir. Bu, domain-example.md'nin "Do not treat 'most famous paper' as an objective fact" kuralını koda bağlar.

### 4.2 Çizgi düğümleri — benimsendi: sıradan, kullanıcı görünür tablo sütunları

Ayrı bir sistem tablosu değil, **P5'in kanıt tablosunun üç sıradan sütunu** olarak öneriyorum: `problem_addressed`, `established_or_changed`, `uncertainty_left` (üçü de `answer_format: text`, 500 karakter). Nedeni: `evidence_cells`/`cell_revisions`/`cell_evidence_links` zaten append-only revizyon, insan düzenlemesi koruma, `cell_recheck` ve alıntı doğrulamasının hepsini yapıyor (D37/D38); ayrı bir sistem tablosu bunların hepsini ikinci kez inşa etmek demektir ve D37'nin "model yalnız boş hücreyi doldurur, insan üstündür" kuralından fayda görmez hale gelirdi. Bedel: bu üç sütun tabloda **kullanıcıya görünür** olur (report tasarımının IV. bölümü gibi), bu da "zincir muhasebesi" ile "kullanıcının kendi kanıt tablosu" görsel olarak karışabilir. Bunu bir sahip sorusu yaptım (§18 soru 1), çünkü karşı örnek de var: kullanıcı kendi sütunlarını eklemişse tabloya üç "sistem" sütunu daha binmesi kalabalık olabilir.

`cell_extraction` adımına yeni bir şema gerekmez; `evidence-cell-draft.schema.json` zaten `text` biçimini destekliyor. `references/evidence-table.md`'ye yeni bir talimat cümlesi eklenmez; `references/synthesis.md` (§6) bu üç sütunun **adlarını ve amacını** tanımlar, doldurma kuralı zaten evidence-table.md'de var.

### 4.3 Çizgi bağları — benimsendi, aday bulma adımı netleştirildi

Yeni bir model adımı (`chain_links`) doğru karar; ama "kaynak içi atıf eşleştirme güvenilmez" uyarısını ciddiye alıp **aday bulmayı koda, ilişki yargısını modele** ayırıyorum:

1. **Kod (deterministik, model yok):** her dahil, tam metinli sonraki-çalışma için, önceki çalışmaların `source_keys.py::family_name()` çıktısı (soyadı) + yıl örüntüsünü (`"Nakano" ... "2013"`, birkaç kelime mesafede) pasaj metninde arar. Soyadı yoksa (yalnız başlık anahtarlı iş) eşleştirme denenmez. Bu **kesin değildir**: "et al.", çeviri yazım, numaralı atıf biçimi (yalnız "[12]") ve ortak soyadları kaçırır ya da yanlış eşler; bu yüzden bulunan her eşleşme yalnız bir **aday**dır, bağ değildir.
2. **Model (`chain_links`):** sonraki çalışma başına bir çağrı, yalnız o çalışmanın adaylarını (önceki çalışmanın üç düğüm hücresi + eşleşme bulunan pasajlar) alır. Her aday için ya bir ilişki (kapalı liste: `extends`, `relaxes_assumption`, `changes_method`, `new_domain_or_condition`, `corrects_or_contradicts`, `independent_parallel`), ne değiştiği, destek türü (`source_stated`/`analyst_inference`) ve alıntı, ya da "ilişki yok" (`no_relation_from_source_ids`) döner. Her aday tam bir kez yanıtlanır (evidence-table'ın "her sütun tam bir kez" kuralının aynısı).

Kod denetimleri: her iki iş de dahil; sürümler tekilleşmiş (D48 başı); `to`nun yılı `from`dan önce değilse ya da ön baskı sıralaması bunu açıklıyorsa geçer, aksi halde uyarı; alıntı `to` işinin pasajında bulunur (D48'in "sonraki çalışma önceki çalışmayı anar" kuralı); `source_stated` bağın alıntısı zorunlu; atıf kenarı (§4.1'de çözülebiliyorsa) yoksa bağ **reddedilmez, işaretlenir** (`unexpected_no_citation_edge`); döngü oluşturan bağ reddedilir (bağlı bileşen kurulurken de ayrıca kontrol edilir); dallanma serbest.

**Kim ne yapıyor tablosu için bkz. §10.**

### 4.4 Çizgi montajı — benimsendi

Kabul edilen bağlar üzerinde bağlı bileşen (union-find) hesaplanır; her bileşen bir zincirdir, dallanma noktaları ve çapraz bağlar (bir düğümün birden çok giden/gelen bağı) korunur. Hiçbir bağı olmayan dahil iş "yerleştirilemedi" listesinde kalır, sessizce düşmez. Zincir ucu belirsizliği: bir düğümün `uncertainty_left` hücresi doludur, düğüm **tam metinlidir** (rapor tasarımının 10. kararındaki `corpus_absence` kuralıyla aynı gerekçeyle: yalnız özeti okunan bir düğümün "kimse peşine düşmedi" demesi okunmamış kısmın yokluğunu iddia etmek olur) ve hiçbir giden bağı `continues_predecessor_uncertainty = true` işaretini taşımıyor. Bu alan modelin yazdığı bir alandır (§4.3); kod yalnız yapıyı sayar, "gerçekten aynı belirsizlik mi" sorusu modele kalır (§10).

### 4.5 Rapora entegrasyon — benimsendi, bağımlılık açık yazıldı

Rapor çalışması (dilim 1) henüz kodda yok; bu bölüm bir **arayüz sözü**dür, dilim 1 bitmeden çalıştırılamaz (§15). `p6-report-design.md`'nin §3 tablosuna ve §4.3 kanıt seçimine eklenecekler:

- **Rapor planı:** `chain_ids` alanı (o rapor için hangi zincirler var).
- **III girdisi:** kabul edilmiş bağların bir özeti (from/to düğüm, ilişki, destek türü); model yalnız bunlardan "alanın gelişimi" alt bölümünü yazar, kronoloji ya da atıftan kendi bağını türetmez.
- **VI:** `report_gaps.kind = 'chain_end_uncertainty'` (alan zaten genişleyebilir, rapor tasarımı §12 madde 2). Basis: düğümün `uncertainty_left` hücresi ve alıntısı, zincir kimliği.
- **VII:** bu adaylardan türeyen yönler; `gap_refs` ile bağlanır (rapor tasarımının VII kuralı aynen geçerli).
- **Montaj denetimi:** III'teki her gelişim cümlesi bir `link_id`'ye eşlenir (rapor tasarımı §8'in `claim_key` → kanıt eşlemesiyle aynı örüntü); bir bağ, destek türünden daha güçlü bir dille (`source_stated` iken kesinmiş gibi) yazılamaz.
- **Ölçüm:** §14'teki R12-R17, rapor tasarımının §13 tablosuna eklenir.

### 4.6 Çizgi görünümü — benimsendi, yalnız metinle tarif edildi

`.impeccable.md` gereği burada görsel maket yok, yalnız davranış:

- Evidence sekmesinde, tablonun üstünde ya da yanında bir "Development chains" görünümü: her zincir bir şerit (lane), düğümler zaman sırasına göre yatayda, dallanma noktasında şerit ikiye ayrılır, çapraz bağ iki şerit arasında ince bir çizgiyle gösterilir.
- Her düğüm kısa künye taşır: `source_key` (D59, "Nakano13" gibi), yıl, okuma derinliği işareti. Tıklayınca kanıt tablosundaki satırına gider (D59'daki "tablo satırı kaynağı açar" davranışıyla aynı).
- Her bağ etiketi ilişki türünü düz metinle yazar ("extends", "relaxes an assumption"…), destek türüne göre stil ayrışır (source_stated dolu çizgi, analyst_inference kesik çizgi; renk değil, mevcut "amber = dikkat" tonlarının dışında yeni bir renk sözlüğü icat edilmez). Bağa tıklamak mevcut `PassageSheet`'i, alıntının bulunduğu sayfada açar.
- "Yerleştirilemedi" işler ayrı, düz bir liste olarak şeridin altında durur; sessizce gizlenmez.
- İnsan düzenlemesi (bağ silme, yeniden etiketleme, alıntısız ekleme) hücre düzenlemesiyle aynı önceliği taşır: sonraki `chain_links` çalışması bunları ezmez, yalnız yeni öneri üretir (§18 soru 5, 6).
- Pil yalnız kısa durum için (`.impeccable.md`); "denetlenmemiş" ya da "insan düzenledi" gibi durumlar düz metinle yazılır, ayrı bir renk sözlüğü icat edilmez.

## 5. Veri modeli taslağı

SQL'in geçerli hâli migration dosyası olur; bu bir niyet taslağıdır.

```sql
-- 00xx — atıf kenarı (yalnız her iki ucu da OpenAlex kökenliyse çözülür; ek çağrı yok, aynı arama isteğine eklenen alan)
ALTER TABLE source_versions ADD COLUMN openalex_work_id TEXT;                -- yalnız provider = openalex kayıtlarında dolu
ALTER TABLE source_versions ADD COLUMN openalex_referenced_works_json TEXT;  -- aynı yanıttan ham liste, sonradan çözülebilsin diye

CREATE TABLE citation_edges (
  citing_source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  cited_source_version_id  TEXT NOT NULL REFERENCES source_versions(id),
  resolved_at TEXT NOT NULL,
  PRIMARY KEY (citing_source_version_id, cited_source_version_id)
);

-- 00xx — alan tabanı (koddan hesaplanır, model çağrısı yok)
CREATE TABLE field_baseline_selections (
  id TEXT PRIMARY KEY,                 -- fbs_
  research_id TEXT NOT NULL REFERENCES researches(id),
  scope_revision INTEGER NOT NULL,
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  slot TEXT NOT NULL CHECK (slot IN ('foundational', 'review', 'close_primary', 'close_adjacent')),
  basis_json TEXT NOT NULL,            -- [{"kind": "citation_count", ...}, {"kind": "corpus_citation_frequency", ...}, ...]
  computed_at TEXT NOT NULL,
  UNIQUE (research_id, scope_revision, source_version_id, slot)
);

-- 00xx — zincirler (koddan bağlı bileşen olarak kurulur; düzenlenmez, yeniden hesaplanır)
CREATE TABLE chains (
  id TEXT PRIMARY KEY,                 -- chn_
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  scope_revision INTEGER NOT NULL,
  computed_at TEXT NOT NULL
);

CREATE TABLE chain_members (
  chain_id TEXT NOT NULL REFERENCES chains(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  is_branch_point INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (chain_id, source_version_id)
);

-- 00xx — çizgi bağları (append-only revizyon, cell_revisions ile aynı örüntü, D37)
CREATE TABLE chain_links (
  id TEXT PRIMARY KEY,                 -- clk_
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  from_source_version_id TEXT NOT NULL REFERENCES source_versions(id),   -- önceki çalışma
  to_source_version_id   TEXT NOT NULL REFERENCES source_versions(id),   -- sonraki çalışma (önceki çalışmayı anar)
  current_revision_id TEXT REFERENCES chain_link_revisions(id),
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK (from_source_version_id <> to_source_version_id),
  UNIQUE (from_source_version_id, to_source_version_id)
);

CREATE TABLE chain_link_revisions (
  id TEXT PRIMARY KEY,                 -- clr_
  link_id TEXT NOT NULL REFERENCES chain_links(id),
  kind TEXT NOT NULL CHECK (kind IN ('model_propose', 'human_add', 'human_edit', 'human_remove')),
  author TEXT NOT NULL CHECK (author IN ('model', 'human')),
  relation TEXT CHECK (relation IN ('extends', 'relaxes_assumption', 'changes_method',
                                    'new_domain_or_condition', 'corrects_or_contradicts', 'independent_parallel')),
  what_changed TEXT,                   -- ≤ 500 karakter
  support_type TEXT CHECK (support_type IN ('source_stated', 'analyst_inference')),
  continues_predecessor_uncertainty INTEGER NOT NULL DEFAULT 0,
  note TEXT,                           -- insan düzenlemesi gerekçesi
  run_id TEXT REFERENCES runs(id), step_id TEXT REFERENCES run_steps(id), step_input_id TEXT REFERENCES step_inputs(id),
  output_status TEXT CHECK (output_status IN ('structurally_valid', 'unverified_draft')),
  idempotency_key TEXT UNIQUE,
  created_at TEXT NOT NULL,
  CHECK ((kind = 'model_propose') = (author = 'model')),
  CHECK (kind <> 'human_remove' OR (relation IS NULL AND what_changed IS NULL))
);
CREATE INDEX chain_link_revisions_link ON chain_link_revisions(link_id, created_at);

CREATE TABLE chain_link_evidence (
  link_revision_id TEXT NOT NULL REFERENCES chain_link_revisions(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),   -- yalnız o bağın to_source_version_id'sinin pasajı
  anchor_text TEXT, anchor_match TEXT CHECK (anchor_match IN ('exact', 'normalized', 'fuzzy')),
  PRIMARY KEY (link_revision_id, passage_id)
);
-- cell_evidence_same_source (0020) ile aynı örüntü: kanıt yalnız to_source_version_id'nin pasajından gelebilir.
CREATE TRIGGER chain_link_evidence_same_source BEFORE INSERT ON chain_link_evidence
WHEN NEW.passage_id NOT IN (
  SELECT p.id FROM passages p JOIN chain_link_revisions r ON r.id = NEW.link_revision_id
  JOIN chain_links l ON l.id = r.link_id WHERE p.source_version_id = l.to_source_version_id)
BEGIN SELECT RAISE(ABORT, 'chain link evidence must come from the later work'); END;
-- + chain_link_revisions ve chain_link_evidence'da güncelleme/silme yasağı, purge yetkisi hariç (0010 örüntüsü).

-- 00xx — zincir ucu belirsizlikleri (koddan hesaplanır, corpus_absence'ın aynı örüntüsü)
CREATE TABLE chain_end_uncertainties (
  id TEXT PRIMARY KEY,                 -- ceu_
  table_id TEXT NOT NULL REFERENCES evidence_tables(id),
  chain_id TEXT NOT NULL REFERENCES chains(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  uncertainty_cell_id TEXT NOT NULL REFERENCES evidence_cells(id),
  computed_at TEXT NOT NULL
);
```

Rapor tasarımının `report_gaps` tablosuna (dilim 1) bu kayıt `kind = 'chain_end_uncertainty'`, `basis_json` ise bu tablodaki `id`, zincir ve alıntı olarak eklenir; yeni bir migration gerekmez, alan zaten genişleyebilir (§4.5).

## 6. Yöntem dosyası: `methods/deixis-research/references/synthesis.md`

```markdown
# Development chains and field baseline

This file is loaded only for the `chain_links` task. The field baseline (which
sources are foundational, a review, or a close study) is computed by the
application from stored citation counts and your own screening decisions; you
do not write it and are not asked about it here.

## Chain nodes

Three evidence-table columns describe one included work's place in the field's
development, filled through the ordinary `cell_extraction` task described in
[evidence table](evidence-table.md). Follow that file's rules (states, quoting,
`text_source`, `passage_scope`); this section only names what the three columns
mean:

- **`problem_addressed`**: the problem or question this work took up, in its
  own terms.
- **`established_or_changed`**: what this work established, showed, or changed
  relative to earlier work, if the passages say so. Do not infer a comparison
  the passages do not make.
- **`uncertainty_left`**: an uncertainty, limitation, or open question this
  work names as remaining or as future work. This is not the same column as an
  evidence table's own "limitations" or "proposed future work" columns if the
  table has them; when the source separates a stated limitation from a stated
  next step, prefer the next step here.

## Chain links (`chain_links` task)

Goal: for the one later work named in `chain_target.to_source_id`, decide
whether it develops each candidate earlier work in `chain_target.candidates`.
The application found these candidates because your later work's passages
contain a plausible mention (an author surname and year, or a title fragment)
of the earlier work; the match is mechanical and can be wrong, coincidental, or
about an unrelated paper by the same author. Confirming or rejecting each one
is your job.

**A link is never justified by chronology or by the presence of a citation
alone.** A citation only tells you the later work mentions the earlier one; you
must read what it says. Two works in date order with no stated or inferable
development relation get no link. A work citing another only as a data source,
a comparator with no methodological continuity, or in a related-work list
without discussion, does not get a link either, unless you can point to a
specific sentence that states a real dependency.

For every candidate in `chain_target.candidates`, do exactly one of:

1. **Propose a link.** Choose the closest relation:
   - `extends`: applies the earlier work's approach further (more scale, more
     cases, a generalization) without changing its core method or assumptions.
   - `relaxes_assumption`: removes or weakens a specific assumption the earlier
     work depended on.
   - `changes_method`: solves substantially the same problem with a different
     method, model, or algorithm.
   - `new_domain_or_condition`: applies the earlier work's problem or method to
     a new domain, setting, or experimental condition.
   - `corrects_or_contradicts`: reports a result that conflicts with the
     earlier work's. State the condition difference explicitly in
     `what_changed`; if the two results were obtained under different
     conditions (different parameters, environments, or definitions), say so
     instead of calling it a plain contradiction. Chronology and a citation
     never establish that a conflict is real; only the passages do.
   - `independent_parallel`: addresses the same problem without depending on
     the earlier work; use this only when the later work's own text places it
     this way (for example, naming the earlier work only as concurrent or
     unrelated work), not merely because you found no other relation.
   - Write `what_changed`: one or two sentences on what specifically moved
     between the two works, close to the source's own words.
   - Choose `support_type`: `source_stated` when a passage of the **later**
     work states the relation to the earlier one; `analyst_inference` when you
     infer it from what both works say without the later work stating the
     dependency itself.
   - Give `evidence`: one or more quotes from the later work's given passages
     (never the earlier work's) that anchor the mention and, where possible,
     the relation. `source_stated` requires at least one item whose quote
     names or clearly identifies the earlier work.
   - Set `continues_predecessor_uncertainty` to true only when the earlier
     work's `uncertainty_left` column names substantially the same open
     question this link's later work takes up. Leave it false when the link
     exists for another reason (a different problem, a parallel improvement).
     This field is how a chain's open question is marked as pursued; do not
     set it to make a chain look more complete than the text supports.
2. **Report no relation.** Add the candidate's `from_source_id` to
   `no_relation_from_source_ids` when, after reading the passages, you find no
   development relation. This is a considered answer, not a skip: distinguish
   it from a candidate you were not given (which never appears in your input).

Every candidate must appear exactly once, either in one link or in
`no_relation_from_source_ids`. Do not propose a link between two works you were
not asked to compare, and do not invent a third work.

## What this file does not cover

This version's chain construction does not include automatic novelty
assessment, candidate-question development, or kill-search. A found or missing
development link is not a statement about whether a research direction is
original. Preprint and published versions of one work are one node; you are
never given two versions of the same work to compare against each other.
```

## 7. Görev türleri, `RUNTIME_FILES`, `SKILL.md` değişiklikleri

- **Yeni `task_type`:** `chain_links`. `step-input.schema.json`'ın `task_type` enum'una eklenir; `capabilities.supported_tasks`'a girer.
- **`domain/skill.py::RUNTIME_FILES`:** `"chain_links": ("SKILL.md", "references/synthesis.md")`.
- **`SKILL.md`:** Görev tablosuna bir satır: `chain_links` için `references/synthesis.md`. "Literature synthesis across idea chains... are not available" cümlesi daralır: yalnız `chain_links` görevi ve rapor bölümleri III/VI/VII için açık olduğu, sıradan `grounded_answer` için yasağın aynen kaldığı yazılır (rapor tasarımının §4.1'deki `SKILL.md` değişikliğiyle aynı örüntü, "task types and RUNTIME_FILES" formatı).
- **Paket hash'i:** `synthesis.md` yeni dosya, `package_hash()` değişir; eski `StepInput`'lar eski hash'leriyle kalır (T13).
- **`provenance.json`:** `sources_used`'a bu notun ve README'nin CoI uyarlama kararının referansı eklenir; CoI-Agent hâlâ çalışma zamanı bağımlılığı değildir (`runtime_dependency_on_upstream: false` korunur).

## 8. JSON Schema'lar (tam)

### 8.1 `contracts/research/chain-links-draft.schema.json` (yeni)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/chain-links-draft.schema.json",
  "title": "ChainLinksDraft",
  "description": "For the one later work named in the StepInput's chain_target, a development-relation judgment for each candidate earlier work the application found a plausible mention of. A link is never accepted on chronology or citation presence alone; passing structural checks is not semantic verification.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "step_input_id",
    "scope_revision",
    "skill_package_hash",
    "links",
    "no_relation_from_source_ids"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.chain_links_draft.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "links": {
      "type": "array",
      "maxItems": 8,
      "description": "One item for a candidate you judge to have a development relation to chain_target.to_source_id.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["from_source_id", "relation", "what_changed", "support_type", "continues_predecessor_uncertainty", "evidence"],
        "properties": {
          "from_source_id": { "$ref": "common.schema.json#/$defs/source_id" },
          "relation": {
            "type": "string",
            "enum": ["extends", "relaxes_assumption", "changes_method", "new_domain_or_condition",
                     "corrects_or_contradicts", "independent_parallel"]
          },
          "what_changed": { "type": "string", "minLength": 1, "maxLength": 500 },
          "support_type": {
            "type": "string",
            "enum": ["source_stated", "analyst_inference"],
            "description": "source_stated: a passage of the later work states the relation to the earlier one. analyst_inference: inferred without the later work stating the dependency itself."
          },
          "continues_predecessor_uncertainty": {
            "type": "boolean",
            "description": "True only when the earlier work's uncertainty_left column names substantially the same open question this link takes up."
          },
          "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "description": "Quotes from the LATER work's given passages only, never the earlier work's.",
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": ["passage_id", "quote"],
              "properties": {
                "passage_id": { "$ref": "common.schema.json#/$defs/passage_id" },
                "quote": { "type": "string", "minLength": 12, "maxLength": 600 }
              }
            }
          }
        }
      }
    },
    "no_relation_from_source_ids": {
      "type": "array",
      "maxItems": 8,
      "description": "Candidates considered and judged to have no development relation. Distinct from a candidate never given.",
      "items": { "$ref": "common.schema.json#/$defs/source_id" }
    }
  }
}
```

Ek denetim (`domain/contracts.py`'de yeni `_check_chain_links`, mevcut `_check_cells`'in örüntüsüyle): `links[].from_source_id` ve `no_relation_from_source_ids` birleşimi, `chain_target.candidates[].from_source_id` kümesiyle birebir aynı olmalı (ne eksik ne fazla); `evidence[].passage_id` yalnız `chain_target.to_source_id`'nin allowlist'teki pasajlarından olmalı; `source_stated` en az bir `evidence` ister (şema zaten `minItems: 1` ile bunu garanti ediyor, ama `analyst_inference` için de en az bir pasaj referansı isteniyor çünkü aday zaten o pasajdan bulundu — bu, D27'nin "value en az bir pasaj ister" kuralının burada da geçerli kılınmasıdır); `locate_anchor` her alıntıyı ilgili pasajda bulur, bulamazsa tek onarıma gider (mevcut `_check_cells`/`_check_answer` mekanizmasıyla aynı).

### 8.2 `step-input.schema.json` eklentisi

```json
"task_type": {
  "type": "string",
  "enum": ["search_plan", "screening", "grounded_answer", "answer_review",
           "cell_extraction", "table_columns", "research_title", "chain_links"]
},
```

```json
"chain_target": {
  "type": "object",
  "description": "chain_links steps only: the one later work being judged, its own three node cells (context only), and the candidate earlier works the application's mention-finder matched inside its passages.",
  "additionalProperties": false,
  "required": ["table_id", "to_source_id", "to_node", "candidates"],
  "properties": {
    "table_id": { "type": "string", "pattern": "^tbl_[0-9A-Za-z]{8,40}$" },
    "to_source_id": { "$ref": "common.schema.json#/$defs/source_id" },
    "to_node": {
      "type": "object",
      "additionalProperties": false,
      "required": ["problem_addressed", "established_or_changed", "uncertainty_left"],
      "properties": {
        "problem_addressed": { "type": ["string", "null"] },
        "established_or_changed": { "type": ["string", "null"] },
        "uncertainty_left": { "type": ["string", "null"] }
      }
    },
    "candidates": {
      "type": "array",
      "maxItems": 8,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["from_source_id", "from_node", "mention_passage_ids"],
        "properties": {
          "from_source_id": { "$ref": "common.schema.json#/$defs/source_id" },
          "from_node": {
            "type": "object",
            "additionalProperties": false,
            "required": ["problem_addressed", "established_or_changed", "uncertainty_left"],
            "properties": {
              "problem_addressed": { "type": ["string", "null"] },
              "established_or_changed": { "type": ["string", "null"] },
              "uncertainty_left": { "type": ["string", "null"] }
            }
          },
          "mention_passage_ids": {
            "type": "array",
            "minItems": 1,
            "items": { "$ref": "common.schema.json#/$defs/passage_id" }
          }
        }
      }
    }
  }
}
```

`common.schema.json`'a yeni bir tanım gerekmiyor; mevcut `source_id`/`passage_id`/`step_input_id`/`scope_revision`/`skill_package_hash` tanımları yeterli.

## 9. Bütçe ve ölçeklendirme kuralları

- **Çağrı birimi:** sonraki-çalışma başına bir `chain_links` çağrısı (evidence-table'ın kaynak başına çağrı örüntüsüyle aynı, D38 §5). Yalnız en az bir adayı olan sonraki-çalışmalar çağrılır; adayı olmayan iş hiç çağrılmaz.
- **Aday kapağı:** çağrı başına en fazla 8 aday (şemadaki `maxItems`, evidence-table'ın 8-sütun bölme sınırıyla aynı sayı). Bir sonraki-çalışmanın 8'den çok adayı varsa, ikinci bir çağrıya bölünür (kalanlar).
- **Aday bulma tüm-çift patlamasını önler:** aday bulma iş sayısının karesi değil, mention-eşleşme sayısı kadar iş yapar; bir sonraki-çalışma yalnız metninde soyadı+yıl (ya da başlık sözcüğü) geçen önceki çalışmaları aday alır, geri kalanı hiç görmez. Alt-konu ya da zaman penceresine göre partileme bu yüzden gerekmiyor; aday bulma zaten doğal bir filtre.
- **Üst sınır:** bir `chain_links` çalışması en fazla 25 dahil, tam metinli iş alır (P5 dilim 1'in `MAX_FILL_SOURCES` sabitiyle aynı sayı, aynı gerekçeyle: D34'teki düzeltilmiş çekirdek küme büyüklüğü). Kalan işler ikinci bir çalışmayla işlenir.
- **Eş zamanlılık:** çağrılar, rapor tasarımının §12 dilim 0'da tanımladığı süreç-geneli üst sınırlı eş zamanlı gönderim mekanizmasını kullanır (aynı sınır, tablo doldurma ve rapor bölümleriyle paylaşılır).
- **Pasaj bütçesi:** her çağrıya, sonraki-çalışmanın yalnız düğüm hücrelerinin alıntı pasajları + mention'ların bulunduğu pasajlar verilir (bütün pasajları değil); bu, evidence-table'ın 24 pasaj/kaynak sınırının çok altında kalır çünkü mention pasajları tipik olarak birkaç sayfadır.

## 10. Kim ne yapıyor: kod doğrular / model değerlendirir / doğrulanmayan

| Kural | Kodun doğruladığı yapı | Modelin değerlendirdiği anlam | Doğrulanmayan |
|---|---|---|---|
| Aday tam kapsama | her aday tam bir kez, ya link ya `no_relation_from_source_ids`'te | — | — |
| Alıntı ve çapa | alıntı `to_source_id`'nin pasajında birebir/normalize bulunur (`locate_anchor`) | alıntı gerçekten ilişkiyi mi anlatıyor | bağlamın doğru aktarıldığı |
| Kronoloji/atıf tek başına yeterli değil (T11) | bağ yalnız model onayıyla kurulur; `citation_edges`'ten otomatik bağ **hiç üretilmez** | ilişkinin gerçek olup olmadığı, koşulların karşılaştırılabilir olduğu | fikri bağımlılığın gerçekten var olduğu |
| Atıf kenarı eksikliği | model bağı, çözülmüş bir `citation_edges` satırı yoksa `unexpected_no_citation_edge` işareti alır (ret değil) | — | kenar veritabanının eksiksizliği (yalnız OpenAlex-kökenli çiftler çözülüyor) |
| Yıl sırası | `to`nun yılı `from`dan önce ise uyarı (ön baskı istisnası hariç) | ön baskı sıralamasının makul açıklama olup olmadığı | — |
| Döngü | bağlı bileşen kurulurken döngü oluşturan bağ reddedilir | — | — |
| Zincir ucu belirsizliği | tam metinli düğüm, dolu `uncertainty_left`, hiçbir giden bağda `continues_predecessor_uncertainty=true` yok | aynı belirsizliğin gerçekten peşine düşülüp düşülmediği (`continues_predecessor_uncertainty`'yi model yazıyor) | korpus dışında peşine düşülüp düşülmediği (kill-search, dilim 3) |
| Sürüm tekilliği | `from`/`to` D48'in baş sürümüne indirgenir | — | — |
| Alan tabanı gerekçesi | `basis_json` yalnız saklı sayılardan dolu | — | "kurucu etki"nin kendisi (yalnız atıf sayısı ve korpus içi sıklıkla yaklaşıklanıyor) |

## 11. Davranış vakaları ve T11

`scripts/model_behavior/` altına, `gpt-5.6-luna` ile (kullanıcının hafızasındaki kural: canlı model testleri Luna ile) koşulacak vakalar:

1. **Atıf var, gelişim ilişkisi belirsiz.** Sonraki çalışma önceki çalışmayı bir cümlede anıyor ama ne aldığını söylemiyor. Beklenen: `no_relation_from_source_ids`, ya da düşük güvenli `analyst_inference` ile açıkça sınırlı bir `what_changed`; **T11'in yürütülebilir denetimi**: kod, bu çift için `citation_edges` çözülmüşse bile bağın **yalnız kenar varlığından** kurulmadığını doğrular (bağ yoksa test geçer; bağ varsa `support_type` ve `evidence` zorunlu olduğu için salt kenardan üretilemez zaten).
2. **Kronolojik sıradaki iki çalışma, ilişkisiz.** Beklenen: `no_relation_from_source_ids`; zincir ucu belirsizliği yanlışlıkla oluşmaz (§10 satır 3'ün testi).
3. **Ön baskı ve yayımlanmış sürüm ayrı düğüm gibi verilirse.** Bu vaka aslında D48'in düğümleri zaten tekilleştirdiğini gösterir; test bu ayrımın modele hiç ulaşmadığını (StepInput'ta yalnız baş sürüm olduğunu) doğrular.
4. **Farklı koşullarda ters sonuç.** İki pasaj aynı büyüklüğü farklı deney koşullarında ölçüyor. Beklenen: `corrects_or_contradicts` yalnız `what_changed` koşul farkını açıkça yazarsa kullanılır; aksi hâlde model "farklı koşullarda farklı sonuç" diye sınırlar (T11'in ikinci yarısı, `report_review`'ın VI/VII değerlendirmesindeki aynı kural).
5. **Yalnız özeti okunan sonraki çalışma.** Beklenen: `chain_target.to_node` ve mention pasajları özet düzeyinde kalır; model `evidence` için özetin ötesine geçen bir ayrıntı (yöntem değişikliği gibi) üretmez, `analyst_inference` ile sınırlı kalır ya da `no_relation` der.
6. **Çekici ama geçersiz uzak analoji.** Başka alandan bir çalışma yüzeysel bir anahtar kelimeyle eşleşiyor (mention bulucusu yanlış eşleştirmiş olabilir). Beklenen: model, pasajları okuyup gerçek bir gelişim ilişkisi bulamadığını `no_relation_from_source_ids`'te söyler.

## 12. Testler (taslak)

**Aday bulma (deterministik, model yok)**

- `tests/test_chain_mentions.py`: soyadı+yıl eşleşmesi bulunan/bulunmayan sentetik pasajlar; particle/suffix'li soyadların `source_keys.py::family_name` ile aynı normalize edildiği; başlık-anahtarlı (yazarsız) işin hiç aday üretmediği.

**Sözleşme ve depolama**

- `tests/test_chain_links_contract.py`: her adayın tam bir kez yanıtlandığı; eksik/fazla aday; `to_source_id`'nin pasajı olmayan bir `evidence`; `source_stated` için boş `evidence`; bilinmeyen `from_source_id`.
- `tests/test_chain_assembly.py`: bağlı bileşen kurma (dallanma, çapraz bağ, izole iş "yerleştirilemedi"); döngü reddi; yıl sırası uyarısı ve ön baskı istisnası; zincir ucu belirsizliği yalnız tam metinli düğümde ve `continues_predecessor_uncertainty` yokken.
- `tests/test_chain_link_edits.py`: insan bağ silme/ekleme/yeniden etiketleme append-only revizyon olarak saklanır; sonraki model çalışması insan revizyonunu ezmez, yalnız öneri üretir (D37 T09 örüntüsünün burada tekrarı).
- `tests/test_field_baseline.py`: `basis_json`'ın yalnız saklı sayılardan (atıf sayısı, korpus içi sıklık, sıra, tarama kararı) doldurulduğu; hiçbir model çağrısı yapılmadığı; korpus içi atıf sıklığının yalnız her iki ucu da OpenAlex kökenliyken hesaplandığı.
- **T11 yürütülebilir denetim** (`tests/test_chain_links_contract.py::test_citation_edge_alone_never_creates_a_link`): `citation_edges` tablosunda çözülmüş bir kenar olsa bile, model `no_relation_from_source_ids` derse bağın oluşmadığı; bağ yalnız modelin döndürdüğü destekli `links[]` öğesinden kurulur.

**Migration**

- `tests/test_chain_migrations.py`: yeni tabloların foreign key ve tetikleyicileriyle boş bir P6-öncesi kopya üzerinde temiz uygulanması; `chain_link_evidence_same_source` tetikleyicisinin başka sürümün pasajını reddettiği.

**Web**

- `npm run build`, `npm run lint`.
- Playwright (fixture sunucusu, senaryolu model): iki-üç düğümlü sentetik bir zincir; bağa tıklayınca `PassageSheet` doğru sayfada açılır; "yerleştirilemedi" listesi görünür; insan bağ silme kalıcı.

**Bu dilimde geçmeyecekler:** rapor entegrasyonunun uçtan uca testi (dilim 1'e bağlı, §15); kill-search ve aday kartı (dilim 3); LaTeX dışa aktarım (dilim 5).

## 13. Kabul senaryosu (senaryolu model)

Fixture sunucusunda (`tests/acceptance/fixture_server.py`) beş sentetik iş: A (temel, yüksek atıf), B ve C (A'yı birer cümleyle anıp genişleten/yöntemi değiştiren iki bağımsız devam), D (B'yi anan ama ilişkisiz bir konudaki iş, mention bulucusu yanlışlıkla eşleştirsin diye aynı soyadı taşıyan başka bir yazar), E (hiçbir işi anmayan, izole). Beklenen: A→B, A→C bağları (dallanma), D "ilişki yok" ile döner ve E "yerleştirilemedi" listesinde görünür. B'nin `uncertainty_left`'i doldurulur ve hiçbir giden bağı yoktur; zincir ucu belirsizliği olarak işaretlenir. Bu, sentetik veriyle **uygulama davranışını** gösterir, model kalitesini değil (AGENTS.md'nin "Playwright suite… demonstrates application behavior, not scientific correctness" kuralı).

## 14. Ölçüm planı (dilim 1'in R-numaralarına devam; koşudan önce dondurulur)

Kural aynı (D55, p6-report-design.md §13): sayısal aralıklar koşudan önce ayrı bir dosyada donar, sonradan yorumlanıp beklentiye uydurulmaz. Kütüphanenin bir kopyasında, `gpt-5.6-luna` ile, gerçek bir soru üzerinde:

| # | Ne | Payda ve tanım |
|---|---|---|
| R12 | Bağ kesinliği | önerilen bağlardan sabit tohumla çekilen bir örneklem; her biri alıntısına ve iki düğümün metnine karşı Claude tarafından: destekler / kısmen / desteklemez |
| R13 | Yalnız kronolojiden yanlış bağ | R12'nin aynı örnekleminde, incelemecinin "bu bağın tek dayanağı tarih/atıf sırası, ilişki metinde yok" diye işaretlediği bağ sayısı / örneklem |
| R14 | Kaçırılan bağ | sahibin önceden bildiği küçük bir zincir (2-4 işlik, soru sorulmadan önce yazılı) ile karşılaştırma: modelin bulduğu / sahibin bildiği bağ sayısı |
| R15 | Yerleştirilemedi oranı | "yerleştirilemedi" listesindeki dahil, tam metinli iş / toplam dahil, tam metinli iş |
| R16 | Zincir ucu belirsizliği isabeti | üretilen her zincir ucu adayının, incelemecinin "gerçekten korpustan sonra hiç peşine düşülmemiş" dediği / üretilen aday sayısı |
| R17 | Alan tabanı gerekçe tutarlılığı | her yuvadaki adayın `basis_json`'ının, saklı sayılarla (atıf sayısı, sıra) birebir aynı olduğu; bu yapısal bir denetimdir, model çağrısı olmadığı için "yanlış" değil yalnız "eksik sinyal" olabilir (örn. atıf kenarı çözülemedi) |

Payda sıfırsa metrik "ölçülemedi" yazılır. İncelemeci Claude'dur, sahip etiketlemedikçe; Claude'un okuması insan denetimi sayılmaz (rapor tasarımı §13'ün aynı cümlesi). Bu ölçüm, dilim 1'in R1-R11'ine **ek**tir, onların yerine geçmez.

## 15. Dilim 1'den beklenenler

- `report` çalışma türü, kanıt anlık görüntüsü (§4.2 rapor tasarımı) ve `report_plan`/bölüm adımı makinesi çalışır durumda olmalı; bu dilimin §4.5'i (rapora entegrasyon) bunsuz test edilemez.
- `report_gaps.kind`'ın gerçekten genişleyebilir bir alan olarak (kapalı bir CHECK kısıtı değil) uygulanmış olması.
- III'ün alt bölüm mekanizması (`axis_id` benzeri bir yapı ya da en azından serbest bir alt başlık alanı) kodda var olmalı.
- Montaj denetiminin `claim_key` → kanıt eşleme örüntüsü (rapor tasarımı §8) kodda çalışıyor olmalı; bu dilim `link_id` için aynı örüntüyü tekrar eder.
- **Bu dilimin kendisi rapor çalışmasından bağımsız çalıştırılabilir**: alan tabanı, düğüm hücreleri, çizgi bağları ve çizgi görünümü Evidence sekmesinde, rapor hiç üretilmeden de kullanılabilir. Yalnız §4.5 (rapor entegrasyonu) ve §13'ün rapor bölümüyle ilgili kısmı dilim 1'e bağlıdır.

## 16. Dilim 3'e verilenler

Kill-search ve aday kartı (dilim 3), bir zincir ucu belirsizliğinden aday kartı açabilmek için şu arayüzü alır:

```text
ChainEndUncertainty:
  id                    ceu_...
  chain_id              chn_...
  source_version_id     srv_...   # zincirin son düğümü
  source_key            "Nakano13" gibi (D59)
  uncertainty_text       düğümün uncertainty_left hücresinin geçerli değeri
  uncertainty_evidence   [{passage_id, quote}]  # o hücrenin alıntıları
  chain_members          [{source_version_id, source_key, year}]  # aday kartının "en yakın çalışma" bağlamı için
  field_baseline_context  [{source_version_id, slot, basis_json}]  # kill-search'ün "alandaki en güçlü önceki çalışma" karşılaştırıcısı için
  kill_search_status     "not_run" (rapor tasarımı §7'deki corpus_absence kaydıyla aynı alan adı)
```

Ayrıca dilim 3, `chain_links.relation` kapalı listesini adayın "oluşma yolu" alanına (research-methods.md §4'teki "varsayım, uyuşmazlık, transfer, yöntem iyileştirmesi" etiketleriyle örtüşüyor) referans olarak kullanabilir; iki liste birebir aynı değildir ve dilim 3 kendi kapalı listesini ayrıca tanımlamalıdır.

## 17. Varsayımlar

- OpenAlex `type` alanının bir `review` değeri taşıdığı doğrulanmadı; §4.1'deki `core_reviews` varyantı bu doğrulanmadan uygulamaya alınmamalı.
- Atıf kenarı yalnız her iki ucu da OpenAlex kökenli olduğunda çözülür; bu, korpus içi atıf sıklığı sinyalinin kütüphanenin OpenAlex kapsama oranına bağlı, eksik bir yaklaşıklama olduğu anlamına gelir.
- Soyadı+yıl eşleştirmesi kesin değildir; ortak soyadları, "et al." biçimleri ve numaralı atıf stilini (yalnız "[12]") kaçırır ya da yanlış eşler. Bu yüzden aday bulma bir öneri katmanıdır, model her adayı okuyup reddedebilir.
- CoI-Agent'ın sabit parametreleri (zincir uzunluğu 5, dal sayısı 3) §0'da anlatıldığı gibi ikinci elden bir özetten geldi ve doğrulanmadan aktarıldı; bu notun tasarımı zaten bunları devralmıyor, yalnız bu belirsizlik kaydedilsin diye burada tekrar ediliyor.
- Düğüm hücrelerinin (§4.2) kullanıcıya görünür sıradan sütun olması bir öneri; §18 soru 1 açık.
- Rapor tasarımının kabul edilmiş §12 madde 2'sindeki dört öğe (alan tabanı, çizgiler, VI'ya dördüncü tür, çizgi görünümü) bu notta karşılanıyor; kill-search ve aday somutlaştırma kapsam dışı bırakıldı (dilim 3).
- Bütçe sayıları (25 iş, 8 aday/çağrı) P5 dilim 1'in sayılarından ödünç alındı, bu dilim için ayrıca ölçülmedi.

## 18. Sahibe sorulanlar

Her soruda önerdiğim seçenek ilk sırada, gerekçesiyle. Yanıt gelmezse ilk seçenek alınır.

1. **Düğüm hücreleri, sıradan görünür sütun mu, ayrı sistem tablosu mu?**
   a. Sıradan görünür sütun, `evidence_cells`'in bir parçası (öneri). *Gerekçe:* revizyon/insan-düzenleme/recheck makinesi bedavaya gelir (§4.2); kalabalık riski kabul edilebilir çünkü sütunlar isteğe bağlı eklenir, zorunlu değildir.
   b. Ayrı, kullanıcıya görünmeyen sistem tablosu; kanıt tablosunu kalabalıklaştırmaz ama D37'nin bütün makinesini ikinci kez kurmak gerekir.
   c. Görünür ama tabloda değil, yalnız çizgi görünümünde bir künye satırı; kanıt provenance'ı (alıntı, revizyon) o zaman ayrı bir yapı ister.

2. **Atıf kenarı (`referenced_works`) OpenAlex'ten çekilsin mi?**
   a. Evet, aynı çağrıya eklenen ücretsiz bir alan olarak; yalnız her iki ucu da OpenAlex kökenliyken çözülür (öneri). *Gerekçe:* ek maliyet yok, T11'in "atıf tek başına kanıt değil" kuralını güçlendiren bir çapraz kontrol (§10) sağlıyor.
   b. Hayır, bu dilimde eklenmez; bağ kurma yalnız mention-eşleştirme + model yargısına dayanır, atıf kenarı hiç saklanmaz.
   c. Evet, ve eksik kenarları tamamlamak için ayrı bir toplu OpenAlex sorgusu da yapılır (ek API maliyeti kabul edilir).

3. **Alan tabanı araması ne zaman çalışır?**
   a. Yalnız rapor ya da çizgi görünümü istenince, kullanıcı isteğiyle (öneri). *Gerekçe:* discovery'nin bugünkü maliyetini büyütmez; çoğu soru rapora hiç gitmeyebilir.
   b. Her discovery ile otomatik, her araştırmada.
   c. Kullanıcı bir ayardan açar/kapatır.

4. **Kapalı ilişki listesi bu haliyle mi kalsın?**
   a. `extends`, `relaxes_assumption`, `changes_method`, `new_domain_or_condition`, `corrects_or_contradicts`, `independent_parallel` (öneri, §6). *Gerekçe:* research-methods.md §4'teki "oluşma yolu" etiketleriyle örtüşüyor, kapalı ve az sayıda.
   b. Daha kısa liste (yalnız `extends`, `changes_method`, `corrects_or_contradicts`).
   c. Serbest metin etiket, kapalı liste yok (denetlenebilirlik azalır).

5. **Analist çıkarımı bağlar rapora girsin mi, yoksa yalnız çizgi görünümünde mi kalsın?**
   a. İkisine de girer, ama rapor cümlesi destek türünü açıkça yazar ("kaynağın kendi anlattığı" / "analist çıkarımı"), rapor tasarımı §6'nın son maddesiyle aynı kural (öneri).
   b. Yalnız çizgi görünümünde; rapor yalnız `source_stated` bağları kullanır.
   c. Rapor hiçbirini kullanmaz, yalnız düz metinle "gelişim çizgileri ayrı görünümde" der.

6. **İnsan, kanıtsız yeni bir bağ ekleyebilir mi?**
   a. Hayır; her insan eklemesi de en az bir pasaj ister, hücre düzenlemesindeki `value` kuralıyla tutarlı (öneri). *Gerekçe:* "her hücre bir kaynağa işaret eder" ilkesini (AGENTS.md "Every cell points to its source") bağlar için de korur.
   b. Evet, kanıtsız eklenebilir ama görünürde "insan notu, kanıtsız" diye ayrı işaretlenir.
   c. Yalnız var olan bir bağı silebilir/yeniden etiketleyebilir, yeni bağ ekleyemez.

7. **Zincir görünümü nerede yaşasın?**
   a. Evidence sekmesinde, kanıt tablosunun yanında yeni bir alt sekme/görünüm (öneri). *Gerekçe:* düğüm hücreleri zaten o tablonun sütunları; aynı yerde kalmak bağlamı korur.
   b. Ayrı bir üst sekme (Answer/Papers/Evidence/Report yanında beşinci).
   c. Yalnız rapordan açılan bir alt görünüm, rapor yokken erişilemez.

8. **`chain_links` kaç işe kadar otomatik çalışsın?**
   a. En fazla 25 dahil, tam metinli iş (P5 dilim 1'in sınırıyla aynı, öneri).
   b. Daha düşük bir sınır (örn. 15), maliyeti kısmak için.
   c. Sınır yok; sahip her seferinde onaylıyor.

## 19. Alt adımlar

Satır düzeyinde değil, alt adım düzeyinde; her biri kendi başına test edilebilir. Sıra bağımlılığa göre.

1. **Atıf kenarı (modelsiz).** `providers/openalex.py::SELECT`'e `referenced_works` eklenir; `openalex_work_id`/`openalex_referenced_works_json` sütunları ve `citation_edges` tablosu için migration; her iki ucu OpenAlex kökenliyken kenarın koddan çözülmesi. **Test:** `tests/test_citation_edges.py` (sentetik OpenAlex yanıtıyla kenar kaydı, tek ucu OpenAlex olmayan çift çözülmez). **Çıkış:** migration temiz uygulanır, yeni testler geçer, canlı kütüphaneye yazılmaz.
2. **Alan tabanı (modelsiz).** `flow.py::_discovery`'ye `core_by_citation`/`core_reviews` sorgu varyantları (§18 soru 3'ün cevabına göre otomatik ya da istekle); `field_baseline_selections` migration'ı ve koddan hesaplama (`basis_json`). **Test:** `tests/test_field_baseline.py`. **Çıkış:** dört yuvaya adaylar, her biri gerekçeli; OpenAlex `review` filtresi doğrulanmadıysa o varyant atlanır ve bu görünür şekilde loglanır.
3. **Düğüm sütunları.** `references/evidence-table.md`'ye dokunmadan, `synthesis.md`'de üç sütunun tanımı (§6); tablo şablonuna ya da `table_columns` önerisine üç yeni sütun. **Test:** mevcut `test_evidence_table.py` fixture'larına bu üç sütunla bir vaka; `cell_extraction`'ın `text` biçimiyle zaten çalıştığının doğrulanması (yeni denetim gerekmez). **Çıkış:** sahte adaptörle bir doldurma çalışması üç sütunu da dolduruyor.
4. **Aday bulma (modelsiz).** `workflow/chain_mentions.py` (yeni): `source_keys.py::family_name`'i kullanarak soyadı+yıl eşleştirmesi; başlık-anahtarlı işler için eşleştirme yapılmaz. **Test:** `tests/test_chain_mentions.py` (§12). **Çıkış:** sentetik pasajlarda beklenen adaylar bulunuyor, particle/suffix'li adlar doğru normalize ediliyor.
5. **`chain-links-draft.schema.json` ve `step-input.schema.json` eklentisi.** Şema dosyaları, `domain/contracts.py::_check_chain_links` (yeni), `tests/fixtures/research/{step-inputs,fake-outputs}.json` ve `tests/fakes.py::valid_response` güncellemesi. **Test:** `tests/test_chain_links_contract.py` (§12, T11 denetimi dahil). **Çıkış:** modelsiz sözleşme testleri geçer; `package_hash` değişikliği `test_skill.py`'de doğrulanır.
6. **`chain_links` adımı ve `flow.py`'ye entegrasyon.** `_chain_links` metodu (evidence-table'ın `_extraction`/`_cell_passages` örüntüsüyle), `chain_links` run türü, bütçe (§9), eş zamanlılık (dilim 0'ın paylaşılan sınırı hazırsa onu kullanır, değilse sıralı çalışır ve bu not düşülür). **Test:** sahte adaptörle akış testleri (T09 örüntüsü: insan düzenlemesi varken model çalışması onu ezmiyor). **Çıkış:** `runs`/`run_steps`/`step_inputs` kaydı bugünkü örüntüyle çalışıyor, duraklatma/devam/`outcome_unknown` davranıyor.
7. **Zincir montajı (modelsiz).** `workflow/chains.py` (yeni): bağlı bileşen, dallanma, çapraz bağ, yerleştirilemeyen işler, zincir ucu belirsizliği hesaplama; `chains`/`chain_members`/`chain_end_uncertainties` migration'ı. **Test:** `tests/test_chain_assembly.py` (§12). **Çıkış:** sentetik bağ kümesiyle beklenen zincirler ve uç belirsizlikleri üretiliyor.
8. **İnsan düzenlemesi.** `chain_link_revisions`'a `human_add`/`human_edit`/`human_remove`; API uçları (`POST/PUT/DELETE .../chain-links/{id}`, mevcut CSRF ve `expected_version` deseniyle). **Test:** `tests/test_chain_link_edits.py` (§12). **Çıkış:** insan düzenlemesi sonraki model çalışmasınca ezilmiyor (D37 T09 örüntüsü).
9. **Arayüz: çizgi görünümü.** Evidence sekmesine yeni görünüm (§4.6, §18 soru 7'nin cevabına göre yerleşim); `PassageSheet` ile bağlantı; "yerleştirilemedi" listesi. **Test:** Playwright, fixture sunucusu ve senaryolu model (§13). **Çıkış:** masaüstü ve 390 px, açık/koyu temada; klavye erişimi doğrulanır.
10. **Davranış vakaları.** `scripts/model_behavior/` altına §11'deki altı vaka; `gpt-5.6-luna` ile bir kez koşulur, sonuç `.local/`'e yazılır. **Çıkış:** her vaka için beklenen/gözlenen davranış kaydı; T11'in yürütülebilir denetimi (adım 5'te yazılan test) ayrıca geçer.
11. **Rapor entegrasyonu (dilim 1 bittiyse).** `report_gaps.kind = 'chain_end_uncertainty'`, III/VI/VII'nin bu notta tarif edilen girdileri, montaj denetimine `link_id` eşlemesi. **Test:** dilim 1'in montaj denetim test dosyasına yeni vakalar. **Çıkış:** sentetik bir raporda zincir ucu adayı VI'da, ona bağlı yön VII'de görünüyor. **Bu adım dilim 1 tamamlanmadan yapılamaz (§15).**
12. **Kapanış.** Tam backend suite, `npm run build`/`lint`, acceptance, `git diff --check`; `docs/decisions.md`'ye D-girdisi (Evidence, Limits); §17'deki doğrulanmamış varsayımların (OpenAlex `review` türü, CoI'nin sabit parametreleri) hâlâ doğrulanmadıysa bunun açıkça yazılması. Canlı kütüphaneye yazılmaz; ölçüm (§14) ayrı, isteğe bağlı bir adımdır ve kapanışı beklemez.

