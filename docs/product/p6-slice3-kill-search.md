# P6 dilim 3 — iddiaya özgü kill-search ve aday kartı: tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Taslak; sahibin yanıtı bekleniyor. Dilim 0–2'nin aksine bu dilimin kabul edilmiş bir tasarımı yok; yalnız [p6-report-design.md](p6-report-design.md)'nin bu dilime bıraktığı arayüz sabittir (rapor bölüm VI'daki `report_gaps` kaydı, `kill_search_status: not_run`, T12). Bu not kod içermez; hiçbir dosya değiştirilmedi.

## Kısaca

Rapor bugün (dilim 1 tasarımıyla) her cevaplanmamış yönü bir `report_gaps` kaydı olarak listeler; `kind` kapalı bir liste değil, kod tarafından denetlenen genişleyebilir bir alandır (p6-report-design.md §12) ve dört değer taşıyacaktır — `stated_limitation`, `conflicting_evidence`, `corpus_absence` (dilim 1) ve dilim 2'nin getirdiği `chain_end_uncertainty`: bir gelişim çizgisinin ucunda kalan, korpusta peşine düşülmemiş belirsizlik. Bu son tür kendiliğinden bir aday değildir — kod önce onu yalnız çizgi görünümünde `no_continuation_in_corpus` diye işaretler; yalnız **tamamlanmış bir ileri atıf denetimi eklendiğinde VE sahip açıkça yükselttiğinde** (`chain_end_uncertainties.forward_check_id` + `promoted_at`, dilim 2 §4.4) bir `report_gaps` satırına, dolayısıyla bu dilimin açabileceği bir adaya dönüşür.

