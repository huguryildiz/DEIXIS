<!-- Tasarım kararları ve denetimi (gpt-6.1-sol · high, salt okunur): karar turu (§16, 10 soru + 6 ek soru) Claude ile ortak; tasarım denetimi: tur 1 hazır değil (4 yüksek, 4 orta, 1 düşük; hepsi işlendi), tur 2 hazır değil (2 yüksek, 2 orta, 1 düşük; hepsi işlendi), tur 3 hazır değil (1 yüksek, 1 düşük; işlendi), tur 4 hazır (0 yüksek). Ham cevaplar /tmp/s3d-a1.md, s3d-a2.md, s3d-a3.md, s3d-a4.md, s3d-a5.md. -->
# P6 dilim 3 — iddiaya özgü kill-search ve aday kartı: tasarım notu

**Tarih:** 17 Eylül 2026 (taslak), 1 Ekim 2026 (yeniden yazım, `06a146d` üzerinde). **Durum:** uygulamaya kabul için hazırlandı; kararlar §16'da, batch'ler §17'de, kalıcı kayıt `docs/decisions.md` D143. Bu not bir tasarımdır: kod, migration, model çağrısı ve ölçüm yoktur; kabul, uygulamanın doğrulandığı anlamına gelmez. 17 Eylül taslağı dilim 1 ve dilim 2'nin kodundan önce yazılmıştı; mevcut kodla karşılaştırılan durum §0 ve §1'de kayıtlıdır. Sahibin isteği gereği dilim 3, dilim 2'den (dokuz batch, yaklaşık 15 saat) dar tutuldu: **dört yapım batch'i, bir geliştirme davranış batch'i ve bir ölçüm batch'i**.

## Kısaca

Sahip, raporun "cevaplanmamış yön" listesinden ya da kendi yazdığı bir cümleden bir **aday** açar. Aday, tek iddialık sürümlü bir karttır: iddia, koşullar, test edilebilir öğeler, en yakın basit açıklama, kritik varsayım, doğrulama planı. Sahip kartı düzenleyebilir (her düzenleme yeni bir sürümdür). Sonra **kill-search** başlatır: model iddiadan iki terim bloğu yazar, kod bunları sağlayıcı sorgularına çevirir ve gönderir, bulunan işlerden sağlayıcılar arası sırayla seçilen ilk sekizi iddianın öğelerine karşı başlık ve özet üzerinden değerlendirilir, kod sonuçtan beş durumdan birini türetir (`not_run`, `undecided`, `narrowed`, `closed`, `open`). Sahip gerekçe yazarak kendi kararını ayrıca ekleyebilir; kod durumu ve sahibin kararı yan yana durur.