Sahibin 14 Eylül 2026 Chain of Ideas kararı ([README](../../README.md#selected-synthesis-method-chain-of-ideas)) **ertelenmiş değildir**: kabul edilen altı adımlı sıra, gelişim çizgileriyle alan haritası → sahibin hangi ucu geliştireceğini yükseltmesi ve amaç/mekanizma/değerlendirmeyi düzenlemesi → **her adayın belirli iddiasına kill-search** → hayatta kalan ya da daralan sorunun koşullu hipotez, varsayım ve doğrulama planıyla sunulmasıdır. Bu dilim üçüncü adımın tamamını, dördüncü adımın "kart açıldıktan sonraki düzenleme" kısmını ve altıncı adımın bir kısmını kurar; birinci ve ikinci adım (alan haritası, gelişim çizgileri) ve dördüncü adımın "yükseltme" kısmı dilim 2'nindir (`p6-slice2-chain-of-ideas.md`, artık yazılmış ve okundu).

Bir aday `report_gaps`'ten "İncele" ile açıldığında [research-methods.md](../methods/research-methods.md) §4'teki aday kartına döner: iddia, koşullar, en yakın basit açıklama, kritik varsayım, doğrulama planı ve — çizgiden geldiyse — hangi gelişim çizgisinden ve hangi uç düğümden doğduğu. `chain_end_uncertainty` türü zaten yükseltilmiş bir kayıt olduğu için kart, dilim 2'nin verdiği `ChainEndUncertainty` teslim kaydını (zincir üyeleri, alan tabanı bağlamı, ileri atıf denetiminin sayıları) olduğu gibi taşır. İddia sürümlenir; iddiaya özgü bir arama (`kill_search`) üç yolu birleştirir — mevcut sorgu derleyiciyle yöntemsel komşulara ve yakın uygulamalara bakan sorgular (README adım 5), dilim 2'nin zaten hesapladığı alan tabanı (alandaki en güçlü önceki çalışma) ve dilim 2'nin `citation_expansions` mekanizmasının yeniden kullanımıyla adayın en yakın çalışmalarının doğrudan atıf komşuları (§2, §7) — ama araştırmanın ana discovery'sinden ayrı bir kapsamda kalır; bulunan yakın çalışmalar taranır, PDF'leri toplanır ve bir iddia–pasaj matrisiyle değerlendirilir; kod bu matristen `closed` / `narrowed` / `open` durumunu türetir (dördüncü bir durum, `undecided`, sahibe soruluyor — §6); sahip gerekçeyle bu durumu değiştirebilir. Dilim 2'nin yükseltme için eklediği ileri atıf denetimi bir kill-search **değildir**; `kill_search_status` yükseltmeden sonra da `not_run` kalır, yalnız bu dilimin kendi `kill_search` run'ı koşunca değişir (§4). Rapor bölüm VI/VII bu durumu okur ve yasak sözcük gevşemesi yalnız gerçekten koşmuş, sınırları yazılı bir aramadan sonra `open` için açılır. Kill-search kullanıcının başlattığı, bütçeli, tek adaya özgü bir eylemdir; hiçbir sıradan soru ya da her aday için otomatik çalışmaz. Deney tasarımı ve yürütmesi bu dilimde de "yok" kalır; karttaki doğrulama planı bir deney tasarımı değildir, hangi kontrolün iddiayı destekleyeceğinin/daraltacağının/zayıflatacağının ifadesidir (§16 soru 10).

## 1. Kodda bugün olan

| Parça | Doğrulanan durum | Bu dilimde kullanımı |
|---|---|---|
| `workflow/flow.py::_discovery` | `search_plan` model adımı → `query_compiler.compile_queries` ile derlenen sorgular saklanır (resume aynı sorguları arar) → her sorgu için `_search` (D18: bir arama başarısız olursa kaydedilir, diğerleri sürer) → `screening` model adımı parti parti (`SCREENING_BATCH`) → isteğe bağlı `_source_similarity` | `kill_search` run'ı bu akışın iskeletini birebir alır (plan→arama→tarama), ama araştırmanın `scope_revision`'ına değil bir `candidate_version_id`'ye bağlanır ve kendi tablolarına yazar (§2, §10) |
| `providers/query_compiler.py::compile_queries(plan, providers, limit)` | Girdi yalnız `plan["concepts"]` (tam bir `core`, geri kalanı `mechanism`/`method`/`outcome`/`context`/`adjacent_field`) ve `plan["providers"]`; sağlayıcı başına söz dizimini `query_rules.query_issues` ile denetler | Değişmeden çağrılır; `KillSearchPlan` çıktısı `SearchPlan`'la aynı `concepts`/`providers` biçimini taşır (§9) |
| `providers/query_rules.py` | Sağlayıcı başına söz dizimi kuralları (OpenAlex OR belirsizliği, arXiv operatör sınırı, Scopus alan grubu, vb.) | Aynen kullanılır; kill-search sorguları da bu denetimden geçmeden gönderilmez |
| `flow.py::_search` | Sağlayıcı çağrısı, D18 hata kaydı, `store.record_search` ile DOI birleştirmesi | Parametrik hale getirilip `kill_search` run'ında yeniden kullanılır; bulunan kayıtlar araştırmanın `works`/`candidates`'ına DOI ile birleşir (aynı kütüphane), ama tarama kararı ayrı bir tabloya yazılır (§2) |
| `candidates` tablosu (`0001_initial.sql`) | `id` öneki `cnd_`, "tarama adayı" (bir kaynağın araştırmadaki arama sonucu satırı); `UNIQUE(research_id, source_version_id)` | **Ad çakışması uyarısı:** research-methods.md'deki "aday kartı" (bir araştırma fikri) bambaşka bir kavramdır. Bu notta ikisini ayırmak için "tarama adayı" (`candidates`, `cnd_`) ve "araştırma adayı" (yeni `research_candidates`, `rcd_`) terimleri kullanılır; ikinci tabloya asla `candidates` denmez |
| `runs.stage` CHECK (`0022`+) | `intake, discovery, screening, inspection, answer, extraction, synthesis, candidate, claim_check, export` | `candidate` ve `claim_check` aşamaları P1 planından beri şemada duruyor ve hiç kullanılmadı; bu dilim onları kullanan ilk iştir (`claim_decomposition`/`kill_search` → `candidate`, `claim_assessment` → `claim_check`) |
| `pdf_collection` run'ı (D49, `0028`) | Dahil kaynakların açık erişim PDF'lerini toplar; `PdfReadiness.tsx` durumu gösterir | Kill-search'ün bulduğu kaynaklar için de kullanılır, ama `target_json`'a isteğe bağlı bir kapsam eklenir (§2); araştırmanın dahil kaynak listesine dokunmaz |
| Pasaj sıralama (lexical + semantik RRF, `fuse_rankings`) | Yanıt ve tablo doldurma aynı sıralamayı kullanıyor | Claim assessment girdisi için sorgu terimleri soru yerine iddia öğelerinden gelir; fonksiyon değişmez |
| `grounded_answer` / `answer_review` / `cell_extraction` (`EvidenceCellDraft`) | `_model_step`, `StepInput` zarfı, `locate_anchor`, allowlist denetimi, kısa kimlik tutamaçları (D12) | Aynı desen `claim_decomposition`, `kill_search_plan`, `kill_search_screening` (ScreeningProposal'ı yeniden kullanır), `claim_assessment` için tekrarlanır |
| `workflow/tables.py`, `evidence_cells`/`cell_revisions` (P5 dilim 1) | Hücre = revizyonlar dizisi + geçerli işaretçi; model yalnız boş hücreyi doldurur, insan kararı üstündür | İddia–pasaj matrisi hücreleri aynı revizyon mantığını izler: kod türetir, sahip gerekçeyle üzerine yazar (§6) |
| `domain/skill.py::RUNTIME_FILES` | `task_type → (dosya listesi)` sözlüğü; paket hash'i yalnız bu sözlükte adı geçen dosyalardan hesaplanır | Yeni görev türleri eklenir; `references/candidate-check.md` yeni dosya (§9) |
| `SKILL.md` | "Literatür sentezi, aday geliştirme, iddiaya özgü kill-search ve deney tasarımı **yok**" der; `capability_notice` bunu yanıtta bildirir | Bu dilim yalnız "iddiaya özgü kill-search" ve "aday geliştirme"yi, **yalnız `report_gaps`'ten açılan adaylar için** kullanılabilir hâle getirir; deney tasarımı/yürütmesi ve serbest fikir üretimi (sıradan bir soru için otomatik aday geliştirme) "yok" kalır (§9) |
| `contracts/research/*.schema.json` | Kapalı şema (`additionalProperties: false`), zorunlu alanlar, `common.schema.json`'daki paylaşılan `$defs`, `SCHEMA_VERSIONS`/`TASK_OUTPUTS` sözlükleri (`domain/contracts.py`) | Üç yeni şema eklenir; `TASK_OUTPUTS["kill_search_screening"] = ("ScreeningProposal",)` gibi mevcut bir şemayı yeni bir görev türüne bağlamak da örnek olarak var (`screening`) |
| `p6-report-design.md` §7, §10 | `report_gaps(id, report_id, gap_id, kind, text, basis_json, provenance_json, kill_search_status)`; VI/VII'nin yasak sözcük listesi yalnız kill-search koşmadan gevşemez | Bu dilimin tek sabit arayüzü; §5'te nasıl bağlandığı yazılı |
| `p6-report-design.md` §12 (17 Eylül 2026 güncellemesi) | Dilim numaraları değişti: dilim 2 "Chain of Ideas: alan tabanı ve kanıta bağlı gelişim çizgileri" (`p6-slice2-chain-of-ideas.md`, artık yazılmış); dilim 3 bu not; `report_gaps.kind` kapalı `CHECK` değil, kod denetimli genişleyebilir bir alan | Adaylar dört `kind`ten gelebilir (§1 üstteki paragraf) |
| `README.md` "Selected synthesis method: Chain of Ideas" (14 Eylül 2026 sahip kararı) | Altı adımlı uyarlama: alan haritası → gelişim çizgileri → çizgilerden aday sentezi → **kullanıcı yönlendirmesi ve amaç/mekanizma/değerlendirme** → **iddiaya özgü kill-search (alan + yöntemsel komşular + yakın uygulamalar)** → hayatta kalan/daralan sorunun koşullu hipotez, varsayım, doğrulama planıyla sunulması | Bu dilim adım 4'ün "kart açıldıktan sonra düzenleme" kısmını, adım 5'in tamamını, adım 6'nın "doğrulama planı" kısmını kurar; adım 4'ün "yükseltme" kısmı dilim 2'nindir (§2, §16 soru 9–10) |
| `p6-slice2-chain-of-ideas.md` §4.4, §4.5, §4.7, §5, §16 | `chains`/`chain_members`/`chain_links`/`chain_link_revisions`/`chain_link_evidence`/`chain_end_uncertainties`/`citation_expansions` gerçek şeması; `no_continuation_in_corpus` işareti yalnız çizgi görünümünde, `report_gaps`/aday adayı olması iki koşula bağlı (§4.4); dilim 3'e `ChainEndUncertainty` teslim kaydı (§16); `chain_links.relation` kapalı listesi | Bu notun §2, §5, §7, §9, §10, §16 bölümleri gerçek adlarla güncellendi; çakışan yer yok (§15.2) |

`report_gaps` tablosu henüz migration olarak yok (dilim 1 uygulanmadı); bu not onu var sayan bir tasarımdır ve dilim 1'in gerçek sütun adlarıyla küçük farklar taşıyabilir (§15.1). Dilim 2'nin gelişim çizgisi tabloları da henüz migration değil (dilim 2 de bir tasarım notu), ama şemaları artık kesin; bu not onlara gerçek adlarıyla değinir (§10, §15.2).

## 2. Kill-search bu bağlamda ne demek

Görevin önerdiği yedi parçalı ayrıştırma incelendi ve şu şekilde kabul edildi; her parça ya bugünkü koddan **aynen** ya da onun **iskelet biçimini kopyalayarak** kurulur, hiçbiri sıfırdan yeni bir mimari değildir. README'nin Chain of Ideas uyarlamasının 4. adımı ("kullanıcı araştırma yönünü belirler, sonra her adayın amacını, mekanizmasını ve değerlendirmesini tarif eder") bir model adımı değil bir **akış adımıdır**; aşağıya adım 0 olarak eklendi.

0. **Kullanıcı yönlendirmesi** (akış adımı, model çağırmaz; iki ayrı anı vardır).
   - **0a. Yükseltme, çizgi kökenli bir aday için dilim 2'nin kendi işidir, bu dilimin değil.** Dilim 2'nin çizgi görünümü bir düğümü `no_continuation_in_corpus` diye işaretler; bu **kendiliğinden bir aday değildir**. Yalnız (i) o düğüm için tamamlanmış bir ileri atıf denetimi (`citation_expansions`, `direction='forward'`, `status='completed'`) `chain_end_uncertainties.forward_check_id`'ye eklenmiş **ve** (ii) sahip düğümü açıkça yükseltmiş (`chain_end_uncertainties.promoted_at`/`promoted_by='owner'`) ise bir `report_gaps` satırı (`kind='chain_end_uncertainty'`) doğar. Bu dilim yalnız **yükseltilmiş** kayıtları tüketir; yükseltmeyi kendisi yapmaz, tekrarlamaz ya da atlayamaz.
   - **0b. Kart açıldıktan sonra düzenleme, her kökende bu dilimin işidir.** Aday hangi türden açılırsa açılsın (dört `kind`'ın hepsi), sahip `claim_decomposition`'ın taslak çıktısını kill-search başlamadan önce düzenleyebilir: amaç/mekanizma/değerlendirmeyi değiştirebilir, `claim_decomposition`'ı bir daha çağırıp alternatif biçimler isteyebilir (§16 soru 9). Kill-search bu düzenlemeden **sonraki** hâle bakar; sahip hiçbir şey değiştirmezse ilk çıktı kullanılır.
1. **`claim_decomposition`** (model adımı, yeni, tek çağrı — `research_title` gibi hafif bir run; sahip alternatif isterse ikinci kez çağrılabilir, §7). Bir `research_candidates` satırını (bir `report_gaps` satırından "İncele" ile açılmış) sürümlü bir iddiaya çevirir: `claim_statement`, `conditions`, `elements` (iddiayı test edilebilir parçalara ayırır), `nearest_simple_explanation`, `critical_assumption`, `pathway`, `validation_plan` (README adım 6'nın istediği doğrulama planı; bir deney tasarımı değildir, §16 soru 10). Aday `chain_end_uncertainty` türündeyse StepInput'a dilim 2'nin verdiği `ChainEndUncertainty` teslim kaydı da girer — zincir üyeleri, alan tabanı bağlamı, ileri atıf denetiminin sayıları (§5); kod bu kaydın alanlarını değiştirmez, olduğu gibi geçirir. research-methods.md §4'teki "geçici hipotez kill-search öncesinde yazılabilir" kuralı budur.
2. **`kill_search_plan`** (model adımı, yeni). `SearchPlan` ile **aynı `concepts`/`providers` biçimini** üretir, ama sorunun değil iddianın kavram sözlüğünü yazar ve README adım 5'in "yöntemsel komşular ve yakın uygulamalar" kısmını hedefler (`adjacent_field` rolündeki kavramlar bunun içindir); `query_compiler.compile_queries` değişmeden çağrılır. Ayrı şema, çünkü `StepInput` içeriği (iddia, soru değil) ve saklanan kayıt (`kill_searches`, `report_gaps` değil) farklıdır. README adım 5'in "alandaki en güçlü önceki çalışma" kısmı bu adımı beklemez: `chain_end_uncertainty` kökenli bir adayda `field_baseline_context` (dilim 2'nin zaten hesapladığı `field_baseline_selections`) doğrudan taranacak adaylara eklenir, yeniden aranmaz.
3. **Sağlayıcı aramaları**, `_search`'ün aynısı, ama `kill_search` run'ının kendi adım anahtarlarına yazar. Bulunan kayıtlar DOI ile **aynı kütüphaneye** (`works`/`source_versions`/`candidates`) birleşir — araştırmanın ana discovery'si aynı kaynağı zaten bulmuşsa `candidates`'ın `UNIQUE(research_id, source_version_id)` kısıtı sayesinde ikinci bir satır açılmaz. Ayrı olan, hangi kaynağın bu iddia için "yakın çalışma" sayıldığıdır (madde 4).

   **Üçüncü avenue: `citation_expansions` yeniden kullanımı (§7, dilim 2 §4.7'nin §18 soru 10'u "a" ile kapandığı varsayımıyla).** Sorgu derlenmiş arama yeni kaynak bulur, alan tabanı bilinen güçlü kaynakları verir; ikisi de bir çalışmanın **doğrudan atıf komşularını** (kim ona atıf yapıyor, o kimi kaynak gösteriyor) yakalamaz — bu tam olarak D55'in ölçtüğü düşük geri çağırım sorunudur (dilim 2 §0, §4.7). `kill_search`, adayın kendi uç düğümünü (varsa) ve query-compiled aramanın bulduğu en iyi birkaç yakın çalışmayı, dilim 2'nin **aynı** `citation_expansions` tablosuna ve **aynı** OpenAlex `referenced_works`/`filter=cites:` çağrısına yazarak genişletir; yeni bir mekanizma kurulmaz. Tek fark **hangi run'ın istediğidir**: `citation_expansions.run_id` bu kez `kill_search` kind'ındaki run'ı gösterir (`chain_expansion` kind'ında ayrı bir run açılmaz), bu yüzden bulunan adaylar dilim 2'nin sıradan taramasına değil **bu dilimin `kill_search_screening`'ine** (§4) gider ve `claim_search_memberships`'e yazılır, araştırmanın `selections`'ına asla girmez. Dilim 2'nin §18 soru 10'u "b" ya da "c" ile kapanırsa (genişletme ayrı bir dilime kalır ya da hiç yapılmaz), bu adım atlanır ve kill-search yalnız sorgu derlenmiş aramaya ve alan tabanına dayanır; bu, notun ilk sürümündeki tek-avenue tasarımıdır ve geri düşülecek varsayılan budur.
4. **Tarama, soruya değil iddiaya karşı.** Yeni görev türü `kill_search_screening`, çıktı şeması olarak **`ScreeningProposal`'ı aynen kullanır** (`TASK_OUTPUTS["kill_search_screening"] = ("ScreeningProposal",)`); farklı olan yüklenen yöntem dosyası (`candidate-check.md`, soru değil iddiaya göre tarar) ve kararların yazıldığı tablodur: `claim_search_memberships`, **araştırmanın `selections`/`corpus_memberships`'inden ayrı** (§16 soru 2). Böylece kill-search'ün taraması araştırmanın dahil kaynak listesini hiç etkilemez.
5. **PDF toplama ve pasaj sıralama.** `pdf_collection` run'ı **aynen** kullanılır; `target_json`'a isteğe bağlı `candidate_version_id` eklenir, verildiğinde toplanacak kaynak kümesi "araştırmanın dahil kaynakları" yerine "bu iddia için `include` işaretli `claim_search_memberships`" olur. Pasaj sıralaması (`fuse_rankings`) değişmez; sorgu terimleri `claim_elements.text`'ten gelir.
6. **`claim_assessment`** (model adımı, yeni run kind, `cell_recheck`in `table_fill`den ayrı bir run olması gibi ayrı). Girdi `EvidenceCellDraft`'a yakın: her (öğe, yakın çalışma) çifti için pasajlar verilir; erişilemeyen çiftler **modelden önce kod tarafından** `insufficient_access` yazılır (tıpkı `inaccessible`'ın `system_fill` olması gibi, D37). Model yalnız erişilebilir çiftleri değerlendirir: ilişki (`explicit_support` / `reasoned_inference` / `partial_match` / `uncertain`), koşul hizası, alıntı.
7. **Durum türetme kod işidir**, model çağırmaz (§6). Sahip gerekçeyle üzerine yazabilir; her iki yol da `candidate_status_history`'e yazılır.

**Yeniden kullanılan aynen:** `query_compiler`, `query_rules`, `_search`'ün gövdesi, `pdf_collection`, `fuse_rankings`, `_model_step`/`StepInput` zarfı, `locate_anchor`, D12 kısa tutamaç deseni, evidence tablosunun revizyon mantığı, dilim 2'nin `citation_expansions` tablosu ve OpenAlex `referenced_works`/`filter=cites:` çağrısı, dilim 2'nin `field_baseline_selections`'ı.
**Yeni gereken:** üç run kind (`claim_decomposition`, `kill_search`, `claim_assessment`), on bir tane yeni tablo (§10) — bunlardan biri (`report_stable_gaps`) dilim 4'ün tasarımından bu dilimin kendi migration'ına erken benimsenmiştir (§15.3), geri kalan onu bu dilime özgüdür —, üç yeni JSON Schema, bir yeni yöntem dosyası, `pdf_collection`'ın kapsam parametresi. Kullanıcı yönlendirmesi (adım 0b) kod değil arayüz işidir; adım 0a dilim 2'nin kendi arayüzüdür (§11'de ayrıca yazılıyor).

## 3. Senaryolar

**S0. Sahip bir Chain of Ideas ucundan aday geliştiriyor.** Dilim 2'nin çizgi görünümünde bir uç düğüm koddan `no_continuation_in_corpus` diye işaretli — henüz bir aday değil. Sahip "Check citing works" der (dilim 2'nin ileri atıf denetimi) → sonuç tamamlanır ve `chain_end_uncertainties.forward_check_id`'ye eklenir → sahip düğümü açıkça yükseltir (`promoted_at`) → **ancak bu andan sonra** bir `report_gaps` satırı (`kind='chain_end_uncertainty'`) doğar ve rapor VI'da görünür. Sahip "İncele" der → `research_candidates` satırı dilim 2'nin `ChainEndUncertainty` teslim kaydıyla açılır (adım 0a bitti, adım 1 başlıyor) → sahip taslak amaç/mekanizma/değerlendirmeyi görmeden önce README adım 4 gereği isterse düzenler, isterse alternatif biçim ister (adım 0b, §16 soru 9) → `claim_decomposition` teslim kaydını alarak çalışır, kart "bu iddia şu çizgiden, şu uç düğümden doğuyor" der → kill-search üç yolu birleştirir: sorgu derlenmiş arama (yöntemsel komşular/yakın uygulamalar), alan tabanı (alandaki en güçlü önceki çalışma, yeniden aranmaz) ve `citation_expansions`'ın yeniden kullanımıyla uç düğümün doğrudan atıf komşuları.

**S1. Sahip bir `corpus_absence` adayını inceliyor.** Rapor bölüm VI'da bir satırda "İncele" tıklanır → `research_candidates` satırı açılır (kaynak: `report_gaps.text`+`basis_json`) → `claim_decomposition` çalışır → sahip taslak iddiayı okur, gerekirse düzenler → "Kill-search başlat" ile `kill_search` run'ı bütçe ve tahmini maliyet gösterip başlar → sonuçta 3 yakın çalışma bulunur, 1'i tarandıktan sonra dahil → PDF toplanır (1/1 açık erişim) → `claim_assessment` matrisi: iddianın 2 öğesinden biri `explicit_support`, öteki `uncertain` → kod `narrowed` türetir ("bir öğe destekleniyor, ötekinde farklı koşul") → VII'deki bağlı yön "ele alınmış" rozeti alır (§16 soru 7).

**S2. Sıfır sonuç.** Kill-search'ün bütün sorguları `completed` döner ama tarama hiçbir kaynağı `include` yapmaz → matris boş → kod `open` türetir, metni "şu tarihte şu sağlayıcılarda şu sorgularla eşleşme bulunamadı" biçimindedir (bounded no-match); "novel"/"gap" sözcükleri yine yasaktır, yalnız "cevaplanmamış yön adayı, aranmış ve eşleşmemiş" denir.

**S3. Sağlayıcı hatası.** Sorguların biri `rate_limited` döner, ötekiler `completed`. D18 kuralı aynen uygulanır: başarısız sorgu kaydedilir, diğerleri sürer. Eğer **hiçbir** sorgu başarılı olmazsa run duraklar ve durum `not_run` kalır (arama hiç sayılmaz); en az biri başarılıysa S2/S4 gibi devam eder ama VIII benzeri bir "N sorgudan M'si başarısız" notu taşınır.

**S4. Kritik PDF'e erişilemiyor.** Tarama bir kaynağı `include` yapar ama PDF açık erişimde yok ve sahip yüklemedi. O (öğe, kaynak) hücresi `insufficient_access` kalır. Eğer bu hücre iddianın **belirleyici** bir öğesiyse (yani onsuz örtüşüp örtüşmediği söylenemez), kod `undecided` türetir — `closed` ya da `open` değil (§6, research-methods.md: "erişim yetersizliği ret değil, karar verilememedir").

**S5. Aynı sonuç başka terminolojiyle.** Yakın çalışma farklı sözcüklerle aynı mekanizmayı anlatıyor; tarama modeli bunu yakalar (candidate-check.md'nin görevi), matriste `explicit_support` yazılır, koşullar hizalıysa kod `closed` türetir. Terminoloji farkı tek başına `partial_match`'e düşürülmez; bu, R10'daki ekilmiş hata sınıflarından biridir (§13'te sınanır).

**S6. Çok iddialı aday, tek örtüşen iddia.** Bir yakın çalışma adayın 3 öğesinden yalnız 1'ini karşılıyor. Kod bulguyu yalnız o öğenin hücresine yazar; adayın **bütün ailesini** kapatmaz (research-methods.md: "bu fikir zaten var" bir iddiayı kapatır, tüm aileyi silmez). Diğer 2 öğe için matris boş kalırsa durum `narrowed` ya da `open` olur, `closed` olmaz.

**S7. Çekici ama geçersiz uzak analoji.** Sorgu genişletmesi (adjacent_field) uzak bir alandan bir çalışma getirir; tarama modeli mekanizmanın taşınmadığını (koşul uyuşmazlığı) not eder → `condition_alignment: different_conditions` → kod bunu `explicit_support` gibi saymaz, `closed`e katkı yapmaz.

**S8. Farklı koşullarda ters sonuç.** İki yakın çalışma birbirine karşıt sonuç veriyor; matriste ikisi de `partial_match`, koşul hizası `different_conditions` — kod bunu "çelişki" ilan etmez (T11'in bu dilimdeki, iddia düzeyindeki karşılığı; T11'in çizgi bağları üzerindeki karşılığı dilim 2'nindir); metin "farklı koşullarda farklı sonuç" der.

## 4. Kurallar

research-methods.md §4–§6'dan doğrudan taşınan, kodun ve yöntem dosyasının uyacağı değişmezler:

- Örtüşme/öncelik (aynı iddia zaten var), geçerlilik (karşı kanıt) ve değer (önemsizlik) ayrı bulgulardır; tek bir "kill skoru"na indirgenmez. Matris hiçbir zaman tek bir sayı üretmez; her hücre kendi ilişkisini taşır.
- "Bu zaten var" bir iddiayı kapatır, adayın bütün ailesini otomatik silmez (S6).
- Kalan anlamlı bir koşul farkı yeni bir aday **sürümü** açar; salt isim/veri seti değişikliğiyle fikir kurtarılmaz (§16 soru 4).
- Yetersiz erişim "karar verilemedi" demektir, "reddedildi" değil (S4, §6).
- Bir öğenin başka yerde ayrı ayrı bulunması, birleşik iddianın zaten kurulmuş olduğunu göstermez (S6).
- Kaynakta açıkça yazılan (`explicit_support`) ile analistin çıkardığı (`reasoned_inference`) ayrı tutulur; ikisi matriste farklı sütun/etikettir.
- Sıfır sonuç, servis hatası ve erişilemeyen kritik PDF üç ayrı sonuçtur; hiçbiri tek başına özgünlük üretmez (S2–S4).
- İddia/sürüm değişince önceki kill-search sonucu yeni sürüme otomatik taşınmaz; bağımlı bulgular yeniden incelenir (§16 soru 4).
- Arama ve revizyon bütçesi sonludur; bütçe dolunca kalan belirsizlikle durulur, "hayatta kalan fikir üretme" zorunluluğu yoktur (§7).
- Kronoloji ya da atıf tek başına bir gelişim ilişkisi kanıtı değildir (README adım 2, T11); bir çizgi ucundan gelen adayın `claim_decomposition`'ı bu bağı dilim 2'den olduğu gibi devralır, kill-search'ün kendisi çizginin bağlarını yeniden kanıtlamaz — yalnız iddianın kendi kill-search'ünü yapar.
- Doğrulama planı bir deney tasarımı değildir; hangi kontrolün iddiayı destekleyeceğini, daraltacağını ya da zayıflatacağını söyler, apparatus/protokol/örneklem/yürütme adımı önermez (README adım 6). Deney tasarımı ve yürütmesi bu dilimde de "yok" kalır (§9.2).
- **Yükseltme için eklenen ileri atıf denetimi bir kill-search değildir.** Dilim 2'nin `no_continuation_in_corpus`'u `report_gaps`'e taşımak için gerektirdiği tamamlanmış ileri atıf denetimi (`citation_expansions`, `direction='forward'`) yalnız o düğüme kim atıf yaptığını sayar; adayın iddiasını başka bir çalışmaya karşı denetlemez. `research_candidates.status` ve `report_gaps.kill_search_status` bu denetimden ve yükseltmeden sonra da `not_run` kalır; yalnız bu dilimin kendi `kill_search` run'ı koştuğunda değişir (dilim 2 §4.4, bu notun §6'sı).

## 5. Aday kartı, sürümleme ve `report_gaps` ile ilişki

**İki tablo, tek doğruluk kaynağı — ve kararlı bir üçüncü kimlik katmanı.** `report_gaps` (dilim 1) rapor **bölümünün** o anki metnidir: bir rapor sürümüne ait, donmuş, ve dilim 1'in kuralıyla **her bölüm yeniden yazımında yeniden verilen** bir `gap_id` taşır (p6-report-design.md §4). Bu, `report_gaps.id`'yi bir adayın kalıcı kökeni yapmaya uygunsuz kılar: aynı gerçek soru raporun ikinci sürümünde farklı bir `report_gaps` satırı olur. Dilim 4'ün önerdiği (`p6-slice4-editing-stale-measurement.md` §5) kararlı kimlik katmanı bunun çözümüdür ve bu not onu **gap kısmı için** benimser: `report_stable_gaps` (kind + temel kümenin deterministik `basis_fingerprint`'i, `research_id` içinde benzersiz) rapor sürümleri arasında hayatta kalır, her `report_gaps` satırı bir `report_stable_gaps.id`'ye (`stable_gap_id`) bağlanır. `research_candidates`/`candidate_versions` (bu dilim) aday **kartının kendisidir**: rapordan bağımsız yaşar, sürümlenir, birden çok kill-search geçirebilir; `research_candidates.source_gap_id` doğrudan **`report_stable_gaps.id`'ye** bağlanır, tek bir `report_gaps.id`'ye değil (§10, §15.3). Sahip bir `report_gaps` satırında "İncele" derse, kod önce o satırın `stable_gap_id`'sini bulur (yoksa dilim 1'in yazma anında zaten çözmüş olması beklenir, §15.3), sonra o kararlı kimlikte bir `research_candidates` var mı diye bakar; varsa açar, yoksa yaratır. Böylece raporun ikinci sürümünde aynı soru yeniden "İncele" edilirse aynı aday kartı açılır, ikincisi yaratılmaz.

**Doğruluk kaynağı `research_candidates.status`'tur.** `report_gaps.kill_search_status`, kod tarafından `research_candidates.status` her değiştiğinde **aynı işlemde** kopyalanan bir görünüm sütunudur; model düzyazısını hiç değiştirmez. Böylece VI'nın bir satırındaki rozet ("not_run" → "narrowed") güncellenir ama o adayı anlatan cümleler aynı kalır — rapor sürümlü ve donmuşsa (`reports.status = 'valid'`), bu satırın **görünümü** güncellenir ama raporun donmuş metni ve `report_version`'ı değişmez; raporun bütünüyle bayat sayılıp sayılmayacağı (bölüm düzeyi `stale` işareti) dilim 4'ün konusudur, burada yalnız "durum sütunu canlı, metin donuk" ayrımı kurulur.

**Çizgi kökeni.** Bir aday `chain_end_uncertainty` türündeyse, `research_candidates.chain_end_uncertainty_id` dilim 2'nin `chain_end_uncertainties(id)` (`ceu_`) satırına işaret eder — bu satır zaten yükseltilmiştir (§2 adım 0a), yani `forward_check_id` ve `promoted_at` doludur. Kart yeni bir kopya tutmaz; dilim 2'nin `ChainEndUncertainty` teslim kaydını (§16'daki alanlarıyla: `chain_id`, `source_version_id`, `source_key`, `uncertainty_text`+`uncertainty_evidence`, `chain_members`, `field_baseline_context`, `forward_check`) olduğu gibi gösterir ve "hangi çizgiden, hangi uç düğümden doğdu" diye özetler. Zincirin kendi bağlarını (kimin kimi nasıl genişlettiğini) göstermek isteyen bir sahip dilim 2'nin çizgi görünümüne `chain_id` üzerinden gider; bu kart ayrı bir bağ kopyası tutmaz. `pathway` (assumption/disagreement/transfer/method_improvement/other) bu kartın **kendi** niteliksel etiketidir; dilim 2'nin `chain_links.relation` kapalı listesiyle (`extends`/`relaxes_assumption`/`changes_method`/`new_domain_or_condition`/`corrects_or_contradicts`/`independent_parallel`) örtüşür ama aynı liste değildir — dilim 2 kendi notunda bunu açıkça ayırır (§16), bu not da ayrı tutar. Bir `report_gaps` satırından (çizgisiz, örn. `stated_limitation`) açılan aday için `chain_end_uncertainty_id` boş kalır.

**Sürümleme.** research-methods.md §4'ün aday kartı içeriği `candidate_versions`'a yazılır: iddia, koşullar, en yakın basit açıklama, kritik varsayım, alternatif açıklama, veri/araç gereksinimi, oluşma yolu (`pathway`), doğrulama planı (`validation_plan`). Bir `claim_decomposition` yeniden çalıştırılırsa (koşul değişti, sahip düzeltti) yeni bir `candidate_versions` satırı açılır; eski sürümün kill-search sonucu (`kill_searches`, `claim_matrix_cells`) o eski sürüme bağlı kalır ve yeni sürüme kopyalanmaz (§4). `research_candidates.status`, **geçerli sürümün** son durumu olarak tutulur; sürüm değişince durum `not_run`'a döner ve eski sürümün geçmişi `candidate_status_history`'de görünür kalır.

## 6. Durum türetme kuralları

Bu kurallar `report_gaps`'in dört türünün hepsi için geçerlidir. `chain_end_uncertainty` (dilim 2), README adım 5'in doğrudan hedeflediği türdür — kill-search'ün "asıl işi" budur. `stated_limitation` için kill-search'ün gerekip gerekmediği ayrıca sorulur (§16 soru 6), çünkü kaynağın kendi belirttiği sınırlama sonraki bir çalışmayla çoktan çözülmüş olabilir; bu, matristen türetilen durumu değiştirmez, yalnız kill-search'ün o türde otomatik önerilip önerilmeyeceğini etkiler.

Girdiler: `kill_searches.outcome` (arama hiç başarılı sorgu üretti mi), `claim_search_memberships` (kaç yakın çalışma dahil edildi), `claim_matrix_cells` (`coverage`, `relation`, `condition_alignment`).

| Girdi durumu | Türetilen durum | Gerekçe |
|---|---|---|
| Hiçbir kill-search çalıştırılmadı | `not_run` | Rapor tasarımının varsayılanı |
| Kill-search çalıştı ama **hiçbir** sorgu başarılı olmadı (hepsi hata/`outcome_unknown`) | `not_run` (arama sayılmaz) | Bir servis hatası "aranmış ve bulunamamış" değildir (S3) |
| En az bir sorgu başarılı, dahil edilen yakın çalışma yok **veya** hiçbir hücre `explicit_support`/`reasoned_inference`/`partial_match` değil | `open` | Sınırları yazılı bir "eşleşme yok" (S2); "novel" denmez |
| Bir öğenin **belirleyici** (kod: iddianın `elements` listesindeki her öğe belirleyicidir, aksi işaretlenmemişse) hücresi `insufficient_access` | `undecided` | Erişim yetersizliği ret değildir (S4); diğer hücreler ne derse desin bu öncelenir |
| En az bir yakın çalışmada **her** öğe `explicit_support` veya `reasoned_inference`, hepsinde `condition_alignment: aligned` | `closed` | Bu iddiayı bütünüyle karşılayan bir çalışma bulundu (S5) |
| En az bir öğe desteklenmiş (`explicit_support`/`reasoned_inference`, `aligned`) ama en az bir öğe desteksiz **veya** bir yakın çalışmada `condition_alignment: different_conditions` | `narrowed` | Kısmi örtüşme; kalan fark yeni bir sürüm gerektirebilir (S1, S6, S8) |

**`undecided`, rapor tasarımının üç durumuna (`narrowed`/`closed`/`open`) eklenen dördüncü bir durumdur** — p6-report-design.md §2 karar 1 yalnız üçünü kabul etmişti. Bu notun önerisi `undecided`'ı eklemektir, çünkü onsuz erişim yetersizliği ya `open`e (yanlış: "aranmış, bulunamamış" değil "okunamamış" demektir) ya da `not_run`a (yanlış: arama gerçekten koştu) sıkışır; ikisi de research-methods.md'nin "erişim yetersizliği ret değil karar verilememedir" kuralını çiğner. Bu, §16 soru 1'de sahibe soruluyor; `report_gaps.kill_search_status`'un CHECK kısıtının genişletilmesi dilim 1'e bağımlıdır (§15.1).

Sahip her zaman gerekçeyle üzerine yazabilir (`candidate_status_history.decided_by = 'human'`); bir sonraki `claim_assessment` çalışması yeni bir kod satırı yazar ama insan satırını silmez, yalnız `research_candidates.status`'u günceller (evidence table'daki `human_edit`/`model_proposal` ayrımının aynısı, §7'de "kabul" yerine burada doğrudan geçerli sayılır çünkü aday kartı bir hücre gibi "öneri bekleyen" değildir — bu bir tasarım basitleştirmesidir, insan kararı üzerine gelen bir sonraki otomatik hesaplama sessizce ezmez, ekranda "kod X diyor, siz Y demiştiniz" karşılaştırması gösterilir).

## 7. Bütçe ve eş zamanlılık

Kill-search **kullanıcının başlattığı, tek adaya özgü, bütçeli** bir eylemdir; hiçbir sıradan soru için otomatik çalışmaz, her aday için otomatik çalışmaz (AGENTS.md: "Do not silently broaden an answer task into candidate-question development ... kill-search"). Sabit varsayılan bütçe (başlamadan gösterilir, tıpkı tablo doldurmanın "en fazla {m} çağrı" gibi):

| Adım | Model çağrısı | Sağlayıcı çağrısı |
|---|---|---|
| `claim_decomposition` | 1 (+1 onarım) | — |
| `kill_search_plan` | 1 (+1 onarım) | — |
| Sağlayıcı aramaları | — | en fazla 6 sorgu (mevcut `max_provider_requests` deseniyle aynı sınır mantığı) |
| Atıf genişletmesi (`citation_expansions` yeniden kullanımı, §2 madde 3) | — | geriye yön ek çağrı istemez (saklı `openalex_referenced_works_json`'dan); ileriye yön düğüm başına 1 çağrı, en fazla 3 düğüm (uç düğüm + sorgu aramasının bulduğu en iyi 2 yakın çalışma) → en fazla 3 ek çağrı |
| `kill_search_screening` | en fazla 2 parti (`SCREENING_BATCH` aynı sabit) | — |
| `claim_assessment` | yakın çalışma başına 1 çağrı, en fazla 10 yakın çalışma | — |

Alan tabanı bağlamı (`field_baseline_context`) zaten dilim 2'de hesaplanmış olduğu için burada ayrıca bir çağrı gerektirmez; doğrudan taranacak adaylara eklenir. Sahip alternatif biçim isterse (§16 soru 9, adım 0), `claim_decomposition` ikinci kez çağrılır — bu bütçeye ek +1 çağrıdır ve yalnız istenirse gerçekleşir; varsayılan tek biçimli akışta bu ek çağrı yoktur.

Süreç genelindeki model-çağrısı sınırlayıcısı (dilim 0, p6-report-design.md §2 karar 7) burada da paylaşılır: kill-search ve rapor/tablo doldurma aynı üst sınırdan pay alır. Aynı anda çalışabilecek kill-search sayısı bu paylaşılan sınırla dolaylı kısıtlıdır; ayrı bir "kaç aday eş zamanlı" sınırı önerilmiyor çünkü kill-search zaten tek adaya özgü ve kullanıcı başına bir tıklamayla başlar — art arda birden çok aday başlatılırsa hepsi aynı kuyruğa girer (bugünkü "tek etkin araştırma çalışması" kısıtına benzer, ama kill-search'ler araştırmanın ana `discovery`/`answer` run'larıyla aynı etkin-run kilidini **paylaşmaz mı** sorusu açık — önerilen: paylaşır, çünkü aynı SQLite bağlantısı ve aynı OS advisory lock kuralı geçerli, ayrı bir kilit türü eklemek D18/D46 gibi mevcut kesinti garantilerini karmaşıklaştırır).

## 8. Kim neyi doğrular

| Kural | Kodun doğruladığı yapı | Modelin değerlendirdiği anlam | Doğrulanmayan |
|---|---|---|---|
| İddia ayrıştırması | Öğeler allowlist'teki kaynak/pasajlara dayanır, sayı sınırı içinde | İddianın doğru ve test edilebilir biçimde bölündüğü | Bölümlemenin bilimsel olarak tam olduğu |
| Sorgu derleme | `query_rules.query_issues` her sorguyu geçer | Kavram sözlüğünün iddiayı doğru temsil ettiği | Geri çağırım (recall) — ölçülmedi (§13) |
| Tarama | `ScreeningProposal` şeması, allowlist | Bir kaynağın gerçekten "yakın çalışma" olduğu | Taranmayan kaynaklar arasında yakın çalışma kalmadığı |
| Matris hücresi | Alıntı pasajda birebir var; `insufficient_access` yalnız sistemce yazılır | İlişki türü, koşul hizası doğru mu | Alıntının bağlamının doğru aktarıldığı |
| Durum türetme | §6 tablosundaki mantık kod içinde çalışır | — (kod işidir) | Matrisin kendisinin doğruluğu — yanlış matris yanlış durum üretir |
| Sahip override'ı | Gerekçe zorunlu alanı dolu | — | Override'ın kendisinin haklılığı |
| Rapor bağlantısı | `kill_search_status` senkron kopyalanır, yasak sözcük listesi hâlâ taranır | — | `open`in metninin abartısız olduğu (`report_review`'ın konusu, bu dilimde yeniden çalışmaz) |

## 9. Yöntem paketi

### 9.1 Görev türleri ve yüklenen dosyalar (`domain/skill.py::RUNTIME_FILES`)

```python
RUNTIME_FILES = {
    ...  # değişmeyenler aynen kalır
    "claim_decomposition": ("SKILL.md", "references/candidate-check.md"),
    "kill_search_plan": ("SKILL.md", "references/candidate-check.md"),
    "kill_search_screening": ("SKILL.md", "references/candidate-check.md"),
    "claim_assessment": ("SKILL.md", "references/candidate-check.md"),
}
```

Tek yeni referans dosyası dört görevi de kapsar (evidence-table.md'nin `cell_extraction`+`table_columns`'ı kapsaması gibi).

### 9.2 `SKILL.md` değişiklikleri

Bugünkü satır: *"Literatürler sentezi..., aday geliştirme, iddiaya özgü kill-search ve deney tasarımı ya da yürütmesi **yok**."* Değişiklik:

- Görev tablosuna dört satır eklenir (`claim_decomposition`, `kill_search_plan`, `kill_search_screening`, `claim_assessment` → [candidate-check.md](../../methods/deixis-research/references/candidate-check.md) bölümleri).
- "Yok" cümlesi daralır: *"Literatür sentezi (idea chain'ler arası), sıradan bir soru için serbest aday geliştirmesi ve deney tasarımı ya da yürütmesi hâlâ **yok**dur. İddiaya özgü kill-search yalnız uygulamanın açtığı bir `research_candidates` kaydı için, `claim_decomposition`/`kill_search_plan`/`kill_search_screening`/`claim_assessment` görev türleriyle çalışır; bu görevler dışında bir soruya kendiliğinden aday ya da kill-search başlatılmaz."*
- "Sıradan bir soru için aday geliştirme/özgünlük değerlendirmesi başlatma" cümlesi aynen kalır (`grounded_answer`/`answer_review` için).

### 9.3 `references/candidate-check.md` (yeni, tam metin)

```markdown
# Candidate check

A research candidate is one idea the user chose to investigate further, opened
either from a report's candidate-unanswered-aspect record or from a
development-chain end the user and the application have already promoted (a
completed forward-citation check plus the user's own action; you never see an
unpromoted chain end). You never open or propose a candidate yourself for an
ordinary question; if a question asks for that, follow SKILL.md's capability
notice instead. Everything here works on one candidate at a time, from the
StepInput's `candidate` and `claim` records, and — when the candidate came from
a chain — that chain's hand-over record: the chain's other members, the field's
already-identified strongest prior works (`field_baseline_context`), and the
forward-citation check's counts. You do not re-derive any of this; it is given.

The user may have already edited the candidate's working purpose, mechanism or
evaluation before asking for this step; work from what the StepInput gives you,
not from an earlier version you might recall.

## Claim decomposition

Goal: turn the candidate's text and basis into one versioned, testable claim.
`StepInput.requested_formulations` says how many formulations to write: 1 by
default, or 2 to 3 when the user asked to see alternatives to choose from
(this is the only branching this step does; you generate the options, the user
picks one — never rank or pre-select for them). Write that many independent
items in `formulations`, each complete on its own, not variations that only
differ in wording.

For each formulation:

1. Write `claim_statement`: one or two sentences, as narrow and checkable as the
   candidate's own basis supports. Do not broaden it into a bigger contribution
   than the candidate record states.
2. List `conditions`: the circumstances the claim is meant to hold under (a
   population, a scale, a parameter range, an assumption). Keep quantities and
   conditions attached to the element they belong to; do not drop them to make
   the claim sound more general.
3. Break the claim into 2 to 8 `elements`, each one mechanism, condition,
   outcome or parameter that a later search can check independently. An
   element that bundles two separable ideas should be split; the search that
   follows checks elements, not the whole claim at once.
4. Name `nearest_simple_explanation`: the simplest existing account that could
   already explain what basis you were given, without granting the new claim.
   If the candidate came from a chain, check the chain's other members and its
   `field_baseline_context` (the field's already-identified strongest prior
   work) before looking further — one of those may already be the simplest
   explanation. If you cannot state one from the given records, say so and set
   it to null; do not invent a precedent you cannot cite.
5. Name `pathway` (`assumption`, `disagreement`, `transfer`, `method_improvement`
   or `other`) — how the candidate arose. This is descriptive, not a gate: pick
   `other` rather than force-fitting one of the named paths. When the candidate
   came from a chain, this is usually the uncertainty the chain's own evidence
   (`uncertainty_text`) left open, not a new pathway you invent. This label is
   yours; it is not the same closed list the chain-building step uses for a
   link's relation, even where the two overlap.
6. Write `critical_assumption`: the one assumption that, if wrong, removes most
   of the claim's value. `alternative_explanation` and `data_or_tool_requirement`
   are optional; leave them null rather than guess.
7. Write `validation_plan`: the check, comparison or further reading that would
   most inform this claim — what would support it, narrow it or weaken it, and
   what a weak or absent result there would mean. This is not an experiment
   design: do not propose apparatus, protocols, sample sizes, instrumentation or
   execution steps. If the claim genuinely needs a designed experiment, say that
   a separately scoped experiment-design activity would follow, and stop there.

Cite the `source_ids`/`passage_ids` your decomposition rests on, including the
chain's own `uncertainty_evidence` passages when you used them. You do not
report which chain or which end node the candidate came from — the application
already knows that and does not ask you to repeat it.

## Kill-search plan

Goal: a concept vocabulary aimed at prior art for the claim you were given, not
the research question. Write exactly one `core` concept naming the claim's
central mechanism, plus other-role concepts from the claim's elements and
conditions. Include at least one `adjacent_field` concept naming a methodological
neighbor or an adjacent application the claim's mechanism could plausibly also
appear in — prior art is not only the claim's own field. The backend compiles
every provider query from this vocabulary and enforces provider syntax and call
limits; you do not write queries or judge whether a query "worked" — a
zero-result, a failed, and an unrun query are different outcomes the backend
tracks, and none of them is your decision to call novelty. If the candidate's
context includes `field_baseline_context`, do not write concepts to re-find
those works — they are already identified and added to screening directly;
write concepts for what is not yet known.

## Kill-search screening

Goal: decide, for each given candidate record, whether it is a close work for
the claim's elements — not for the research question. A close work addresses
at least one element with a comparable mechanism or condition; a work that
only shares the field or a keyword is not close. Use `include`, `exclude` or
`uncertain` exactly as in ordinary screening, with a reason and your evidence
basis. This decision does not touch the research's own included-source list.

## Claim assessment

Goal: fill the claim–passage matrix. You receive, for one close work, the
elements it may be relevant to and the supplied passages of that source. You
were not given every (element, source) pair — pairs without accessible text
are marked `insufficient_access` by the application before you see them, and
you never write that state yourself.

For each element you were given passages for, judge the relation:

- `explicit_support`: a passage states the same mechanism/outcome for this
  element, under comparable conditions.
- `reasoned_inference`: the passages do not state it outright, but you can
  derive it from what they do state. Say the inference in `note`.
- `partial_match`: the passage addresses the element but only part of it, or
  under conditions that only partly align.
- `uncertain`: the passages touch the element but you cannot judge the
  relation from what you were given.

Judge `condition_alignment` (`aligned`, `different_conditions`, `unclear`)
separately from `relation`. A result obtained under a different population,
scale or assumption is not the same claim even if the mechanism matches; say
`different_conditions` and let the difference stand, rather than forcing a
match or declaring a contradiction. Comparing conditions this way is the same
discipline as comparing table columns before calling two results consistent
or conflicting.

Every cell needs at least one `evidence` item — an `uncertain` relation still
cites the passage that leaves you uncertain. Terminology differing from the
candidate's own wording is not evidence against a match: judge the mechanism,
not the vocabulary. One element matching in one close work does not establish
that the whole claim is already known; each element's cell stands on its own,
and a candidate with several elements can have some closed and some still
open. Do not derive a claim's overall status yourself — the application
computes it from the matrix.

If an element has no accessible passage in any close work you were given, add
it to `insufficient_evidence` rather than guessing a relation for it.

Write `nearest_match_summary` in plain language, in the question's language
unless the StepInput says otherwise: which close work comes closest and on
which elements, without repeating every cell.
```

### 9.4 Sözleşmeler (`contracts/research/*.schema.json`, tam metin)

`common.schema.json`'a eklenen `$defs`:

```json
"research_candidate_id": { "type": "string", "pattern": "^rcd_[0-9A-Za-z]{8,40}$" },
"candidate_version_id": { "type": "string", "pattern": "^clv_[0-9A-Za-z]{8,40}$" },
"claim_element_ref": { "type": "string", "pattern": "^el[0-9]{1,2}$", "description": "Short in-output handle for one claim_elements row; the backend resolves it, as with grounded-answer claim_label (D12)." }
```

Çizgi kökeni artık modelin çıktısında taşınmaz (aşağıya bakın); `StepInput`'un `candidate` alanına dilim 2'nin `ChainEndUncertainty` teslim kaydı (§16, gerçek alan adlarıyla: `chain_id`, `source_version_id`, `source_key`, `uncertainty_text`, `uncertainty_evidence`, `chain_members`, `field_baseline_context`, `forward_check`) girer; bu, bu notta yeni bir `$def` gerektirmez, çünkü backend tarafından biliniyor ve modele yalnız okunmak üzere verilir, geri istenmez (`SearchPlan`'ın `research_id`'yi hiç istememesiyle aynı ilke).

**`claim-decomposition.schema.json`** (task_type `claim_decomposition`). `requested_formulations` StepInput'tan gelir (backend/arayüz denetler, model yazmaz); çıktı 1 ile `requested_formulations` arasında `formulations` öğesi taşır (§16 soru 9). Çizgi kökeni de StepInput'tan gelir ve çıktıda tekrarlanmaz (backend zaten bilir):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/claim-decomposition.schema.json",
  "title": "ClaimDecomposition",
  "description": "One or more alternative versioned, testable claim formulations decomposed from a research candidate opened by the user from a report's candidate-unanswered-aspect record (including a promoted chain-end uncertainty). Never produced for an ordinary question. The user chooses one formulation; unchosen ones are kept for audit, not silently discarded.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "step_input_id", "scope_revision", "skill_package_hash",
    "formulations", "source_ids", "passage_ids", "rationale"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.claim_decomposition.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "formulations": {
      "type": "array",
      "minItems": 1,
      "maxItems": 3,
      "description": "As many independent purpose/mechanism/evaluation formulations as StepInput.requested_formulations asked for. The user picks one; this step never ranks or pre-selects.",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "claim_statement", "conditions", "elements", "nearest_simple_explanation",
          "pathway", "critical_assumption", "alternative_explanation",
          "data_or_tool_requirement", "validation_plan"
        ],
        "properties": {
          "claim_statement": { "type": "string", "maxLength": 800 },
          "conditions": { "type": "array", "maxItems": 6, "items": { "$ref": "common.schema.json#/$defs/short_text" } },
          "elements": {
            "type": "array",
            "minItems": 2,
            "maxItems": 8,
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": ["element_ref", "text", "kind"],
              "properties": {
                "element_ref": { "$ref": "common.schema.json#/$defs/claim_element_ref" },
                "text": { "$ref": "common.schema.json#/$defs/short_text" },
                "kind": { "type": "string", "enum": ["mechanism", "condition", "outcome", "parameter"] }
              }
            }
          },
          "nearest_simple_explanation": { "type": ["string", "null"], "maxLength": 600 },
          "pathway": { "type": "string", "enum": ["assumption", "disagreement", "transfer", "method_improvement", "other"] },
          "critical_assumption": { "$ref": "common.schema.json#/$defs/short_text" },
          "alternative_explanation": { "type": ["string", "null"], "maxLength": 600 },
          "data_or_tool_requirement": { "type": ["string", "null"], "maxLength": 600 },
          "validation_plan": {
            "type": "string",
            "maxLength": 800,
            "description": "What check, comparison or further reading would support, narrow or weaken this claim. Not an experiment design."
          }
        }
      }
    },
    "source_ids": { "type": "array", "maxItems": 20, "items": { "$ref": "common.schema.json#/$defs/source_id" } },
    "passage_ids": { "type": "array", "maxItems": 30, "items": { "$ref": "common.schema.json#/$defs/passage_id" } },
    "rationale": { "type": "string", "maxLength": 1200 }
  }
}
```

`element_ref` tutamaçları her `formulations` öğesi içinde yalnız o öğeye özeldir (D12 deseninin aynısı: model kısa bir kimlik üretir, backend gerçek `claim_elements.id`'ye çözer); iki formülasyonun aynı `el1` tutamacı aynı öğe anlamına gelmez, sürüm kaydedilirken yalnız seçilen formülasyonun öğeleri kalıcı `ele_` kimlikleri alır.

**`kill-search-plan.schema.json`** (task_type `kill_search_plan`; `concepts`/`providers`/`scope_boundaries` alanları `search-plan.schema.json` ile birebir aynı biçimdedir, `query_compiler.compile_queries` değişmeden çağrılabilsin diye):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/kill-search-plan.schema.json",
  "title": "KillSearchPlan",
  "description": "Concept vocabulary aimed at prior art for one claim, not the research question — the claim's own field plus methodological neighbours and adjacent applications (README's Chain of Ideas adaptation, step 5). The backend compiles every provider query from `concepts` with the same compiler as SearchPlan (exactly one core concept).",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "step_input_id", "scope_revision", "skill_package_hash",
    "claim_interpretation", "concepts", "providers", "scope_boundaries", "search_rationale"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.kill_search_plan.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "claim_interpretation": { "type": "string", "maxLength": 1000 },
    "concepts": {
      "type": "array",
      "maxItems": 8,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["label", "role", "synonyms"],
        "properties": {
          "label": { "type": "string", "maxLength": 120 },
          "role": { "type": "string", "enum": ["core", "mechanism", "method", "outcome", "context", "adjacent_field"] },
          "synonyms": { "type": "array", "maxItems": 8, "items": { "type": "string", "maxLength": 120 } }
        }
      }
    },
    "providers": { "type": "array", "minItems": 1, "maxItems": 10, "items": { "$ref": "common.schema.json#/$defs/provider_id" } },
    "scope_boundaries": { "type": "array", "maxItems": 8, "items": { "$ref": "common.schema.json#/$defs/short_text" } },
    "search_rationale": { "type": "string", "maxLength": 1200 }
  }
}
```

**`claim-assessment.schema.json`** (task_type `claim_assessment`):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://deixis.local/contracts/research/claim-assessment.schema.json",
  "title": "ClaimAssessment",
  "description": "The claim-passage matrix cells this step was asked to fill: for one close work, the relation of its passages to given claim elements. insufficient_access is written by the application, never by this output.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version", "step_input_id", "scope_revision", "skill_package_hash",
    "cells", "insufficient_evidence", "nearest_match_summary"
  ],
  "properties": {
    "schema_version": { "type": "string", "const": "deixis.claim_assessment.v1" },
    "step_input_id": { "$ref": "common.schema.json#/$defs/step_input_id" },
    "scope_revision": { "$ref": "common.schema.json#/$defs/scope_revision" },
    "skill_package_hash": { "$ref": "common.schema.json#/$defs/skill_package_hash" },
    "cells": {
      "type": "array",
      "maxItems": 64,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["element_ref", "source_id", "relation", "condition_alignment", "evidence", "note"],
        "properties": {
          "element_ref": { "$ref": "common.schema.json#/$defs/claim_element_ref" },
          "source_id": { "$ref": "common.schema.json#/$defs/source_id" },
          "relation": { "type": "string", "enum": ["explicit_support", "reasoned_inference", "partial_match", "uncertain"] },
          "condition_alignment": { "type": "string", "enum": ["aligned", "different_conditions", "unclear"] },
          "evidence": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
              "type": "object",
              "additionalProperties": false,
              "required": ["passage_id", "quote"],
              "properties": {
                "passage_id": { "$ref": "common.schema.json#/$defs/passage_id" },
                "quote": { "type": "string", "minLength": 12, "maxLength": 600 }
              }
            }
          },
          "note": { "type": ["string", "null"], "maxLength": 600 }
        }
      }
    },
    "insufficient_evidence": {
      "type": "array",
      "maxItems": 8,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["element_ref", "note"],
        "properties": {
          "element_ref": { "$ref": "common.schema.json#/$defs/claim_element_ref" },
          "note": { "$ref": "common.schema.json#/$defs/short_text" }
        }
      }
    },
    "nearest_match_summary": { "type": ["string", "null"], "maxLength": 1200 }
  }
}
```

`domain/contracts.py` eklemeleri: `SCHEMA_VERSIONS`'a üç yeni giriş; `TASK_OUTPUTS`'a `"claim_decomposition": ("ClaimDecomposition",)`, `"kill_search_plan": ("KillSearchPlan",)`, `"kill_search_screening": ("ScreeningProposal",)`, `"claim_assessment": ("ClaimAssessment",)`. Yeni deterministik denetimler (`_check_claim_decomposition`, `_check_kill_search_plan`, `_check_claim_assessment`) mevcut `_check_search_plan`/`_check_cells` desenini izler: `elements`in `source_ids`/`passage_ids` allowlist'te olması, `claim-assessment`'ta her `cells` girdisinin StepInput'un verdiği (element, kaynak) çiftlerinden biri olması ve `insufficient_access` işaretli çiftlerin hiç modele verilmemiş olması, `locate_anchor` ile her alıntının pasajda bulunması (D27 ile aynı fonksiyon).

### 9.5 Fixtures, fakes, davranış vakaları

- `tests/fixtures/research/step-inputs.json` ve `fake-outputs.json`'a dört yeni görev için örnek `StepInput`/çıktı çiftleri; en az biri `candidate`'ında dilim 2'nin `ChainEndUncertainty` teslim kaydı dolu olan bir örnek (çizgi kökenli aday), en az biri `requested_formulations: 3` (alternatif biçim) örneği taşır.
- `tests/fakes.py::valid_response` yeni `task_type` dallarına `ClaimDecomposition`/`KillSearchPlan`/`ClaimAssessment` üretimi eklenir (`ScreeningProposal` zaten var, `kill_search_screening` için aynen kullanılır). `ClaimDecomposition`'ın sahte üretimi `requested_formulations` sayısı kadar öğe döndürür.
- `scripts/model_behavior/` altına en az beş vaka (istenen listeyle):
  1. Aynı sonuç başka terminolojiyle (S5) — beklenen: `explicit_support`, terminoloji farkı gerekçe olarak reddedilir.
  2. Sıfır sonuç / sağlayıcı hatası / erişilemeyen kritik PDF (S2–S4) — üçü de ayrı kayıt, hiçbiri `closed`/`open` karıştırılmaz.
  3. Çok iddialı aday, tek örtüşen iddia (S6) — yalnız o öğenin hücresi dolar, aile kapatılmaz.
  4. Çekici ama geçersiz uzak analoji (S7) — `different_conditions`, `closed`e katkı yapmaz.
  5. Farklı koşullarda ters sonuç (S8) — "çelişki" değil "farklı koşullarda farklı sonuç".

  Dilim 1'deki gibi `gpt-5.6-luna` ile koşulur (bu dilimin kapanışında, §17 alt adım 12).

## 10. Veri modeli taslağı

SQL'in geçerli hâli migration dosyası olacaktır; bu taslak niyettir. Migration numaraları uygulama sırasında verilir.

```sql
-- runs.kind CHECK genişletmesi (0001/0019/... deseniyle, foreign-keys-off yeniden kurma)
-- kind IN (..., 'claim_decomposition', 'kill_search', 'claim_assessment')
-- stage CHECK zaten 'candidate' ve 'claim_check' içeriyor (0022+); değişiklik gerekmez.
-- target_json: claim_decomposition/kill_search {"candidate_id","candidate_version_id"};
--              claim_assessment {"candidate_version_id"}; pdf_collection (genişletilmiş) {"candidate_version_id"?}

-- Adopted from p6-slice4-editing-stale-measurement.md §5 (gap identity only, not the claim-matching layer): a
-- report_gaps row's gap_id is reissued on every section rewrite (dilim 1 rule), so it cannot anchor a candidate
-- that must survive report regeneration. This slice introduces the table because it is the first to need it;
-- dilim 4 later adds report_stable_claims/report_claim_matches on top, unchanged here (§15.3).
CREATE TABLE report_stable_gaps (
  id TEXT PRIMARY KEY,                 -- rgs_
  research_id TEXT NOT NULL REFERENCES researches(id),
  kind TEXT NOT NULL,                  -- same open list as report_gaps.kind (domain.contracts.GAP_KINDS)
  basis_fingerprint TEXT NOT NULL,     -- deterministic hash of the sorted basis set; see identity.py::fingerprint_gap
  first_seen_report_id TEXT NOT NULL REFERENCES reports(id),
  last_seen_report_id TEXT NOT NULL REFERENCES reports(id),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (research_id, kind, basis_fingerprint)
);
-- report_gaps.stable_gap_id REFERENCES report_stable_gaps(id) is dilim 1's column to add (§15.1); this slice only
-- consumes it, it does not migrate report_gaps itself.

CREATE TABLE research_candidates (
  id TEXT PRIMARY KEY,                              -- rcd_
  research_id TEXT NOT NULL REFERENCES researches(id),
  source_gap_id TEXT NOT NULL UNIQUE REFERENCES report_stable_gaps(id),  -- NOT report_gaps.id: a candidate must outlive
                                                      -- report regeneration, and only report_stable_gaps does (§5, §15.3).
                                                      -- Every candidate has exactly one: even a chain-origin candidate only
                                                      -- exists because a chain_end_uncertainty was promoted into a report_gaps
                                                      -- row first (§2 adım 0a) — there is no origin path that skips this.
  chain_end_uncertainty_id TEXT UNIQUE REFERENCES chain_end_uncertainties(id),  -- dilim 2 (§5); additional cross-reference,
                                                      -- set only when source_gap_id's report_stable_gaps.kind = 'chain_end_uncertainty'.
                                                      -- Already promoted by construction: a report_gaps row of this kind exists only
                                                      -- once chain_end_uncertainties.forward_check_id and promoted_at are both set (dilim 2 §4.4).
  status TEXT NOT NULL DEFAULT 'not_run'
    CHECK (status IN ('not_run', 'undecided', 'narrowed', 'closed', 'open')),
  current_version INTEGER NOT NULL DEFAULT 0,        -- 0 until the first claim_decomposition succeeds
  trashed_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);