Bu not 14 Eylül 2026 Chain of Ideas kararının ([README](../../README.md#selected-synthesis-method-chain-of-ideas)) **adım 4'ün "kart açıldıktan sonra düzenleme" kısmını, adım 5'in iddiaya özgü aramasını ve adım 6'nın doğrulama planı alanını** kurar. Adım 5'in "alandaki en güçlü önceki çalışma" ve "doğrudan atıf komşuları" kollarını kurmaz: ikisi dilim 2'nin yapılmamış 2b parçasına dayanır (§15). Kill-search kullanıcının başlattığı, bütçeli, tek adaya özgü bir eylemdir; sıradan bir soru için ya da her aday için kendiliğinden çalışmaz. Aranan işler **araştırmanın kaynak listesine hiç girmez**. Hiçbir durum "özgün" ya da "boşluk" demek değildir; `open` yalnızca "okunan metinde eşleşme yok" demektir ve okuma derinliği hep yazılıdır. Deney tasarımı ve yürütmesi bu dilimde de yoktur.

## 0. Taslağın bugünkü koda göre yanlış kalan yerleri

| # | Taslak diyordu | `06a146d`'de durum | Bu notta karşılığı |
|---|---|---|---|
| F1 | Dilim 2'nin `chains`, `chain_end_uncertainties`, `citation_expansions`, `field_baseline_selections` tabloları var; dördüncü gap türü `chain_end_uncertainty` | Yok. Dilim 2 yalnız `lineage_links` ailesini kurdu (D131–D141); devam-yok işareti, ileri denetim, yükseltme ve rapor girişi 2b/2c'ye bırakıldı ve yapılmadı. `GAP_KINDS` üç değerlidir | Bu dilim yalnız üç mevcut türü tüketir. Çizgi kökenli aday, atıf genişletmesi ve alan tabanı kolu ertelendi (§15) |
| F2 | Kill-search'ün bulduğu kayıtlar araştırmanın `works`/`candidates`'ına DOI ile birleşir, yalnız tarama kararı ayrı tabloya yazılır | `Store.record_search` araştırma için `search_runs`, `candidates` ve `corpus_memberships` yazar; `sw` araştırmada `links.link_records` da çağırır. Onu kullanmak kill-search sonuçlarını sessizce araştırmanın aday havuzuna koyar, yani taslağın yasakladığı şeyi yapar | Kill-search kendi depolama yöntemini kullanır: yalnız `upsert_provider_source` (paylaşılan kaynak kaydı) ve kendi `kill_search_hits` tablosu. `record_search`, `add_search_run`, `add_to_corpus`, `link_records` çağrılmaz; `corpus_memberships`, seçimler, keşif sayıları ve `selection_revision` değişmez (§2, §12) |
| F3 | `SearchPlan` biçimi (`concepts`/`providers`) `query_compiler.compile_queries` ile derlenir | `SearchPlan` sözleşmesi kalmadı; keşif artık model yazımlı `sw` sorgu bloğuyla çalışır (`search-query.schema.json`, D92). `providers.query_compiler.compile_queries(plan)` hâlâ var ama akış onu çağırmıyor; akış `compile_block_queries` ve `search_query.compile_queries` kullanıyor | Model iki terim bloğu yazar, kod `compile_block_queries` ile sağlayıcı başına tek sorguya çevirir (§2 adım 2, §8). Eski `compile_queries(plan)` canlandırılmaz |
| F4 | `report_gaps.kill_search_status` kod tarafından eşzamanlı yazılır, `undecided` eklenir; `gap_id` her yeniden yazımda yeniden verilir | `0035`'te `CHECK (kill_search_status IN ('not_run','narrowed','closed','open'))` var; `undecided` eklemek ya da geri yazmak `report_gaps` yeniden kurmayı ve `workflow/report/*`'a dokunmayı gerektirir. `save_gaps` aynı `(report_id, gap_id)` çakışmasında satırı **yerinde günceller**: `report_gaps.id` korunur, metin, dayanak ve köken değişebilir; yeni rapor sürümü yeni satır üretir. `report_stable_gaps` (dilim 4) yok | Durum **okuma anında** aday tablolarından hesaplanır, `report_gaps`'e geri yazılmaz; aday gap'in bir **anlık kopyasını ve içerik parmak izini** taşır, aynı satır sonradan farklı içerikle yeniden yazılmışsa yeni aday açılır (§2 adım 0, §7). Rapor VI/VII rozeti ve yasak sözcük gevşemesi ertelendi |
| F5 | Aday, rapor VI'daki bir satırdan açılır | Gerçek modelle tamamlanmış bir rapor yok (D124, D126, D128: bölüm IV'te durdu); VI'nın gerçek model çıktısı sınanmadı | İkinci giriş eklendi: sahibin yazdığı iddia (`owner_text`). Ölçüm bu girişi kullanır (§2, §13) |
| F6 | `pdf_collection` kapsamı aday sürümüne genişletilir, bulunan işlerin PDF'i toplanır | `pdf_collection`, `fulltext_fetch` ve pasaj hattı araştırma korpusuna bağlıdır; kill-search işleri o hatta değildir | Bu dilimde PDF edinme yok. Değerlendirme başlık, özet ve zaten saklı pasajlar üzerindendir; okuma derinliği her hücrede yazılıdır (§5, §14) |
| F7 | `claim_search_memberships`, ayrı `kill_search_screening` görevi | Ayrı tarama görevi bu dilimin boyutunu büyütür ve ikinci bir model hatası katmanı ekler | Tarama değerlendirme adımına katıldı: iş başına tek çağrı hem yakınlığı hem öğe matrisini verir (§2) |
| F8 | Matris hücresi `(sürüm, öğe, kaynak)` ile tekil | Aynı sürümde iki ayrı kill-search olabilir; hücreler birbirini ezer ya da karışır | Hücre `kill_search_id` ile bağlıdır (§7) |
| F9 | "AGENTS.md TDD kuralı" | Böyle bir zorunluluk AGENTS.md'de yoktur | Cümle kaldırıldı; her batch kendi testini yazar ama kural olarak anılmaz |

## 1. Kodda bugün olan (`06a146d`'de doğrulandı)

| Parça | Durum | Bu dilimde kullanımı |
|---|---|---|
| `runs.kind` / `runs.stage` CHECK (`0059`) | `kind`: `discovery, answer, table_columns, table_fill, cell_recheck, research_title, pdf_collection, pdf_ocr, report, fulltext_fetch, fulltext_adjudication, lineage_links`; `stage` zaten `candidate` ve `claim_check` içerir ve hiç kullanılmadı | `kind` iki değerle genişler (`claim_decomposition`, `kill_search`), `runs` yeniden kurulur; ikisi de `stage = 'candidate'` (`create_run`'daki stage eşlemesi açıkça eklenir, yoksa `extraction` düşer) |
| `ResearchFlow.execute` | `kind` zinciri; bilinmeyen kind `table_columns` dalına düşer | İki yeni açık dal; düşme yolu kullanılmaz |
| `Store.create_run` | Araştırma başına **tek etkin run** (`ACTIVE_RUN_STATUSES`) | Kill-search ve ayrıştırma da bu kuralı paylaşır; ayrı kilit eklenmez. Devam (`resume`) başka etkin run varken reddedilir |
| `flow._model_step` | StepInput, izin listesi, kısa tutamaçlar (D12/D127), tek onarım, `ModelCallLimiter`, `model_mismatch` | Üç yeni görev aynı yolu kullanır (§8) |
| `providers/query_compiler.compile_block_queries` | Sözlükten (`terms` içinde `block`, `root`, `in_query`, `phrase`, `dropped`) sağlayıcı başına tek sorgu; `query_rules.query_issues` denetimi; çıkarılan terimleri `dropped_terms` olarak döner | Kill-search sorguları buradan derlenir (§2, §8); sağlayıcı söz diziminin denetimi aynen geçerlidir |
| `Store.upsert_provider_source` | Sağlayıcı kaydını `works`/`source_versions`'a yazar, araştırmaya bağlamaz | Kill-search'ün tek ortak yazma noktası |
| `Store.record_search`, `add_to_corpus`, `link_records` | Araştırma kapsamına yazar (F2) | **Çağrılmaz** |
| `Store.passages_for`, `passage_view` | Pasaj görünümü `was_member` ister | Aday kapsamlı, ayrı bir erişim denetimi gerekir (§9) |
| `report_gaps` (`0035`), `workflow/report/store.py::save_gaps`, `domain/contracts.GAP_KINDS` | Üç tür: `stated_limitation`, `conflicting_evidence`, `corpus_absence`; `basis_json`, `provenance_json` | Salt okunur kaynak: aday bir satırın anlık kopyasını alır; `workflow/report/*` ve `report_*` şemalarına dokunulmaz |
| `domain/skill.py::RUNTIME_FILES`, `SKILL.md` | Paket hash'i yalnız `RUNTIME_FILES`'taki dosyalardan; `SKILL.md` "iddiaya özgü kill-search ... yok" der | Üç görev ve `references/candidate-check.md` eklenir, hash hareket eder, `SKILL.md` daraltılır (§8) |
| `Store.purge_research`, `purge_sources`, `cited_source_versions`, `research_cites_asset`, `asset_impact`, `backup._referenced_files`, `_delete_tables` | Mevcut tablolar için yaşam döngüsü | Aday tabloları bu yollara eklenir (§9) |
| `README.md` Chain of Ideas (14 Eylül) | Altı adımlı sıra | §Kısaca'daki kısmı kurulur |

## 2. Akış

0. **Aday açma** (kod işi, model çağırmaz). İki giriş:
   - **`report_gap`**: sahip bir raporun VI bölümündeki bir gap satırında "Investigate" der. Kod satırın `kind`ını `GAP_KINDS`'e karşı, satırın araştırmaya aitliğini ise rapor üzerinden doğrular ve `text`, `basis_json`, `provenance_json`, `kind` ile `report_id` ve `report_gaps.id` değerlerini **düz metin olarak** adayın kendi kaydına kopyalar. Aday, o `report_gaps` satırının sonradan yok olmasına ya da raporun yeniden yazılmasına bağlı değildir. Kopyayla birlikte `kind`, `text` ve `basis_json`'dan hesaplanan bir **içerik parmak izi** saklanır ve dayanağın o andaki görünür içeriği (hücre değerleri ve pasaj alıntı metinleri) `origin_basis_view_json`'a yazılır, böylece dayanak kayıtları sonradan silinse de kart incelenebilir. Aynı `report_gaps.id` aynı parmak iziyle ikinci kez açılırsa mevcut aday döner; satır sonradan farklı içerikle yeniden yazılmışsa (`save_gaps` yerinde günceller) parmak izi uyuşmaz ve yeni aday açılır, eskisi 'köken değişti' ibaresiyle kalır. Rapor sürümleri arası eşleştirme yoktur (§15).
   - **`owner_text`**: sahip bir araştırma içinde kendi cümlesini yazar. Kaynak dayanağı boş olabilir. Kayıt "sahibin önerisi" diye işaretlenir; sonraki ayrıştırma ve doğrulama planı literatürce desteklenmiş bulgu olarak sunulmaz.
1. **`claim_decomposition`** (run, tek model adımı). Adayın metni ve dayanağından **tek** bir sürümlü iddia üretir: `claim_statement`, `conditions`, 2–6 `elements` (mekanizma/koşul/sonuç/parametre), `nearest_simple_explanation` (verilen kayıtlardan söylenemiyorsa `null`), `critical_assumption`, `validation_plan` (hangi kontrolün iddiayı destekleyeceği/daraltacağı/zayıflatacağı; deney tasarımı değil). Alternatif biçim yoktur. Başarı yeni bir `candidate_versions` satırı ve öğeleri yazar.
2. **Sahip düzenlemesi** (kod işi). İddia, koşullar, öğe metinleri, doğrulama planı düzenlenebilir; her düzenleme yeni bir `human_edit` sürümüdür ve bir sürümün kill-search sonuçları o sürüme bağlı kalır, yenisine taşınmaz.
3. **`kill_search`** (run; kullanıcı başlatır; bütçe ve tahmini maliyet düğmenin üstünde yazılı):
   - **a. Sorgu terimleri** (model, 1 adım). İddiadan iki terim bloğu yazar: bir *ortam* bloğu (alan, sistem, koşul) ve bir *görev* bloğu (mekanizma, sonuç); toplam en çok 6 terim, blok başına en çok 3 yedek terim (D92'nin terim disiplini). Model operatör ya da sorgu metni yazmaz. Yedek-terim ikamesi, alan dağılımı sayım yoklaması ve eşlik eden kod sorgusu D92'den **alınmaz**; `compile_block_queries`'in sağlayıcı eleme ve uç nokta yönlendirmesi (`routed=True`) korunur. Kod terimleri bir `vocabulary` sözlüğüne çevirir ve `compile_block_queries`'ten sağlayıcı başına tek sorgu üretir; çıkarılan terimler ve derleyicinin atladıkları gönderimden **önce** kayda yazılır.
   - **b. Sağlayıcı aramaları** (kod). Araştırmanın etkin sağlayıcılarından, `compile_block_queries(..., routed=True)`'nun sw için derleyebildikleri üzerinden (keşifle aynı yönlendirme; Semantic Scholar toplu uç noktası dahil) en çok 6 mantıksal sorgu; bir mantıksal sorgu sağlayıcının tek arama işlemidir ve en çok 20 kayıt döner; sayfalama, sayım yoklaması, zenginleştirme ve genişletme yok. Bir işlemin birden çok HTTP isteği varsa (PubMed: ESearch + EFetch) gerçek istekler taşıma tavanında sayılır; istekleri sınırlanamayan bir bağlayıcı kill-search'ten çıkarılır. Başarısız sorgu kaydedilir, diğerleri sürer (D18). Kayıtlar yalnız `upsert_provider_source` ile kaynak olarak yazılır ve `kill_search_hits`'e eklenir; araştırmanın korpusuna, seçimlerine ya da sayılarına dokunulmaz.
   - **c. Birleştirme ve kesme** (kod). Sağlayıcılar arası sırayla (her sağlayıcının 1., 2., ... kaydı), iş (`work_id`) bazında tekilleştirilerek en çok **8** iş tutulur. Kesilen işler (`rank_cut`) ve yinelenenler sayılarıyla kayda yazılır; her durum metni "N sonuç daha düşük sırada olduğundan okunmadı" cümlesini taşır.
   - **d. Değerlendirme** (model; tutulan iş başına **bir** çağrı, sırayla, eşzamansız değil). Girdi: iddianın öğeleri ve işin başlığı, özeti ve (varsa) zaten saklı pasajları. Ne özeti ne kullanılabilir pasajı olan iş (yalnız başlık/üstveri) modele hiç gönderilmez; kod onu `insufficient_access` yazar. Model işin öğelerle ilişkisini ve her öğe için hücreyi verir (§5, §8).
4. **Durum türetme** (kod; model yok). §5.
5. **Sahip kararı** (kod). Gerekçeli, eklemeli kayıt; kod durumunun üstüne yazılmaz.

**Kapsam dışı kalan Chain of Ideas kolları** (§15): alan tabanı, atıf genişletmesi, çizgi kökenli aday.

## 3. Senaryolar

**S1. Gap'ten aday, kısmi örtüşme.** VI'daki bir `corpus_absence` satırından aday açılır → ayrıştırma 3 öğe verir → sahip bir öğenin metnini düzeltir (sürüm 2) → kill-search 4 sağlayıcıda 4 sorgu gönderir, 31 kayıt gelir, 8 tutulur → bir işin özeti öğelerden birini açıkça destekliyor, öteki ikisi için `no_match_in_supplied_text` → `narrowed`; metin hangi öğenin karşılandığını, okuma derinliğinin "özet" olduğunu ve 23 sonucun okunmadığını söyler.
**S2. Sıfır eşleşme.** Sorguların hepsi `completed`, 8 iş de `unrelated` → `open`; metin "şu sağlayıcılarda şu sorgularla, okunan 8 özette eşleşme yok; 23 sonuç okunmadı; yalnız özet okundu" der. "Özgün", "boşluk", "ilk" yasaktır (yasak sözcük denetimi bu dilimde yalnız aday ekranının kendi metnine uygulanır; rapor metni değişmez).
**S3. Sağlayıcı hatası.** Bir sorgu `rate_limited`, diğerleri başarılı: D18 gibi sürer; durum metni "N sorgudan M'si başarısız" taşır. **Hiçbir** sorgu başarılı olmazsa durum `undecided`'dır (neden: `search_failed`), `not_run` değildir: arama denendi ama hiçbir şey okunmadı.
**S4. Özeti olmayan iş.** Tutulan bir işin yalnız başlığı var: `insufficient_access`, modele gönderilmez. Bu iş `closed` bulgusunu geçersiz kılmaz, ama `open` ya da `narrowed` sonucunu `undecided`'a çeker (§5).
**S5. Başka terminoloji, aynı mekanizma.** Özet aynı mekanizmayı farklı sözcüklerle anlatır: `explicit_support`. Terminoloji farkı tek başına `partial_match`'e indirmez.
**S6. Birleşik iddianın yalnız parçaları.** Bir iş her öğeyi ayrı ayrı destekler ama öğelerin birlikte geçerli olduğunu söylemez: `states_whole_claim: false`, durum `closed` olmaz (`narrowed`).
**S7. Çekici ama geçersiz analoji ve ters sonuç.** Farklı koşullarda aynı mekanizma ya da karşıt sonuç: `condition_alignment: different_conditions`; kod bunu `closed`e saymaz, "çelişki" de ilan etmez; metin "farklı koşullarda farklı sonuç" der.
**S8. Sahibin kendi cümlesi.** `owner_text` ile boş dayanaktan başlanır; ayrıştırma `nearest_simple_explanation: null` döner (uydurulmaz); kart "sahibin önerisi, literatürce desteklenmiş değil" ibaresini taşır.

## 4. Kurallar

- Örtüşme, geçerlilik ve değer ayrı bulgulardır; tek bir "kill skoru" yoktur. Matris her hücrede kendi ilişkisini taşır.
- "Bu iş iddiayı karşılıyor" yalnız aday sürümünü ve o aramayı kapatır, adayın ailesini değil.
- Anlamlı bir koşul farkı yeni bir aday **sürümü** açar; salt ad değişikliğiyle fikir kurtarılmaz.
- Erişim yetersizliği "karar verilemedi"dir, "reddedildi" değil.
- Sıfır sonuç, servis hatası ve okunamayan iş üç ayrı sonuçtur; hiçbiri tek başına özgünlük üretmez.
- Kaynakta açıkça yazılan (`explicit_support`) ile modelin çıkardığı (`reasoned_inference`) ayrı tutulur; çıkarım `closed`i kuramaz.
- Bir sürümün sonucu başka sürüme otomatik taşınmaz.
- Kill-search araştırmanın kaynak listesini, seçimlerini, keşif sayılarını ve `selection_revision`ını değiştirmez.
- Bütçe sonludur; dolunca kalan belirsizlikle durulur. Hiçbir durum yeni bir fikir üretme zorunluluğu doğurmaz.
- Doğrulama planı bir deney tasarımı değildir; araç, protokol, örneklem büyüklüğü ve yürütme adımı önermez.
- Sahibin kararı bağımsız kanıt değildir: arama kapısını (aranmış kanıt) karşılamaz ve her yerde "sahibin kararı" olarak ayrı gösterilir.

## 5. Durum türetme (kod; model yok)

**Hangi arama sayılır.** Sürümün **en son** `kill_search` kaydı, durumu ne olursa olsun (`running`, `paused`, `completed`, `failed`, `stopped`); `not_run` yalnız sürümün hiç `kill_search` kaydı olmadığında döner. En son kayıt `running` ya da `paused` ise durum, kısmi hücreler üzerinden aşağıdaki kurallarla hesaplanır ve `closed` yoksa `undecided` (`search_running` / `search_paused`) olur; daha eski bir biten sonuç kartta "önceki arama" olarak **ayrıca** gösterilir ama durumu belirlemez, yeni bir başarısız ya da sürmekte olan denemenin arkasında da kaybolmaz. Her iş değerlendirmesi kendi adımı başarılı olunca yayımlanır (devam idempotenttir); bu yüzden sürmekte olan, duraklamış ya da `stopped` bir aramada kısmi hücreler vardır ve pozitif bulgu (aşağıda 2. sıra) yine geçerlidir.

**Tutarlılık kuralları (yayımlama anında doğrulayıcı reddeder, tek onarım).** `unrelated` iş için bütün hücreler `no_match_in_supplied_text`; `related` iş için en az bir hücre `explicit_support`, `reasoned_inference` ya da `partial_match`; `uncertain` iş için en az bir hücre `uncertain`. `condition_alignment` yalnız bu üç destek ilişkisinde zorunludur ve `no_match_in_supplied_text` hücresinde boş (`null`) olur; `uncertain` hücrede isteğe bağlıdır. Bu yüzden `unrelated` bir işte koşul farkı ya da kanıtsız `related` iş oluşamaz.

Kurallar sırayla çalışır, ilk uyan kazanır:

| Sıra | Koşul | Durum | Gerekçe |
|---|---|---|---|
| 1 | Sürümün hiç `kill_search` kaydı yok | `not_run` | Hiç aranmadı; `not_run` yalnız bu durumdur |
| 2 | Bir iş için `states_whole_claim = true` (alıntılı) **ve** her öğe `explicit_support` + `aligned` | `closed` | Bir iş iddiayı bütün olarak, aynı koşullarda açıkça söylüyor. `reasoned_inference` kuramaz; ilgisiz ya da erişilemeyen başka iş bu pozitif bulguyu bozmaz; en son kayıtta (kısmi, sürmekte olan ya da duraklamış dahil) geçerlidir. Okuma derinliği özet olabilir; metin bunu yazar |
| 3 | Aşağıdakilerden biri: en son kayıt `running`/`paused` (`search_running`/`search_paused`); biten arama hiçbir sorguda başarılı olmadı (`search_failed`); arama `stopped`/`failed` (`search_incomplete`); `insufficient_access` ya da `not_assessed_budget` iş var; `uncertain` yakınlıkta iş var; bir `related` işte `uncertain` hücre var; bir destek hücresinde `condition_alignment = unclear` | `undecided` | Okunmamış ya da çözülmemiş olası ilgili iş ya da belirsiz hücre varken ne `narrowed` ne `open` doğru olur |
| 4 | Bir destek hücresi (`explicit_support`, `reasoned_inference`, `partial_match`) var (hizalı ya da `different_conditions`) | `narrowed` | Kısmi örtüşme ya da koşul farkı; kalan fark yeni bir sürüm gerektirebilir |
| 5 | En son kayıt `completed`, en az bir sorgu başarılı, tutulan bütün işler değerlendirildi ve hepsi `unrelated` — **ya da** başarılı sorgular hiç kayıt döndürmedi (tutulan iş sıfır) | `open` | "Değerlendirilen alt kümede ve okunan metinde eşleşme yok"; okuma derinliği, kesilen/okunmayan sonuç sayısı ve başarısız sorgu sayısı hep yazılı |
| 6 | Hiçbiri | `undecided` (`unclassified`) | Kapalı başarısızlık: tabloda yeri olmayan bir girdi sessizce `open` olmaz; kayda uyarı yazılır |

`rank_cut` ile kesilen işler `undecided` yapmaz; bir arama sınırıdır ve her durumun metninde sayısıyla yazılır, sonuç "değerlendirilen alt küme" için geçerlidir. Bütçesi biten ya da durdurulan aramada tutulup değerlendirilmemiş işler `not_assessed_budget`tir. Hiçbir durum özgünlük, boşluk ya da yenilik iddiası değildir.

Sahip kararı: `candidate_status_overrides` eklemeli kaydı (durum, zorunlu gerekçe, sürüm). Ekranda "Sahip: closed; arama: not_run" gibi yan yana görünür. Sahibin kararı kod durumunu değiştirmez ve sonraki bir aramayla silinmez; yeni sürüme taşınmaz.

## 6. Bütçe

Başlamadan, düğmenin üstünde gösterilir; sabittir, sahip girmez.

| Adım | Sınır |
|---|---|
| `claim_decomposition` | 1 çağrı + 1 onarım |
| Sorgu terimleri | 1 çağrı + 1 onarım |
| Sağlayıcı aramaları | en çok 6 mantıksal sorgu (sağlayıcının tek arama işlemi), her biri en çok 20 kayıt; sayfalama, sayım yoklaması, zenginleştirme, genişletme dışı; çok istekli işlemin gerçek istekleri taşıma tavanında sayılır |
| Değerlendirme | en çok 8 iş, iş başına 1 çağrı + 1 onarım |

İki ayrı tavan gösterilir ve uygulanır: **taşıma** (gerçek sağlayıcı istekleri; her uygun bağlayıcının sorgu başına istek sayısı ve yeniden deneme sabiti sağlayıcı katmanından okunup K3'te önizlemeye ve dondurulmuş kayda yazılır) ve **model denemesi**. Model denemesi tavanı: her adım için (1 gönderim + 1 onarım) × (1 + 2 hız sınırı yeniden gönderimi) = 6 deneme; iki run için ayrıştırma 6 + sorgu terimleri 6 + değerlendirme 8 × 6 = 48 = **60**. Zaman aşımı yeniden gönderimi bu görevler için **açılmaz**: zaman aşımı mevcut kurala göre adımı `outcome_unknown`/`paused` yapar ve ek hak vermez. Devam (`resume`) hakkı yenilemez. Tavan her gönderimden **önce** kalıcı olarak denetlenir (onarım, hız sınırı yeniden gönderimi ve devam sonrası gönderim dahil); K3 yarıda kalmış onarım/yeniden gönderimin kurtarılmasını sınar. Tahminler ölçülmedi.

## 7. Veri modeli (niyet; geçerli SQL migration'dır)

`runs.kind` CHECK'i `claim_decomposition` ve `kill_search` ile genişler (`0059`'un bütün sütun, indeks ve bağımlı satırlarını koruyan yeniden kurma; `deixis:foreign-keys-off`).

- `research_candidates` (`rcd_`): `research_id`, `origin` (`report_gap` | `owner_text`), `origin_report_id`, `origin_gap_row_id` (düz metin, FK yok), `gap_kind` (`GAP_KINDS` kod denetimli), `origin_text`, `origin_basis_json`, `origin_basis_view_json` (açılış anındaki görünür dayanak içeriği), `origin_provenance_json`, `origin_fingerprint` (`kind`+`text`+`basis_json` özeti), `current_version`, `trashed_at`, `created_at`; `research_id` → `researches` FK. `UNIQUE (research_id, origin_gap_row_id, origin_fingerprint)` yalnız `origin_gap_row_id` dolu olduğunda. Bir tabloya, hücreye ya da canlı rapor satırına yabancı anahtarı yoktur: `_delete_tables` ya da rapor yeniden yazımı kopyalanmış kökeni bozmaz.
- `candidate_versions` (`clv_`): `candidate_id`, `version`, `claim_statement`, `conditions_json`, `nearest_simple_explanation`, `critical_assumption`, `validation_plan`, `origin` (`model_decomposition` | `human_edit`), `step_input_id`, `created_at`; değişmez (eklemeli), `UNIQUE (candidate_id, version)`.
- `claim_elements` (`ele_`): sürüme bağlı (FK), `position`, `text`, `kind`; `UNIQUE (candidate_version_id, position)`.
- `kill_searches` (`kls_`): `candidate_version_id` → `candidate_versions` FK, `run_id` → `runs` FK, `UNIQUE (run_id)`, dondurulmuş `query_block_json`, `rendered_queries_json` ve derleyicinin atladıkları, dondurulmuş sağlayıcı/model/efor seçimi, `outcome` (`running` | `paused` | `completed` | `failed` | `stopped`), sayılar (`found`, `kept`, `rank_cut`, `duplicates`), `created_at`.
- `kill_search_queries`: `UNIQUE (kill_search_id, position)`; arama başına sağlayıcı, sorgu metni, durum (`succeeded` | `failed` | `outcome_unknown`), kayıt sayısı, yük dosyası göstergesi (boş ve başarısız aramalar dahil), `step_id`.
- `kill_search_hits`: `kill_search_id` → `kill_searches` FK, `source_version_id` → `source_versions` FK, `UNIQUE (kill_search_id, source_version_id)`, sıra anahtarı, `kept`, `cut_reason`, `reading_depth` (`abstract` | `stored_passages` | `metadata_only`), değerlendirme durumu (`assessed` | `insufficient_access` | `not_assessed_budget`), `work_relevance`, `states_whole_claim`, `note`, `step_input_id`.
- `claim_matrix_cells` (`cmx_`): `kill_search_id`, `element_id`, `source_version_id`, `relation`, `condition_alignment`, `note`; `UNIQUE (kill_search_id, element_id, source_version_id)`; yayımlama anında her tutulan ve değerlendirilen iş için **her** öğenin hücresi bulunması denetlenir (eksik, yinelenen ve fazla hücre reddedilir).
- `claim_matrix_evidence`: `kill_search_id`, `source_version_id`, `element_id` (boş = **bütün iddia** alıntısı, `states_whole_claim = true` için), `matrix_cell_id` (öğe alıntısı için), `evidence_kind` (`abstract` | `passage`), `passage_id` (yalnız pasaj için), `quote`; her alıntı modele **verilen** metinde `locate_anchor` ile bulunmuş olmalıdır.
- **Yabancı anahtarlar** açıkça: `candidate_versions.candidate_id` → `research_candidates`; `kill_search_queries.kill_search_id` → `kill_searches`; `claim_matrix_cells.kill_search_id`, `element_id`, `source_version_id` → `kill_searches`, `claim_elements`, `source_versions`; `claim_matrix_evidence.matrix_cell_id` → `claim_matrix_cells`, `passage_id` → `passages`; `candidate_status_overrides.candidate_version_id` → `candidate_versions`; `claim_elements.candidate_version_id` → `candidate_versions`.
- **Bütünlük denetimleri** (tetikleyici ya da yayımlama doğrulayıcısı, K1'de ikisinden hangisi seçilirse testli): hücrenin öğesi aramanın aday sürümüne aittir; hücrenin ve kanıtın kaynağı aramanın tutulan ve değerlendirilen bir vuruşudur; bir kanıt satırının `kill_search_id`, `source_version_id` ve `element_id` değerleri bağlı olduğu hücreninkiyle aynıdır (bütün-iddia kanıtında `element_id` boş, hücre bağı boş ve `states_whole_claim = true` olan vuruşa bağlı).
- `candidate_status_overrides`: `candidate_version_id`, `status`, `reason` (zorunlu), `created_at`; eklemeli.

Durum için tablo yoktur: §5 okuma anında hesaplanır. `report_gaps`, `workflow/report/*` ve `report_*` şemaları değişmez.

## 8. Yöntem paketi ve sözleşmeler

`RUNTIME_FILES`: `claim_decomposition`, `kill_search_query`, `claim_assessment` → (`SKILL.md`, `references/candidate-check.md`). `SKILL.md`'nin "iddiaya özgü kill-search ... yok" cümlesi şuna daralır: serbest aday geliştirme, deney tasarımı ve yürütmesi **yok**; iddiaya özgü kill-search yalnız uygulamanın açtığı bir aday kaydı için bu üç görevle çalışır. `skill_package_hash` hareket eder (eski ve yeni hash K2'de kayda yazılır); `provenance.json` ve model rolü kaydı (`step_model`, yetenek bildirimi) birlikte güncellenir. Üç yeni sözleşme `contracts/research/` altında, kapalı şemayla (`additionalProperties: false`), v1:

- **`claim-decomposition`**: `claim_statement`, `conditions`, `elements` (2–6; `element_ref`, `text`, `kind`), `nearest_simple_explanation` (null olabilir), `critical_assumption`, `validation_plan`, `source_ids`, `passage_ids` (izin listesinden), `rationale`. Tek formülasyon; `element_ref` kısa tutamaçtır, kod gerçek `ele_` kimliğine çözer (D12/D127 deseni).
- **`kill-search-query`**: `setting` ve `task` blokları (toplam ≤ 6 terim), blok başına ≤ 3 yedek terim; model operatör ya da sorgu metni yazmaz.
- **`claim-assessment`**: bir iş için `work_relevance` (`unrelated` | `related` | `uncertain`), `states_whole_claim` (boolean; `true` ise bütün iddiayı ve öğelerin birlikte geçerliliğini söyleyen alıntı zorunlu), her öğe için `cells` (`element_ref`, `relation`, `condition_alignment`, `evidence`, `note`); `no_match_in_supplied_text` ve `uncertain` hücreler kanıt **taşımayabilir**, ama `explicit_support`, `reasoned_inference` ve `partial_match` en az bir alıntı ister. `insufficient_access` çıktıda yoktur; yalnız kod yazar. `nearest_match_summary` düz dilde.

Deterministik denetimler (`domain/contracts.py`, mevcut `_check_*` deseninde): izin listesi (kaynak, pasaj, öğe tutamacı), eksik/yinelenen/fazla hücre, alıntının verilen metinde bulunması, `closed` için gereken `states_whole_claim` kanıtı, `validation_plan`'da deney tasarımı sözcüklerinin (araç, protokol, örneklem büyüklüğü) bulunmaması (yüzeysel; içerik doğrulaması değildir). Çıktı sözleşmeye uysa da bilimsel doğrulama sayılmaz.

## 9. Yaşam döngüsü, bütünlük ve güvenlik

K1–K3'ün içinde, ek batch olmadan:

1. **Kaynak yaşam döngüsü.** `purge_research`, `purge_sources`, `cited_source_versions`, `research_cites_asset`, `asset_impact` ve yük dosyası temizliği aday kökenlerini, vuruşları ve kanıtları sayar; yetkili silmede aday çocukları, bağlı run, adım ve pasajlardan **önce** silinir. Araştırma çöpe atma ve geri alma her şeyi korur; `_delete_tables` kopyalanmış aday kökenini bozmaz.
2. **Dayanıklılık ve tekrar.** Aday sürümü, sağlayıcı/model/efor seçimi, sorgu sırası, kaynak sürümleri ve modele verilen pasajlar arama başına dondurulur; yayımlama sürüm korumalıdır. `Idempotency-Key` araştırma, aday, işlem ve istek parmak izine bağlıdır; tekrar özgün sonucu döndürür, başarılı adım yeniden gönderilmez ya da ezilmez. Çalışma yarıda kesilirse `outcome_unknown`/`paused` olur, yeniden denenmez (mevcut kural).
3. **Kontrol.** Değerlendirme çağrıları **sırayla** yapılır; bu yüzden `app.py`'deki iptal yolu (`table_fill` ve `lineage_links` dışındaki run'lar için bağdaştırıcıları keser) bu iki kind için aynen geçerli kalır ve açıkça yazılır. Eşzamanlı çağrılar bu dilimde yoktur. Aday run'ı araştırmanın `scope_revision`ına bağlıdır: yeni bir kapsam revizyonu run'ı durdurur (`_checkpoint`); aday ve sürümleri etkilenmez.
4. **Kanıt erişimi.** `passage_view` `was_member` ister; kill-search işleri üye değildir. Aday kapsamlı bir erişim denetimi, yalnız o aramaya ait tutulan işlerin modele **gerçekten verilen** metnini (özet ve pasajlar) gösterir ve korpus korumalarını gevşetmez.
5. **Yedek ve geri yükleme.** Sorgu yük dosyaları (başarısız ve boş aramalar dahil) `backup._referenced_files` ve yetim denetimine girer; geri yükleme sürümleri, vuruşları, sahip kararlarını, alıntıları, dosyaları ve yabancı anahtarları korur.
6. **Okuma derinliği.** `abstract`, `stored_passages`, `metadata_only` ayrı kalır; "saklı pasaj" tam metin okundu demek değildir.

## 10. Arayüz (yalnız davranış)

`.impeccable.md` ve AGENTS.md hiyerarşisi geçerlidir; mevcut bileşenler (Transcript zaman çizelgesi, kanıt görünümü, Notice) yeniden kullanılır.

- **Giriş.** Rapor VI'daki her gap satırında "Investigate" ve, aday zaten varsa, ona bağlantı; satırın yanında aday durumu bir aday listesi uç noktasından okunur, rapor görünümü değişmez. Ayrıca araştırma sayfasında "Add candidate" (sahibin kendi cümlesi).
- **Aday kartı.** Kaynak (gap ya da "sahibin önerisi"), iddia, koşullar, öğeler, en yakın basit açıklama, kritik varsayım, doğrulama planı; sürüm numarası ve önceki sürümler katlanmış. Düzenleme yeni sürüm açar. `owner_text` adayında "literatürce desteklenmiş değil" ibaresi.
- **Kill-search.** Bütçe ve tahmini maliyet düğmenin üstünde; run sürerken düğme kapalı. Zaman çizelgesi tek satır: terimler → sağlayıcı aramaları (sağlayıcı başına alt satır, hata dahil) → değerlendirme. Başlık: "Search for prior art on this claim".
- **Matris.** Satırlar tutulan işler, sütunlar öğeler; ilişki etiketi metinle (yalnız renkle değil; `insufficient_access` ve `uncertain` amber, kırmızı yok). "Show evidence" özeti ya da pasajı gösterir. Kesilen sonuç sayısı ve okuma derinliği matrisin üstünde yazılı.
- **Durum.** Kod durumu ve "Kod bu matristen türetti" notu; yanında sahip kararı ("Sahip: closed; arama: not_run") ve gerekçeli "Record my decision" eylemi.
- Dil: İngilizce ve Türkçe metin, 390 px ve masaüstü, açık ve koyu tema.

## 11. Kim neyi doğrular

| Kural | Kod | Model | Doğrulanmayan |
|---|---|---|---|
| Ayrıştırma | Kaynak/pasaj izin listesi, öğe sayısı | İddianın test edilebilir bölündüğü | Bölümlemenin bilimsel tamlığı |
| Sorgu | Blok/terim sayısı, sağlayıcı söz dizimi, atlananların kaydı | Terimlerin iddiayı temsil ettiği | Geri çağırım (ölçülmedi) |
| Değerlendirme | Alıntı verilen metinde var, hücre eksiksiz | İlişki, koşul hizası, bütün iddia | Alıntının bağlamının doğru aktarıldığı; özetin işin tamamını yansıttığı |
| Durum | §5 tablosu kodda | — | Matris yanlışsa durum da yanlış |
| Sahip kararı | Gerekçe zorunlu | — | Kararın haklılığı |

## 12. Testler

**Modelsiz depolama ve saf hesap (K1):** migration (P6 öncesi boş kopyada ve dolu kopyada, `runs` satırları korunur, yabancı anahtar temiz); aday açma iki kökenle (gap anlık kopyası, `owner_text`), ikinci açışta aynı aday; bir sürüm eklemesi değişmezdir; **izolasyon**: bir kill-search yazması `corpus_memberships`, `candidates`, seçimler, `selection_revision` ve keşif sayılarını değiştirmez, `record_search` hiç çağrılmaz; `purge_research` ve yetkili `purge_sources`; çöpe atma/geri alma; yedek ve geri yükleme; §5'in her satırı için sabit vaka kümesiyle durum türetme (ölçüm K4 satırının modelsiz karşılığı, §13); birleştirme/kesme (sağlayıcılar arası sıra, `work_id` tekilleştirme, 8'e kesme); blok sözlüğünden `compile_block_queries` sonucu `query_rules.query_issues`'ten geçer.
**Sözleşme (K2):** üç şemanın kapalılığı; hücre eksik/yinelenen/fazla reddi; `states_whole_claim: true` alıntısız reddi; `no_match_in_supplied_text` kanıtsız kabul; alıntı bulunamazsa tek onarım; paket bütünlüğü ve hash hareketi (`test_skill.py`).
**Akış (K3, sahte adaptör):** gap'ten ve `owner_text`ten ayrıştırma; sürüm 1; düzenleme sürüm 2; kill-search uçtan uca; D18 (bir sorgu başarısız, diğerleri sürer; hepsi başarısızsa `undecided`/`search_failed`); metadata-only iş modele gönderilmez ve `insufficient_access` olur; yarıda kesme ve devam (başarılı adım yeniden gönderilmez, hak yenilenmez); iptal; yeni kapsam revizyonu run'ı durdurur; ikinci etkin run 409; başka araştırmanın adayı 404; `Idempotency-Key` tekrarı; sahip kararı gerekçesiz 422; devam, başka etkin run varken reddedilir.
**Web (K4, Playwright, senaryolu model):** VI satırı → aday → düzenleme → kill-search → matris → durum + sahip kararı; `owner_text` ile giriş; masaüstü ve 390 px, açık ve koyu tema.

## 13. Ölçüm planı (K6; koşudan önce dondurulur)

Kural aynı (D55, dilim 2 §14): beklentiler ayrı bir dosyada (`p6-slice3-expectations.md`) donar ve commit'lenir, sonradan yorumlanıp uydurulmaz. Geliştirme davranış vakaları (K5) ve bağımsız ölçüm (K6) ayrıdır; K5'te kullanılan iddia ve korpus K6'da kullanılmaz. K6 geçici bir `DEIXIS_DATA_DIR`de boş bir araştırma açar ve adayları `owner_text` girişiyle, **iddia sürümü Claude'un yazdığı dondurulmuş iddia, öğeler, koşullar ve doğrulama planıyla** (`human_edit`, sürüm 1) oluşturur. Böylece ölçüm kill-search'ü ölçer; ayrıştırma ölçülmez ve bu sonuçta açıkça "ayrıştırma ölçülmedi" diye yazılır.

İddia kümesi: taze bir konudan 6 iddia; beşi için 1–3 işlik önceden yazılmış en yakın iş kümesi `N`, en az biri için `N` boş ("yakın iş bilinmiyor": Claude'un etiketi, doğrulanmamış; bu iddiadan oran üretilmez). Her `N` işi için dondurma dosyasına işin sağlayıcıdan gelen **özet metninin hash'i** ve Claude'un o özet metni ile dondurulmuş öğelere karşı yazdığı **beklenen ilişki** ("bütün iddiayı söylüyor / bazı öğeleri söylüyor / söylemiyor") koşudan önce yazılır; pasaj saklıysa ve modele verilen girdiye giriyorsa verilen **bütün** metnin (özet ve pasajlar) hash'i dondurulur. Koşuda iş dondurulandan farklı bir metinle gelirse o iş değerlendirmeden çıkar ve ayrıca sayılır; `S2`/`S3` payda iddia düzeyindedir: etiketli bütün işleri çıkan iddia paydadan çıkar, aksi hâlde iddia kalır ve çıkan iş sayısı yazılır.

| # | Ne | Payda ve tanım |
|---|---|---|
| S1 | Geri çağırım kaçağı | `N`'deki işlerden kaçı sağlayıcı sonuçlarında hiç yok / sonuçta var ama kesildi / tutuldu. Üçü ayrı sayılır |
| S2 | Yanlış `open` | Dondurulmuş beklentisi "en az bir öğeyi söylüyor" olan bir iş **tutulmuş ve değerlendirilmişken** `open` türeyen iddia sayısı / böyle iddia sayısı |
| S3 | Yanlış `closed` | Dondurulmuş beklentisi "`N`'deki hiçbir iş bütün iddiayı söylemiyor" olan iddialarda `closed` türeyen sayısı / bu iddia sayısı. Her `closed` için Claude kapatan işin bütün-iddia alıntısını okur: `N` dışı, etiketsiz bir iş gerçekten bütün iddiayı söylüyorsa bu "etiketsiz tanık bulundu" diye **ayrı** sayılır ve yanlış `closed` sayılmaz; söylemiyorsa yanlış `closed`tir |
| S4 | Alıntı geçerliliği | Alıntıların modele verilen metinde bulunma oranı (yapısal) ve Claude'un okuduğu bir örneklemde desteklediği (model değerlendirmesi, insan denetimi değil). Örneklem: sabit tohumla 20 hücre (daha azsa hepsi), okuyucu Claude, efor dondurma dosyasında yazılı |
| S5 | Bütçe ve süre | Uçtan uca süre, model denemeleri ve sağlayıcı istekleri §6 tavanlarına karşı |

Etiketleyen Claude'dur, sahip etiketlemedikçe; Claude'un okuması insan denetimi sayılmaz. Payda sıfırsa "ölçülemedi". "Tek koşu": altı iddianın tek serisi, yeniden koşu yok. Örneklem küçüktür; genel doğruluk, geri çağırım ya da hız iddiası çıkarılmaz. **Dondurma:** hazırlıktan önce konu, dışlanan konular ve korpuslar (slice 2 §14 listesi, L9 NLP korpusu, K5 iddiaları), ürün commit'i, `skill_package_hash`, bağlantı/model/efor (`codex` / `gpt-5.6-luna`), dondurulmuş iddialar, `N` kümeleri ve özet hash'leri, beklenen ilişkiler (hash'i ve zamanı kayıtlı), S4 örneklem tohumu ve okuyucu eforu, oturum ve süre tavanı; dondurma commit'i ölçümden önce atılır ve bir gpt-6.1-sol incelemesinden geçer. Müdahale yok; D141'deki gibi kapıda durursa sonuç olduğu gibi yazılır; başarı da başarısızlık da `decisions.md`'de ayrı karar olur. Gerçek model kotası yoksa batch bekler, başka model konmaz.

## 14. Varsayımlar ve sınırlar

- Değerlendirme başlık, özet ve işin zaten saklı pasajlar üzerindendir; özet bir işin tamamını yansıtmaz, saklı pasaj da tam metin okuması değildir. `closed` bu yüzden yalnız verilen metnin iddiayı açıkça ve bütün olarak söylediği durumda kurulur; `open` hiçbir zaman "yok" değil, "okunan metinde eşleşme yok"tur. Tam metin okuması ve PDF edinme sonraki bir dilimdir (§15).
- Geri çağırım (sağlayıcılar, terimler, en çok 8 iş) ölçülmedi; D55'teki sorunlar burada da geçerlidir ve S1'de görünür.
- Gerçek modelle tamamlanmış bir rapor yoktur (D124, D126, D128); gap girişi gerçek VI çıktısıyla hiç sınanmadı. Dilim 2'nin gerçek-model bağ üretimi ölçülmedi (D140, D141); bu dilim ona dayanmaz.
- Matris yapısal olarak geçerli olsa da semantik doğrulama değildir.
- Bütçe sayıları (8 iş, 20 kayıt, 6 sorgu, 60 deneme) bu dilim için ölçülmedi.
- Aday sürümleri arasında sonuç taşınmaz; bu, aynı aday için yeniden arama maliyetidir (bilinen ödün).
- `validation_plan` kalitesi ölçülmez; kod yalnız deney tasarımı sözcüklerini yüzeysel denetler.
- Gerçek `codex app-server`'ın eşzamanlı turları (D61) bu dilimde kullanılmaz; çağrılar sıralıdır.
- Rapor gap'ini kopyalamak, aynı sorunun ikinci bir aday olarak açılabileceği anlamına gelir: aynı `report_gaps.id` aynı parmak iziyle yinelenmez, ama satır sonradan farklı içerikle yeniden yazılırsa ya da başka bir rapor sürümünde yeni satır olarak gelirse yinelenebilir.

## 15. Ertelenenler (nedeniyle)

- Çizgi kökenli aday (`chain_end_uncertainty`), ileri atıf denetimi, atıf genişletmesi, alan tabanı kolu: dilim 2b/2c yapılmadı (F1).
- `report_gaps.kill_search_status` geri yazımı, rapor VI/VII durum rozeti, VII'nin adaydan durum devralması, yasak sözcük gevşemesinin (T12) `open` için açılması: `report_gaps` yeniden kurma ve `workflow/report/*` değişikliği ister (F4); rapor entegrasyonuna ya da dilim 4'e kalır.
- `report_stable_gaps` ve rapor sürümleri arası aday eşleştirmesi: dilim 4.
- PDF edinme, tam metin değerlendirmesi, bulunan işlerin araştırma korpusuna eklenmesi: ayrı dilim; en büyük iç sınır budur.
- Alternatif iddia formülasyonları, aday dosyası dışa aktarımı, adayların karşılaştırmalı sıralaması, eşzamanlı değerlendirme çağrıları, deney tasarımı ve yürütmesi.

## 16. Kararlar

Kararlar sahibin talimatıyla **Claude ve gpt-6.1-sol tarafından, 1 Ekim 2026'da** birlikte verildi; sahibe soru sorulmadı. Karar turu `/tmp/s3d-a1.md`. Sol dört yerde Claude'un önerisinden ayrıldı (Q5, X1, X3, X6) ve Claude kabul etti; Q4, Q1, X2 ve X4'te Sol kısıt ekledi. Kalıcı kayıt: `docs/decisions.md` D143.

1. **Beş durum (taslak §16.1: dört durum önerisi).** Önerilen/kabul: `undecided` taslağın üç durumuna dördüncü olarak eklenir (`not_run` ile birlikte beş), yalnız aday tablolarında; `report_gaps` değişmez. Sol'un eki: hiçbir sorgunun başarılı olmadığı aranmış durum `undecided` (`search_failed`), `not_run` yalnız hiç aranmamıştır (taslak `not_run` diyordu). *Claude önerdi, Sol ekledi, Claude kabul etti.*
2. **Ayrı kapsam (§16.2).** Ayrı: kill-search kendi sorgu, vuruş ve değerlendirme kayıtlarını yazar; `record_search`, `add_search_run`, `add_to_corpus`, `link_records` çağrılmaz. *Claude ve Sol.*
3. **Aranmadan sahip kararı (§16.3).** Evet; gerekçeli, eklemeli, sürüme bağlı, kod durumunun yanında gösterilir ve hiçbir aranmış-kanıt kapısını karşılamaz. *Claude ve Sol.*
4. **Sürümler (§16.4).** Sürümler, değişmez; sonuç eski sürüme bağlı kalır. Sol'un eki: hücreler `kill_search_id`'ye bağlanır (§0 F8). *Claude önerdi, Sol ekledi.*
5. **Bütçe (§16.5).** 1 ayrıştırma + 1 sorgu + en çok 8 değerlendirme çağrısı; **Sol'un değişikliği:** "6 sorgu" mantıksal sorgudur (sağlayıcının tek arama işlemi, çok istekli işlemlerin gerçek istekleri taşıma tavanında sayılır) ve en çok 20 kayıt; sayfalama, sayım yoklaması, zenginleştirme ve genişletme dışı; taşıma ve model denemesi tavanları ayrı gösterilir ve uygulanır, iki run için model denemesi tavanı 60 (§6). *Sol değiştirdi, Claude kabul etti.*
6. **`stated_limitation` (§16.6).** Uygundur; uygunluk özgün kaynağın sınırlamasının bir araştırma boşluğu olduğunu göstermez; özgün kaynak, koşullar ve tarih korunur. *Claude ve Sol.*
7. **VII devralması (§16.7).** Ertelendi; VI yalnız "Investigate" eylemi ve mevcut adaya bağlantı alır. *Claude önerdi, Sol kabul etti.*
8. **Giriş (§16.8).** Bir gap satırının anlık kopyası ya da açıkça `owner_text`; ikisi de kökeni kopyalar, canlı gap satırına ya da gap kimliği eşleştirmesine bağımlılık yoktur. Çizgi ucu girişi ertelendi. *Claude önerdi, Sol kabul etti.*
9. **Tek biçim (§16.9).** Tek formülasyon; alternatif, sıralama ve olumsuz sonuçtan sonra otomatik yeniden formülasyon yok; insan düzenlemesi revizyon yoludur. *Claude ve Sol.*
10. **Aday dosyası (§16.10).** Ertelendi; kalıcı kart zaten koşullu iddiayı, varsayımı ve doğrulama planını gösterir. *Claude önerdi, Sol kabul etti.*
- **X1. Yalnız özetle okuma.** **Sol'un değişikliği:** özetle `closed` yalnız tek bir kaynak sürümü bütün iddiayı (öğelerin birlikte geçerliliği dahil) aynı koşullarda açıkça söylüyorsa; `reasoned_inference` kuramaz; ilgisiz erişilemeyen iş pozitif bulguyu bozmaz. `open` yalnız "verilen metinde eşleşme yok" demektir. Çözülmemiş olası ilgili iş, `unclear` koşul, eksik metin ya da bütçe eksiği `undecided`dır. *Sol değiştirdi, Claude kabul etti.* **Claude'un uyarlaması (Sol turunda denetlenir):** kod tutulan iş sayısını 8'e indirir (taslak önerisi 12'ydi), böylece `rank_cut` bir arama sınırı olarak yazılır ve `undecided` yapmaz; aksi hâlde 12 tutulup 8 değerlendirilince `open` hiç ulaşılamaz olurdu.
- **X2. Taramayı değerlendirmeye katma.** Katıldı; tek çağrı yakınlığı ve matrisi verir. Sol'un sözleşme değişikliği: `unrelated`, `no_match_in_supplied_text`, `uncertain` ve kodun yazdığı `insufficient_access` ayrı; taslağın "her `uncertain` hücre alıntı ister" kuralı kalktı. *Claude önerdi, Sol ekledi.*
- **X3. Sorgu.** **Sol'un değişikliği:** model sınırlı terim blokları yazar, kod `compile_block_queries` ile sağlayıcıya çevirir; `SearchPlan` canlandırılmaz, ham sorgu sözdizimi yok; D92'nin alan dağılımı sayım yoklaması, yedek ikamesi ve eşlik eden kod sorgusu alınmaz, `compile_block_queries`'in sağlayıcı eleme ve uç nokta yönlendirmesi korunur; derlenmiş sorgular ve atlananlar gönderimden önce dondurulur. *Sol değiştirdi, Claude kabul etti.*
- **X4. `owner_text`.** Kabul: kişi aday akışına bilerek girer, AGENTS.md "sessizce genişletme" kuralını bozmaz; sahibin önerisi olarak kaydedilir, boş dayanak olabilir, ayrıştırma ve doğrulama planı literatürce desteklenmiş bulgu olarak sunulmaz. *Claude önerdi, Sol ekledi.*
- **X5. Altı batch.** Altı yeterlidir: K1–K4 yapım, K5 geliştirme davranışı, K6 bağımsız ölçüm; geliştirme ve ölçüm birleşmez; K6 `owner_text` girişini kullanır. Altı batch 15 saatin altında bir süreyi göstermez. *Claude ve Sol.*
- **X6. Kodun gerektirdiği ek güvenceler.** `runs.kind` yeniden kurma, açık stage eşlemesi ve dispatch; tek etkin run kuralının korunması; dondurulmuş arama kaydı ve idempotency; yaşam döngüsü (silme, çöp, yedek); aday kapsamlı kanıt erişimi; model rolü, StepInput, tutamaç ve paket hash'i birlikte (§9). Hepsi K1–K4'ün içindedir, ek batch açmaz. *Sol ekledi, Claude kabul etti.*

## 17. Batch'ler

Her batch ayrı bir commit olur; commit ve push yalnız sahibin istediği zaman, doğrudan `main`'e (PR yok). Batch kabul edilirken tam takım (`PYTHONPATH=backend uv run pytest`, `npm run build`, `npm run lint`, tam Playwright) bir kez koşulur ve sayılar yazılır; geliştirme sırasında yalnız ilgili test dosyaları. Migration ve karar numarası yazım anında son numaradan sonra alınır. Canlı 8765 örneğine ve sahibin kütüphanesine dokunulmaz; her sınama geçici `DEIXIS_DATA_DIR` ve başka portla koşar. Model çağırmayan batch'lerde sahte adaptör kullanılır. Dilim 3 hiçbir batch'te `workflow/report/*` ve `report_*` şemalarına dokunmaz. Dilim 2'nin sıra kuralı (H9'un ölçtüğü ürün checkout'unda dondurma ile sonuç arasında ürün, yöntem, şema ya da doğrulayıcı değişmez) K1–K4'ün ve K5 düzeltmelerinin hepsi için geçerlidir: bu batch'ler H9 penceresinden önce ya da sonra kalır ya da H9 ayrı, sabit bir checkout'ta koşar. Boyut: **S** yarım gün, **M** bir gün, **L** iki–üç gün; tahmin ölçüm değildir.

| Batch | Bağlı olduğu | Boyut | Model |
|---|---|---|---|
| K1 Depolama ve saf hesaplar | — | M | hayır — **yapıldı** (D144, `0060_candidates.sql`; commit: bu satırı ekleyen commit) |
| K2 Sözleşmeler ve yöntem paketi | — | M–L | hayır (sahte) — **yapıldı** (D145, `candidate-check.md`, hash `371fcecb` → `8e1e4a84`; commit: bu satırı ekleyen commit) |
| K3 Akış ve API | K1, K2 | L | hayır (sahte) |
| K4 Arayüz | K3 | M | hayır (senaryolu) |
| K5 Geliştirme davranış koşuları ve kapanış | K1–K4 | S–M | **evet** |
| K6 Bağımsız gerçek-model ölçümü | K5, dondurma incelemesi, sahip başlatması | L | **evet** |

### K1 — Depolama ve saf hesaplar (M)

**Kapsam.** Migration (`runs.kind` genişlemesi + §7 tabloları); `workflow/candidates/{status,hits,terms}.py` saf işlevler: §5 durum türetme, sağlayıcılar arası birleştirme/`work_id` tekilleştirme/8'e kesme, terim bloklarından `vocabulary` sözlüğü; `CandidateStore`: gap anlık kopyası ve `owner_text` ile aday açma, değişmez sürümler ve öğeler, kill-search kaydı ve vuruş/hücre yayımlama (eksik/yinelenen/fazla hücre reddi), sahip kararı; yaşam döngüsü (§9 madde 1 ve 5): `purge_research`, `purge_sources`, `cited_source_versions`, `research_cites_asset`, `asset_impact`, `backup._referenced_files`.
**Dosyalar.** `storage/migrations/00NN_candidates.sql`, `workflow/candidates/*`, `workflow/store.py`, `backup.py`, `tests/test_candidate_status.py`, `tests/test_candidate_store.py`, `tests/test_migrations.py`.
**Testler/kontroller.** §12 K1 satırı; izolasyon; parmak izi uyuşmazlığında yeni aday; olumsuz bütünlük vakaları (başka sürümün öğesine, tutulmamış kaynağa ya da arama/kaynak/öğesi uyuşmayan kanıta bağlı hücre ve kanıt reddedilir); silme (başka araştırmanın ya da adayın da kullandığı paylaşılan kaynak silinmez), çöp, yedek/geri yükleme; tam pytest.
**Çıkış.** Depolama ve saf hesaplar akıştan bağımsız çalışır; §5'in her satırı için sabit vaka geçer; `runs` yeniden kurulumu mevcut satırları korur.
**Göstermez.** Akışın duraklama davranışını, modelin ürettiği veriyle çalışmayı, arayüzü.

### K2 — Sözleşmeler ve yöntem paketi (M–L)

**Kapsam.** Üç şema; `step-input.schema.json`'a aday hedefi; `domain/contracts.py` (kayıt noktaları, `_check_*`, tutamaç eşleme ve onarım mesajı); `RUNTIME_FILES`, `references/candidate-check.md`, `SKILL.md` daraltması, `provenance.json`, model rolü kaydı ve yetenek bildirimi; fixture ve `fakes.py::valid_response`; K5 davranış vakalarının **tanımları** (çalıştırma yok).
**Dosyalar.** `contracts/research/*`, `domain/contracts.py`, `domain/skill.py`, `domain/rules.py` (model rolü kaydı), `methods/deixis-research/**`, `workflow/flow.py` (`_step_input` izin listesi ve `_model_step` parametresi; iş mantığı yok), `tests/test_candidate_contract.py`, `tests/test_skill.py`, `tests/fixtures/research/*`, `tests/fakes.py`, `tests/model_behavior/candidate_cases.json`.
**Testler/kontroller.** §12 K2 satırı; paket bütünlüğü; tam pytest.
**Çıkış.** Yeni üç görev tutamaçlarla sahte adaptörden uçtan uca doğrulanır; `skill_package_hash` hareketi kayıtlı; sıra kuralı kontrol edildi.
**Göstermez.** Gerçek modelin sözleşmeye uyduğunu ya da çıktının doğruluğunu.

### K3 — Akış ve API (L)

**Kapsam.** `flow.py` dispatch ve `create_run` stage eşlemesi; `_claim_decomposition` ve `_kill_search` (terimler → sağlayıcı aramaları → birleştirme/kesme → sıralı değerlendirme → yayımlama), dondurulmuş kayıt, bütçe/tavanlar (§6), `resume` korumaları; aday kapsamlı kanıt erişimi (§9 madde 4); modele verilen pasaj ve ileti boyutu sınırları (`max_message_chars`) ve uygun bağlayıcıların gerçek istek sayıları (§6); her gönderimden önce kalıcı bütçe denetimi; API: aday açma (iki kökenle), okuma, düzenleme, ayrıştırma, kill-search önizleme ve başlatma (`Idempotency-Key`, parmak izi), sahip kararı, aday listesi (VI satırı için).
**Dosyalar.** `workflow/flow.py`, `workflow/store.py`, `api/app.py`, `workflow/candidates/run.py`, `tests/test_candidate_flow.py`, `tests/test_candidate_api.py`, `tests/acceptance/fixture_server.py`.
**Testler/kontroller.** §12 Akış satırı; izolasyon uçtan uca; tam pytest.
**Çıkış.** Sahte adaptörle iki köken de ayrıştırılır, kill-search koşar, durum türer; yarıda kesme/devam/iptal idempotent; araştırma korpusu değişmez; bütçe aşımı sessizce `open` üretmez.
**Göstermez.** Gerçek sağlayıcı ya da model davranışını; süreyi.

### K4 — Arayüz (M)

**Kapsam.** §10: aday kartı, sürümler, düzenleme, kill-search düğmesi ve zaman çizelgesi, matris, kanıt görünümü, durum ve sahip kararı, VI satırında "Investigate", "Add candidate"; `api.ts`, `i18n.ts`.
**Dosyalar.** `apps/web/src/candidate/*`, `apps/web/src/report/*` (yalnız eylem ve bağlantı; rapor verisi değişmez), `apps/web/src/api.ts`, `apps/web/src/i18n.ts`, `apps/web/e2e/candidate.spec.ts`.
**Testler/kontroller.** §12 Web satırı; `npm run build`, `npm run lint`, tam Playwright; 390 px ve masaüstü, iki tema, gözle doğrulama.
**Çıkış.** Senaryolu modelle uçtan uca akış ekranda çalışır.
**Göstermez.** Gerçek model kalitesini; gerçek rapor VI çıktısıyla girişi.

### K5 — Geliştirme davranış koşuları ve kapanış (S–M) — **model gerekir**

**Kapsam.** Yedi vaka `gpt-5.6-luna` ile bir kez: (1) aynı sonuç başka terminolojiyle, (2) sıfır sonuç / tüm sorgular başarısız / özetsiz iş (üç ayrı durum), (3) çok öğeli iddia, tek öğe eşleşiyor, (4) çekici ama geçersiz analoji, (5) farklı koşulda ters sonuç, (6) özet öğeleri ayrı söylüyor ama bütün iddiayı söylemiyor, (7) `owner_text` boş dayanak (uydurma yok); bir geliştirme iddiasıyla uçtan uca deneme (korpus yanar); bulgulara göre düzeltmeler bu batch'te biter; `decisions.md` kapanış kaydı (Evidence, Limits).
**Dosyalar.** `scripts/model_behavior/run_candidate_cases.py`, `tests/model_behavior/candidate_cases.json`, `docs/decisions.md`.
**Testler/kontroller.** Tam takım; `git diff --check`.
**Çıkış.** Her vaka için beklenen/gözlenen kayıt; bulgular düzeltildi ya da açık yazıldı.
**Göstermez.** Bağımsız ölçüm değerini, oran ya da genellemeyi.

### K6 — Bağımsız gerçek-model ölçümü (L) — **model gerekir, ayrı dondurma kuralı, sahip başlatır**

**Kapsam.** §13: S1–S5, taze iddia kümesi, tek koşu, müdahalesiz; dondurma commit'i ve gpt-6.1-sol dondurma incelemesi ölçümden önce; sonuç belgesi ve `decisions.md` kaydı (başarı ya da başarısızlık ayrı karar). Dilim 3'ün kapanışı için zorunlu değildir: sahip başlatmazsa dilim "uygulandı, gerçek-model ölçümü yok" diye kapanır.
**Dosyalar.** `docs/product/p6-slice3-expectations.md`, `docs/product/p6-slice3-results.md`, `docs/decisions.md`.
**Testler/kontroller.** Dondurma dosyası hash'i; ürün commit'i ve `skill_package_hash` eşitliği; sıfır `started` oturum doğrulaması.
**Çıkış.** S1–S5 değer ya da "ölçülemedi"; §13'teki dilde sonuç.
**Göstermez.** Popülasyon oranı, genelleme, karşılaştırmalı hız/maliyet, insan denetimi, gerçek rapor VI girişi.