CREATE TABLE candidate_versions (
  id TEXT PRIMARY KEY,                               -- clv_
  candidate_id TEXT NOT NULL REFERENCES research_candidates(id),
  version INTEGER NOT NULL,
  claim_statement TEXT NOT NULL,
  conditions_json TEXT NOT NULL,                     -- [short_text]
  nearest_simple_explanation TEXT,
  pathway TEXT NOT NULL CHECK (pathway IN ('assumption', 'disagreement', 'transfer', 'method_improvement', 'other')),
  critical_assumption TEXT NOT NULL,
  alternative_explanation TEXT,
  data_or_tool_requirement TEXT,
  validation_plan TEXT NOT NULL,                     -- README step 6; never an experiment design
  origin TEXT NOT NULL CHECK (origin IN ('model_decomposition', 'human_edit')),
  step_input_id TEXT REFERENCES step_inputs(id),     -- null for a human edit
  created_at TEXT NOT NULL,
  UNIQUE (candidate_id, version)
);

-- No separate table copies the chain's links: research_candidates.chain_end_uncertainty_id already resolves to
-- dilim 2's chain_end_uncertainties.chain_id, and the chain view renders that chain's own chain_links/chain_link_revisions
-- directly (§5); duplicating a copy here would drift from dilim 2's append-only revision history.

-- Formulations the user did not choose when requested_formulations > 1 (§16 soru 9). Kept for audit rather than
-- silently discarded, consistent with the repo's "preserve revisions" rule (AGENTS.md); the chosen one becomes the
-- normal candidate_versions row above.
CREATE TABLE candidate_version_alternatives (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES research_candidates(id),
  step_input_id TEXT NOT NULL REFERENCES step_inputs(id),
  formulations_json TEXT NOT NULL,                   -- the full ClaimDecomposition.formulations array as returned
  chosen_version_id TEXT REFERENCES candidate_versions(id),
  created_at TEXT NOT NULL
);

CREATE TABLE claim_elements (
  id TEXT PRIMARY KEY,                               -- ele_
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  position INTEGER NOT NULL,                          -- matches the element_ref order the model saw
  text TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('mechanism', 'condition', 'outcome', 'parameter')),
  UNIQUE (candidate_version_id, position)
);

CREATE TABLE kill_searches (                          -- one row per kill_search run
  id TEXT PRIMARY KEY,                                -- kls_
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  run_id TEXT NOT NULL REFERENCES runs(id),
  plan_json TEXT,                                     -- KillSearchPlan output, once produced
  query_compiler TEXT,
  outcome TEXT NOT NULL DEFAULT 'not_run' CHECK (outcome IN ('completed', 'failed', 'not_run')),
  created_at TEXT NOT NULL
);

CREATE TABLE kill_search_queries (                    -- mirrors the provider_search step records of discovery
  id TEXT PRIMARY KEY,
  kill_search_id TEXT NOT NULL REFERENCES kill_searches(id),
  provider TEXT NOT NULL,
  query_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'outcome_unknown')),
  result_count INTEGER,
  step_id TEXT REFERENCES run_steps(id),
  created_at TEXT NOT NULL
);

-- Kept apart from corpus_memberships/selections so a kill-search never silently widens the research's included set.
CREATE TABLE claim_search_memberships (
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  decision TEXT NOT NULL CHECK (decision IN ('include', 'exclude', 'uncertain')),
  reason TEXT,
  origin TEXT NOT NULL CHECK (origin IN ('model_proposal', 'human')),
  step_id TEXT REFERENCES run_steps(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (candidate_version_id, source_version_id)
);

CREATE TABLE claim_matrix_cells (
  id TEXT PRIMARY KEY,                                -- cmx_
  candidate_version_id TEXT NOT NULL REFERENCES candidate_versions(id),
  element_id TEXT NOT NULL REFERENCES claim_elements(id),
  source_version_id TEXT NOT NULL REFERENCES source_versions(id),
  coverage TEXT NOT NULL CHECK (coverage IN ('assessed', 'insufficient_access')),
  relation TEXT CHECK (relation IN ('explicit_support', 'reasoned_inference', 'partial_match', 'uncertain')),
  condition_alignment TEXT CHECK (condition_alignment IN ('aligned', 'different_conditions', 'unclear')),
  reading_depth TEXT CHECK (reading_depth IN ('metadata', 'abstract', 'selected_sections', 'full_text')),
  note TEXT,
  step_input_id TEXT REFERENCES step_inputs(id),
  created_at TEXT NOT NULL,
  UNIQUE (candidate_version_id, element_id, source_version_id),
  CHECK ((coverage = 'assessed') = (relation IS NOT NULL))
);

CREATE TABLE claim_matrix_evidence (
  matrix_cell_id TEXT NOT NULL REFERENCES claim_matrix_cells(id),
  passage_id TEXT NOT NULL REFERENCES passages(id),
  quote TEXT NOT NULL,
  PRIMARY KEY (matrix_cell_id, passage_id, quote)
);

CREATE TABLE candidate_status_history (
  id TEXT PRIMARY KEY,
  candidate_id TEXT NOT NULL REFERENCES research_candidates(id),
  candidate_version_id TEXT REFERENCES candidate_versions(id),
  status TEXT NOT NULL CHECK (status IN ('not_run', 'undecided', 'narrowed', 'closed', 'open')),
  decided_by TEXT NOT NULL CHECK (decided_by IN ('code', 'human')),
  reason TEXT,                                        -- required when decided_by = 'human'
  step_id TEXT REFERENCES run_steps(id),
  created_at TEXT NOT NULL,
  CHECK (decided_by = 'code' OR reason IS NOT NULL)
);

-- Dilim 1'e bağımlı: report_gaps.stable_gap_id (dilim 4'ün önerisi, bu notun benimsediği, §15.1/§15.3) ve
-- report_gaps.kill_search_status'un CHECK'inin 'undecided' ile genişlemesi (§6, §15.1).
-- Dilim 2'ye bağımlı (şeması artık kesin, yalnız migration olarak henüz yok): chain_end_uncertainties(id),
-- citation_expansions(id, direction, status, run_id) — research_candidates.chain_end_uncertainty_id bu tabloya,
-- kill_search'ün atıf genişletmesi (§2 madde 3) citation_expansions'a FK verir (§15.2).
-- Dilim 4'ten benimsenen (bu slice'ın kendi migration'ında kurulur, §15.3): report_stable_gaps ve
-- identity.py::fingerprint_gap/resolve_stable_gap (yalnız gap kısmı; claim kısmı dilim 4'ün kendi işidir).
```

## 11. Arayüz

`.impeccable.md` ve `AGENTS.md`'deki hiyerarşi ve kanıt kuralları geçerlidir; yalnız metin, mockup yok.

- **Giriş noktası.** Rapor bölüm VI'daki her aday satırında "Investigate" eylemi; `chain_end_uncertainty` türündeki adaylar için dilim 2'nin çizgi görünümündeki uç düğümden de aynı eylem açılabilir (§16 soru 8, iki giriş noktası da aynı `research_candidates` satırına gider). Tıklanınca aday kartı ayrı bir sayfa/panelde açılır; satırdaki rozet o andan itibaren `not_run` yerine gerçek durumu gösterir.
- **Kullanıcı yönlendirmesi (adım 0).** Aday kartı ilk açıldığında (kill-search'ten önce) alanlar düzenlenebilir durumda gösterilir: amaç/mekanizma/değerlendirme metni, koşullar. "Alternatif biçim öner" eylemi `claim_decomposition`'ı `requested_formulations: 3` ile yeniden çağırır (ek çağrı maliyeti önceden yazılı, §7); sonuç yan yana üç kart olarak gelir, sahip birini seçer, seçilmeyenler geçmişte kalır (§10). Çizgi kökenli bir adayda kart üstte "şu çizgiden, şu bağlarla" özetini gösterir.
- **Aday kartı.** research-methods.md §4'teki alanlar sırayla: iddia, koşullar, en yakın basit açıklama, kritik varsayım, oluşma yolu, doğrulama planı. Sürüm numarası ve "önceki sürümler" katlanmış geçmiş olarak (evidence hücresinin geçmişi gibi). "Kill-search başlat" birincil eylem, bütçe ve tahmini maliyet (§7) buton üstünde yazılı; run sürerken buton kapalı.
- **Kill-search zaman çizelgesi.** Mevcut Transcript desenindeki gibi tek satır: plan → arama (sağlayıcı başına alt satır, D18 hatası dahil) → tarama. `discovery`nin bugünkü satırıyla aynı görsel dil, farklı başlık ("Search for prior art on this claim").
- **Matris görünümü.** Satırlar yakın çalışmalar, sütunlar öğeler; hücrede ilişki etiketi (metinle, yalnız renkle değil — amber `uncertain`/`insufficient_access`, yeşil `explicit_support`, kırmızı yok çünkü hiçbir ilişki "hata" değildir) ve "Show evidence" (mevcut PassageSheet'i açar, D27 vurgusuyla). `insufficient_access` hücresi tıklanamaz, nedenini yazar (PDF yok / özet düzeyinde).
- **Durum rozeti ve override.** Kartın üstünde `not_run`/`undecided`/`narrowed`/`closed`/`open` rozeti, yanında "Kod bu matristen türetti" notu. "Override" eylemi sahibin gerekçe yazmasını zorunlu kılar; override sonrası rozet "sizin kararınız" ibaresiyle görünür, bir sonraki otomatik hesaplama sessizce ezmez, karşılaştırmalı gösterilir (§6).
- **Rapor bölüm VI/VII.** Değişiklik yalnız rozet ve "kill-search yapılmadı" ibaresinin kalkması; model düzyazısı elle tetiklenen bir `report_section` yeniden yazımı olmadan değişmez (§5).
- **Aday dosyası (§16 soru 10).** Aday kartında "Export candidate brief" eylemi, mevcut kayıtlı alanlardan (çizgi, iddia, amaç/mekanizma/değerlendirme, matris, kill-search sonucu ve sınırları, durum, doğrulama planı) tek geçişte kod tarafından derlenen bir Markdown dosyası verir; rapor dışa aktarımıyla aynı "DEIXIS ile üretildi" satırını taşır. Yeni model çağrısı yapmaz.

## 12. Testler taslağı

**Sözleşme ve depolama (modelsiz)**

- Üç yeni şemanın `additionalProperties: false`, zorunlu alan ve `common.schema.json` referans denetimi.
- `ClaimDecomposition`: `formulations` dizisi `requested_formulations`'tan fazla öğe döndürürse reddedilir; çıktı çizgi kökenini tekrarlamaz (StepInput'ta kalır, modelden istenmez); her formülasyonun `element_ref`leri kendi içinde tekil.
- `ClaimAssessment`: allowlist dışı (element, kaynak) çifti reddedilir; `insufficient_access` işaretli çiftin modele hiç verilmediği (StepInput'ta yok) doğrulanır; `uncertain` ilişkide de en az bir `evidence` zorunlu; bulunamayan alıntı (`locate_anchor` başarısız) tek onarıma gider.
- Migration: yeni tablolar, `runs.kind` genişlemesi, foreign key denetimi temiz; `purge_research` yeni tabloları temizler.
- `claim_matrix_cells` tetikleyicisi: `coverage = 'assessed'` iken `relation IS NULL` olamaz (CHECK).

**Akış (sahte adaptörle)**

- Bir `report_gaps` satırından aday açma → `claim_decomposition` → sürüm 1 ve öğeler kaydı.
- Bir yükseltilmiş `chain_end_uncertainties` kaydından (sahte `ChainEndUncertainty` teslim kaydıyla) aday açma → `claim_decomposition` StepInput'unun `candidate` alanında teslim kaydı var → sürüme `chain_end_uncertainty_id` yazılır.
- `requested_formulations: 3` ile çağrılan `claim_decomposition` → üç `candidate_version_alternatives` girdisi saklanır, sahibin seçtiği `candidate_versions`'a normal sürüm olarak yazılır, seçilmeyenler silinmez.
- `kill_search_plan` çıktısından `query_compiler.compile_queries` çağrısı (mevcut `query_compiler` testleriyle aynı desende, girdi artık iddia sözlüğü).
- D18'in aynısı: bir sorgu başarısız, diğerleri sürer; hiçbiri başarılı olmazsa run duraklar ve `kill_searches.outcome = 'not_run'` kalır.
- `kill_search_screening` kararları `claim_search_memberships`'e yazılır, araştırmanın `selections`/`corpus_memberships`'i **değişmez** (T08'in aynısı, iddia kapsamı ↔ araştırma kapsamı izolasyonu).
- `pdf_collection`, `candidate_version_id` kapsamıyla çağrıldığında yalnız `claim_search_memberships`'te `include` olan kaynakları toplar.
- §6'daki beş durumun her biri için bir senaryo (S1–S4 + S6'daki kısmi örtüşme): matristen doğru durumun türediği.
- Sahip override'ı sonraki otomatik hesaplamayla ezilmez; yeni bir `claim_assessment` gelince kod satırı eklenir ama insan satırı silinmez.

**API**

- Yeni uçlar (`POST /researches/{rid}/candidates` [gövdede o anki `report_gaps.id`; kod bunu `stable_gap_id`'ye çözüp `research_candidates.source_gap_id`'yi ona yazar — çağıran taraf `report_stable_gaps.id`'yi bilmek zorunda değildir], `POST .../candidates/{id}/claim-decomposition`, `POST .../candidates/{id}/kill-search`, `POST .../candidates/{id}/claim-assessment`, `PUT .../candidates/{id}/status`) mevcut CSRF/loopback/Idempotency-Key kurallarından geçer.
- Başka araştırmanın adayı 404; etkin run varken ikinci kill-search 409.
- `PUT .../status` gerekçesiz istek 422.

**Web (Playwright, fixture sunucusu, sentetik senaryolu model)**

- Rapor VI satırından "Investigate" → aday kartı → isteğe bağlı "Alternatif biçim öner" ve seçim → "Kill-search başlat" → sahte sağlayıcı sonucu → tarama → matris → durum rozeti → override formu → "Export candidate brief" indirmesi. Masaüstü ve 390 px, açık ve koyu tema.
- Dilim 2'nin çizgi görünümünden (sahte çizgi verisiyle) "Investigate" → aynı aday kartına gider, "şu çizgiden, şu bağlarla" özeti görünür.

**T12 yürütülebilir denetim olarak:** boş bir kill-search (S2) sonrasında raporun **hiçbir yerinde** ("gap", "novel", "first" ve eşdeğerlerinin sabit listesi, iki dilde) geçmediği; VI/VII'deki metnin "şu tarihte şu sorgularla eşleşme bulunamadı" biçiminde sınırlı kaldığı, kod tarafından bütün rapor metninde aranarak sınanır (p6-report-design.md §7'deki yasak sözcük denetiminin aynısı, kill-search'ün gerçekten koştuğu durumla birlikte).

## 13. Ön kayıtlı ölçüm planı

P5 dilim 5 ve p6-report-design.md §13'teki kural: beklenti koşudan önce yazılır ve commit'lenir, sonradan yorumlanıp uydurulmaz. Gerçek bir soru üzerinde, kütüphanenin bir kopyasında, `gpt-5.6-luna` ile:

| # | Ne ölçülür | Payda |
|---|---|---|
| K1 | Yanlış `open` | sahibin önceden bildiği, aslında literatürde var olan bir iddia için kill-search kaç kez `open` türetiyor — sahip-etiketli küçük bir küme üzerinde |
| K2 | Yanlış `closed` | sahibin bildiği, aslında koşulları farklı olan bir "yakın" çalışma için kill-search kaç kez `closed` türetiyor |
| K3 | Kaçırılan en yakın çalışma | sahibin önceden bildiği en yakın çalışma kümesinden kaçı taramaya hiç girmedi (D55'teki bilinen eser geri çağırımı ölçümüyle aynı yöntem, bu kez iddia düzeyinde) |
| K4 | Durum türetme tutarlılığı | aynı matris girdisiyle §6 tablosunun elle hesaplanan durumu ile kodun ürettiği durum birebir aynı mı (modelsiz, sabit vaka kümesiyle) |
| K5 | Bütçe ve süre | uçtan uca süre, model/sağlayıcı çağrı sayısı (§7'deki tahminle karşılaştırma) |

Değerlendiren Claude'dur, sahip etiketlemediği sürece; bu bir "insan denetimi" sayılmaz (p6-report-design.md §13'ün aynı uyarısı). Payda sıfırsa metrik "ölçülemedi" yazılır. K1–K3 örneklem küçüktür (tek soru, birkaç aday); genel doğruluk iddiası çıkarılmaz.

## 14. Varsayımlar ve sınırlar

- Kill-search korpusun kapsamını iyileştirmez; D55'teki geri çağırım ve PDF edinme sorunları (ayrı not, henüz çözülmedi) burada da aynen geçerlidir ve K3'te görünür.
- `claim_assessment`in matris hücresi yapısal olarak geçerli olsa da semantik doğrulama değildir (AGENTS.md: "A valid JSON shape ... is not scientific validation"); kodun `_check_claim_assessment` denetimi biçimi doğrular, ilişkinin doğruluğunu değil.
- Kod yalnız §6'daki mantığı uygular; matrisin kendisi yanlışsa (model yanlış ilişki yazmışsa) durum da yanlış türer. Bu, `report_review`'a benzer bir "yakalama oranı ölçülmedi" sınırıdır ama bu dilimde ayrı bir inceleme adımı önerilmiyor (kapsam dışı bırakıldı, §16'da tartışılabilir).
- İddia sürümleri arasında kill-search sonucu otomatik taşınmaz; bu, aynı adayı tekrar tekrar aramaktan kaçınmak isteyen bir kullanıcı için ek iş demektir — bilinen ödün (research-methods.md §5 madde 5).
- Bu not tek bir kill-search akışını tanımlar; birden çok adayın **karşılaştırmalı** değerlendirilmesi (örneğin hangi adayın önce araştırılacağı) kapsam dışıdır.
- `validation_plan` alanının kalitesi (önerilen kontrolün gerçekten bilgilendirici olup olmadığı) ölçülmez; kod yalnız alanın var olduğunu ve bir deney tasarımı biçiminde olmadığını (apparatus/protokol sözcüklerinin geçmediğini) yüzeysel denetleyebilir, içeriğin doğruluğunu denetleyemez.
- Bu not dilim 2'nin gerçek şemasına (`chains`, `chain_end_uncertainties`, `citation_expansions`) dayanır (§15.2); dilim 2 bir migration olarak henüz uygulanmadı, yalnız tasarım notu olarak var.
- Alternatif biçim özelliğinin (§16 soru 9) gerçek maliyeti (kaç sahibin kullandığı, ek çağrının süresi) ölçülmedi; §7'deki "+1 çağrı" yalnız bir üst sınırdır.
- "Aday dosyası" (§16 soru 10) kabul edilirse dahi, dışa aktarılan metnin kendisi model tarafından yeniden okunup tutarlılık denetiminden geçmez (rapor'un `report_review`'ı gibi bir inceleme adımı bu dilimde yok); yalnız zaten kayıtlı alanların derlemesidir.
- `report_stable_gaps`'in deterministik eşleştirmesi (kind + basis_fingerprint) en iyi çaba niteliğindedir, garanti değil: raporun bir sonraki sürümünde aynı boşluğun temel kümesi (basis_json) değişirse (örn. kanıt kümesi genişlerse) fingerprint de değişir ve aday kartı "aynı soruyu" bulamaz, sessizce yeni bir `report_stable_gaps` satırı açılır — dilim 4'ün kendi notunda aynı dürüstlükle işaretlediği bir sınırdır (§5, "Ne kırılıyor"), burada da geçerlidir ve ölçülmedi.

## 15. Dilim 1'den, dilim 2'den ve dilim 4'ten beklenenler

### 15.1 Dilim 1'den beklenenler

Bu not, `report_gaps` tablosunun p6-report-design.md §10'daki taslak sütunlarıyla var olduğunu varsayar: `id, report_id, gap_id, kind, text, basis_json, provenance_json, kill_search_status`, `kind`'ın kapalı bir `CHECK` değil kod denetimli genişleyebilir bir alan olduğunu (§12 güncellemesi). Uygulama sırasında gerçek migration şu ikisini sağlamalıdır:

1. `report_gaps.stable_gap_id` (nullable, `report_stable_gaps(id)`'e FK) — dilim 4'ün önerdiği sütun (§15.3); bu not `report_gaps.candidate_id` gibi ayrı bir sütun **istemez**, çünkü `research_candidates.source_gap_id` zaten `report_stable_gaps.id`'ye bağlıdır ve "bu gap'in adayı var mı" sorusu `report_gaps.stable_gap_id = research_candidates.source_gap_id` eşleşmesiyle yanıtlanır.
2. `report_gaps.kill_search_status`'un CHECK kısıtının, bu notun önerdiği `undecided` durumunu kabul edecek biçimde genişlemesi (sahip §16 soru 1'i onaylarsa); onaylamazsa bu notun §6'sı üç duruma göre yeniden yazılır.

Ayrıca dilim 1'in `reports`/`report_sections`/`report_snapshot` görünüm mekanizmasının (§4.2, "kanıt anlık görüntüsü") gerçekten donmuş bir metin ile canlı bir durum sütununu ayırabildiği varsayılıyor (§5); bu ayrım dilim 1'de zaten tasarlandı ama uygulanmadıysa bu notun "rozet canlı, metin donuk" önerisi doğrulanmamış kalır.

### 15.2 Dilim 2'den beklenenler

`p6-slice2-chain-of-ideas.md` artık yazılmış ve bu not onunla uzlaştırıldı (§1, §2, §5, §7, §9, §10). Genuine açık kalan tek nokta:

1. **Çizgi görünümünden yükseltme sonrası "İncele" bağlantısı.** Dilim 2'nin çizgi görünümü tarifi (§4.6) yükseltmeyi (`promoted_at`) ve "Check citing works" eylemini anlatıyor, ama yükseltmeden sonra aynı ekranda bir "View candidate" bağlantısı olup olmayacağını söylemiyor. Bu not (§16 soru 8) böyle bir bağlantının bulunmasını önerir; iki notun arayüz bölümlerinin (dilim 2 §4.6, bu notun §11'i) bunu aynı ekran davranışıyla tarif etmesi gerekir, kesinleşmedi.

Çözülenler (artık açık değil): dördüncü `report_gaps.kind` adı (`chain_end_uncertainty`, dilim 2 §4.5'te doğrudan kullanılıyor); çizgi tablolarının şeması (`chains`/`chain_members`/`chain_links`/`chain_link_revisions`/`chain_link_evidence`/`chain_end_uncertainties`/`citation_expansions`, §5, §10); T11'in çizgi bağları üzerindeki karşılığının dilim 2'de, iddia düzeyindeki karşılığının bu notta (S8, §4) olduğu.

### 15.3 Dilim 4'ten beklenenler

`p6-slice4-editing-stale-measurement.md` §5 ve §11, henüz uygulanmamış olsa da, `research_candidates.source_gap_id`'nin `report_gaps.id` yerine `report_stable_gaps.id`'ye bağlanmasını istiyor — dilim 1'in `gap_id`'yi her bölüm yeniden yazımında yeniden vermesi (p6-report-design.md §4) yüzünden, aksi hâlde bir aday kartı raporun ikinci sürümünde "aynı gerçek soruyu" bulamaz. Bu not bunu **kabul etti ve §10'da uyguladı**; sıralama gereği (dilim 3, dilim 4'ten önce uygulanır, p6-report-design.md §12) bu, **dilim 4'ün değil bu dilimin migration'ında** kurulur — dilim 4 `report_stable_gaps`'i hazır bulur, yalnız kendi `report_stable_claims`/`report_claim_matches` (iddia düzeyindeki bulanık eşleştirme, Jaccard) katmanını üstüne ekler. Bu, dilim 4'ün kendi notunda flagelediği "dilim 3 önce uygulanırsa geriye dönük migration gerekir" riskini baştan önler.

Bu genuine bir sahip kararı değildir (iki tasarım notu arasında bir mekanik uzlaşmadır), bu yüzden §16'ya soru olarak eklenmedi. Açık kalan tek nokta: `identity.py::fingerprint_gap`/`resolve_stable_gap` fonksiyonlarının **çağrı yeri** dilim 1'in VI-yazma kodudur (dilim 1'in kabul edilmiş notu bunu henüz içermiyor, çünkü dilim 4 dilim 1'den sonra tasarlandı); bu dilim yalnız tabloyu ve saf fonksiyonları kurar, dilim 1'in VI kodunun bunları gerçekten çağırması ayrı bir entegrasyon adımıdır ve bu notun alt adımlarına dahildir (§17 alt adım 2).

## 16. Sahibe sorulanlar

Her soruda önerilen seçenek ilk sırada ve gerekçesiyle yazılıdır. **Yanıt gelmezse ilk seçenek uygulanır.**

1. **Dört durum mu üç mü.** research-methods.md'nin "erişim yetersizliği ret değil karar verilememedir" kuralı üç durumla (narrowed/closed/open) tam ifade edilemiyor.
   - a. `undecided` dördüncü durum olarak eklenir; `report_gaps.kill_search_status` CHECK'i genişler. **(öneri — §6'nın gerekçesi)**
   - b. Üç durum kalır, erişim yetersizliği `open` sayılır (yanıltıcı: "aranmış bulunamamış" ile "okunamamış" karışır).
   - c. Üç durum kalır, erişim yetersizliği `not_run`a döner (arama gerçekten koştuğu hâlde "hiç aranmamış" görünür).

2. **Kill-search'ün bulduğu kaynaklar araştırmanın dahil kaynaklarına mı katılsın, ayrı kapsamda mı kalsın.**
   - a. Ayrı kapsam (`claim_search_memberships`); sahip isterse elle ana korpusa ekler. Kill-search'ün taraması dar ve iddiaya özgüdür, araştırmanın cevabını sessizce genişletmemeli. **(öneri)**
   - b. Otomatik ana korpusa (`corpus_memberships`) katılır, normal tarama akışına girer.
   - c. Her kill-search sonunda kullanıcıya "ana korpusa eklensin mi" sorulur.

3. **Sahip, kill-search yapmadan bir adayı `closed` işaretleyebilir mi.**
   - a. Evet, gerekçe zorunlu ve `candidate_status_history.decided_by = 'human'` ile ayrı görünür ("aranmadı, sizin kararınız" ibaresiyle). **(öneri — evidence hücrelerindeki insan üstünlüğü kuralının aynısı)**
   - b. Hayır; `closed` yalnız en az bir tamamlanmış kill-search'ten sonra verilebilir.
   - c. Evet, iz bırakmadan (karşılaştırma için; önerilmiyor).

4. **Aday sürümleri mi, yerinde düzenleme mi.**
   - a. Sürümler; kill-search sonucu eski sürüme bağlı kalır, yeni sürüme otomatik taşınmaz (§4, §14). **(öneri — research-methods.md'nin "salt isim değişikliğiyle fikir kurtarılmaz" kuralı)**
   - b. Yerinde düzenleme, geçmiş tutulmaz.
   - c. Sürüm ama kill-search sonucu otomatik kopyalanır (reddedilecek: eski sonucu yeni iddiaya otomatik aktarmama kuralına aykırı).

5. **Varsayılan bütçe.**
   - a. §7'deki sabit tablo (1+1+6+2+10 çağrı sınırı), başlamadan gösterilir. **(öneri — tablo doldurmanın "en fazla {m} çağrı" desenine uyar)**
   - b. Kullanıcı her seferinde bütçe girer.
   - c. Sınırsız, yalnız sağlayıcı/kota sınırına kadar (reddedilecek: "sınırlı iş" ilkesine aykırı).

6. **`stated_limitation` adaylarına kill-search uygulanır mı** (kaynağın kendi belirttiği sınırlama sonraki bir çalışmayla çözülmüş olabilir).
   - a. Evet, üç türe de uygulanır; `stated_limitation` için candidate-check.md sorgu vurgusu "bu sınırlamayı gideren sonraki çalışma" olur. **(öneri — hiçbir tür kill-search'ten muaf tutulmuyor, tutarlılık için)**
   - b. Hayır, yalnız `corpus_absence` ve `conflicting_evidence`.
   - c. Yalnız kullanıcı elle işaretlerse.

7. **VII'deki yönler adayın durumunu miras alsın mı.**
   - a. Evet: `gap_id`'ye bağlı bir yön, adayı `closed`/`narrowed` olunca "ele alınmış" rozeti alır; metin yeniden yazılmaz, yalnız görünüm bandı. **(öneri — §5'teki "rozet canlı, metin donuk" ilkesiyle tutarlı)**
   - b. Hayır, durum yalnız VI'da görünür.
   - c. Durum değişince VII otomatik `stale` işaretlenir (dilim 4'ün konusu; bu dilimde erken karar vermeye gerek yok).

8. **Aday kartı nereden açılır.**
   - a. Rapor VI'daki her aday satırından **ve**, `chain_end_uncertainty` türü için, dilim 2'nin çizgi görünümündeki uç düğümden; ikisi de aynı `research_candidates` satırını açar/gösterir. Bağımsız oluşturma (ör. Evidence tablosundan) sonraki bir işe bırakılır. **(öneri — Chain of Ideas akışında sahip çoğunlukla çizgiden çalışacak; onu her seferinde rapora dönmeye zorlamak README adım 4'ün akışını bozar)**
   - b. Yalnız rapor VI'dan; çizgi ucundaki bir belirsizlik önce raporda görünmeden incelenemez.
   - c. Yalnız API üzerinden, arayüzde giriş yok.

9. **`claim_decomposition` tek biçim mi, 2-3 alternatif mi önersin.** Tree-of-Thoughts tarzı dallanmanın DEIXIS'e uyan tek parçası budur: model seçenekleri üretir, **insan budar**, model değil.
   - a. Varsayılan tek biçim; sahip isterse ayrı bir "Alternatif biçim öner" eylemiyle 2-3 ek biçim ister (§7'de bütçelenen ek bir çağrı). **(öneri — çoğu adayda tek biçim yeterlidir; maliyet yalnız gerçekten istendiğinde artar, varsayılan akış ucuz kalır)**
   - b. Her zaman 2-3 alternatif biçim üretilir, sahip her seferinde birini seçer.
   - c. Her zaman tek biçim; alternatif hiç sunulmaz.

10. **"Aday dosyası" (aday brifingi) dışa aktarımı** — README adım 6'nın istediği, hayatta kalan/daralan sorunun koşullu hipotez, varsayım ve doğrulama planıyla sunulduğu 1-2 sayfalık belge.
    - a. Bu dilime dahil edilir: kartın zaten kayıtlı alanlarından (çizgi, iddia, amaç/mekanizma/değerlendirme, matris, kill-search sonucu ve sınırları, durum, doğrulama planı) kod tarafından derlenen bir Markdown dışa aktarımı; doğrulama planı alanı dışında yeni model düzyazısı yok. **(öneri — rapor dışa aktarımıyla aynı ilke: model metni bir kez yazılır, kod yeniden derler; yeni bir model adımı istemez, §7'nin bütçesini değiştirmez)**
    - b. Ertelenir; dilim 4 ya da ayrı bir işe bırakılır.
    - c. Ayrı bir model adımı (`candidate_brief`) belgeyi düzyazı olarak yeniden yazar.

## 17. Alt adımlar

Her alt adımda önce testler yazılır ve kırmızı görülür, sonra uygulanır (research-methods.md §5, AGENTS.md TDD kuralı).

1. **Sözleşmeler.** `contracts/research/claim-decomposition.schema.json` (`formulations`, `validation_plan` dahil), `kill-search-plan.schema.json`, `claim-assessment.schema.json`; `common.schema.json`'a üç yeni `$def` (`research_candidate_id`, `candidate_version_id`, `claim_element_ref`); `step-input.schema.json`'a çizgi kökenli bir `candidate`'ın taşıyacağı `ChainEndUncertainty` alanları (dilim 2'nin §8.2'sindeki `chain_target` eklentisine benzer bir örüntüyle, ama slice 2'nin kendi işi olduğu için gerçek ekleme oradan gelir). `domain/contracts.py::SCHEMA_VERSIONS`/`TASK_OUTPUTS`. Test: `tests/test_contracts.py`'ye şema geçerlilik ve kapalılık testleri; `formulations` sayısının `requested_formulations`'ı aşamayacağı denetimi. Çıkış: modelsiz şema testleri yeşil.
2. **Veri modeli.** Migration: `report_stable_gaps` (dilim 4'ten benimsenen, §15.3), `research_candidates` (`source_gap_id` → `report_stable_gaps.id`; `chain_end_uncertainty_id` → dilim 2'nin `chain_end_uncertainties(id)`'ine FK dahil), `candidate_versions` (`validation_plan` dahil), `claim_elements`, `kill_searches`, `kill_search_queries`, `claim_search_memberships`, `claim_matrix_cells`, `claim_matrix_evidence`, `candidate_status_history`, `candidate_version_alternatives`; `runs.kind` genişlemesi. `workflow/report/identity.py` (yeni dosya, dilim 4'ün adlandırdığı modül, §15.3): yalnız `fingerprint_gap(kind, basis) -> str` ve `resolve_stable_gap(store, research_id, kind, basis) -> str`; `match_claims` dilim 4'ün eklediği fonksiyondur, burada yazılmaz. Test: migration + foreign key + `purge_research` temizliği; `tests/test_report_identity.py`'ye dört `kind`in `basis_fingerprint` hesaplaması (deterministik, aynı temel küme aynı `stable_gap_id`'yi verir). Çıkış: depolama testleri yeşil.
3. **`claim_decomposition` adımı ve kullanıcı yönlendirmesi (adım 0).** `flow.py::_claim_decomposition`, yeni run kind, `Store` metodları; bir aday çizgi ucundan açıldığında StepInput'a çizginin düğüm/bağ kayıtlarının eklenmesi; `requested_formulations` desteği ve seçilmeyen biçimlerin `candidate_version_alternatives`'e yazılması. Test: sahte adaptörle bir `report_gaps` satırından ve bir çizgi ucundan aday açma, sürüm 1 ve öğeler doğru kaydedilir; allowlist dışı kaynak reddedilir; 3 biçim istenince 3'ü de saklanır, seçilen normal sürüm olur. Çıkış: akış testi yeşil.
4. **`kill_search_plan` ve sorgu derleme.** `flow.py::_kill_search_plan`; `kill_searches`/`kill_search_queries` kaydı. Test: sahte plan çıktısından derlenen sorgular `query_rules.query_issues`'tan geçer (mevcut `query_compiler` testleriyle aynı desende); en az bir `adjacent_field` kavramı olmadan gelen plan `candidate-check.md`'nin kuralına göre yeniden denetlenir (bu bir kod reddi değil, `report_review` benzeri bir uyarı; kod yalnız kavram sayısını/rolünü denetler). Çıkış: derleme testleri yeşil.
5. **Sağlayıcı aramaları.** `_search`'ün kill-search run'ında yeniden kullanımı; DOI birleşmesi. Test: D18'in aynısı (bir sorgu başarısız, diğerleri sürer; hiçbiri başarılı olmazsa `outcome = 'not_run'`); aynı DOI'li kaynak ana discovery'nin `candidates` satırıyla birleşir. Çıkış: arama testleri yeşil.
6. **`kill_search_screening`.** Yeni görev türü, `ScreeningProposal` yeniden kullanımı, `claim_search_memberships` yazımı. Test: T08 benzeri izolasyon — kill-search kararları `selections`/`corpus_memberships`'i değiştirmez. Çıkış: izolasyon testi yeşil.
7. **`pdf_collection` kapsam genişletmesi.** `target_json.candidate_version_id` desteği; pasaj sıralaması element metinleriyle. Test: sahte kütüphanede yalnız `include` işaretli kaynaklar toplanır; element başına en iyi pasajlar seçilir. Çıkış: kapsam testi yeşil.
8. **`claim_assessment` adımı.** Model adımı, `claim_matrix_cells`/`claim_matrix_evidence` yazımı, `insufficient_access` ön-yazımı. Test: EvidenceCellDraft benzeri denetimler (allowlist, alıntı bulunabilirliği, `uncertain` için de kanıt zorunlu); PDF'i olmayan kaynak modele hiç verilmeden `insufficient_access` alır. Çıkış: matris testleri yeşil.
9. **Durum türetme ve geçmiş.** §6 mantığı kodda; `candidate_status_history` yazımı; `report_gaps.kill_search_status` senkron kopyası; override uç noktası. Test: §6'daki beş durumun her biri için bir senaryo; override sonraki otomatik hesaplamayla ezilmez. Çıkış: durum testleri yeşil.
10. **Rapor bağlantısı.** VI/VII görünümünün `kill_search_status`'u okuması; yasak sözcük denetimine "open için arama kaydı var mı" eklenir. Test: T12'nin yürütülebilir hâli (§12); rapor metni değişmeden rozet güncellenir. Çıkış: rapor bağlantı testi yeşil.
11. **Arayüz.** Aday kartı (kullanıcı yönlendirmesi düzenleme alanları ve "Alternatif biçim öner" seçim ekranı dahil), dilim 2'nin çizgi görünümünden giriş noktası, kill-search zaman çizelgesi, matris görünümü, durum rozeti/override, "Export candidate brief" eylemi; `api.ts`, `i18n.ts`. Test: Playwright fixture senaryosu (§12), masaüstü + 390 px, açık/koyu tema. Çıkış: `npm run build`, `npm run lint`, acceptance yeşil.
12. **Kapanış: gerçek model denemesi ve ölçüm.** `gpt-5.6-luna` ile bir gerçek `report_gaps` adayı üzerinde uçtan uca kill-search; §13'teki ön kayıtlı beklentilerle karşılaştırma; davranış vakaları (§9.5) koşulur; karar kaydına D-girdisi (Evidence, Limits).
