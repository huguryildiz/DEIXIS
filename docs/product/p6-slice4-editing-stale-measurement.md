<!-- Tasarım kararları ve denetimi (gpt-6.1-sol · high, salt okunur): karar turu (§13, Q1–Q9 + dört ek) Claude ile ortak; tasarım denetimi: tur 1 hazır değil (4 yüksek, 3 orta; hepsi işlendi), tur 2 hazır değil (1 yüksek, 1 orta; işlendi), tur 3 hazır (0 yüksek, 1 orta; işlendi) Ham cevaplar /tmp/s4d-a1.md (karar turu), s4d-a2.md, s4d-a3.md, s4d-a4.md (denetim). -->
# P6 dilim 4 — düzenlenmiş raporun denetimi ve kaynak çıkarma: tasarım notu

**Tarih:** 17 Eylül 2026 (taslak), 29 Eylül 2026 (küçük sürüm, D112), 2 Ekim 2026 (yeniden yazım, `58676f1` üzerinde). **Durum:** uygulamaya kabul için hazırlandı; kararlar §13'te, batch'ler §14'te, kalıcı kayıt `docs/decisions.md` D147. Bu not bir tasarımdır: kod, migration, model çağrısı ve ölçüm yoktur; kabul, uygulamanın doğrulandığı anlamına gelmez. 17 Eylül taslağı (§1–§13) ve 29 Eylül'ün §0 güncellemesi git geçmişindedir; bu not onların yerine geçer. D112'nin istemi (`p6-slice4-prompt.md`) tarihi bir kayıttır, bu notun eski §0'ına atıf yapar ve değiştirilmedi. Sahibin 2 Ekim isteği gereği dilim **dar** tutuldu: **dört batch**, hiçbirinde model çağrısı yok; kapanış ölçümü P9'a borç olarak taşındı (§10).

## Kısaca

D112 ve D113 ile bir bitmiş raporun iddiası elle düzeltilebiliyor, geçmişi tutuluyor, kanıt değişince bölüm işaretleniyor ve ekranda "Düzenle", "Geçmiş", "Geri yükle", "Böyle kalsın" var. İki şey eksik kaldı ve bu dilim yalnız onları kurar. Birincisi, düzenlenmiş metin hiçbir denetimden geçmiyor: dışa aktarılan dosya ve ekran "düzenlenen metin yeniden denetlenmedi" diyor, çünkü montaj kuralları `report_claims.text`'i, yani **modelin** metnini okuyor. Dilim, düzenlenmiş raporu kodla, modelsiz, yeniden denetleyen salt-okunur bir **"Düzenlemeleri denetle"** eylemi ekler; sonucu kayda yazılır, ekranda ve dışa aktarımda "bu denetim şu düzenleme sürümleri için yapıldı" diye görünür, bir şey değişirse "eski" olur. İkincisi, yanlış bir atıf bugün düzeltilemiyor: metin düzenlenir ama kanıt bağı aynen kalır. Dilim iddiadan **atıf kaldırma**yı (geri alınabilir, geçmişe bağlı) ekler. Rapor sürüm numarası, "Yayımla" eylemi, bölüm yeniden yazımı, kararlı kimlik katmanı ve tüm gerçek-model ölçümü bu dilimde **yoktur** (§12).

Bu dilim hiçbir şeyi "doğrulanmış" yapmaz: denetim biçim ve yasak sözcük gibi kod kurallarını yeniden çalıştırır, bir cümlenin kanıtı gerçekten desteklediğini göstermez (AGENTS.md "Never overstate what was established"). Bir düzenleme yeni bir atıf eklemez; atıf kaldırma kanıtı azaltır, artırmaz.

## 0. Taslağın bugünkü koda göre yanlış kalan yerleri

| # | Taslak diyordu | `58676f1`'de durum | Bu notta karşılığı |
|---|---|---|---|
| F1 | Dilim 1 kodda yok, `staleBand` yok, rapor ekranı yok | Hepsi var (D112, D113, D116, D118, D120): rapor koşusu, 14 montaj kuralı, `report_review`, ekran, Markdown dışa aktarım, düzenleme formu, geçmiş, geri yükleme, "Böyle kalsın" | Bu dilim yalnız iki eksiği kurar (§Kısaca) |
| F2 | "Yayımla" düzenleme sonrası yeni `report_version` verir (Q2a), montaj denetimi insan metniyle yeniden koşar | Hiçbiri yok. Üstelik montaj kuralları `report_claims.text`'i okur, güncel düzenleme sürümünü değil (`assembly._claims`, `_section_texts`); `reports.report_version` `finalize` ile bir kez atanır ve `(research_id, report_version)` benzersizdir | "Yayımla" ve yeni numara ertelendi (§12). Asıl boşluk, düzenlenmiş metnin denetlenmemesidir: ayrı bir okuma modu ve eylem (§2, §5) |
| F3 | Bölüm yeniden yazma önerisi (S3/S4), `report_section_revisions` | Bitmiş bir rapor için bölüm yeniden yazma işlemi yok; `save_claims` insan düzenlemesi olan bölümü değiştirmeyi reddeder. Gerçek-model bir rapor, sabit P16 serisinde hiç tamamlanmadı (D124, D126, D128) | Ertelendi (§12) |
| F4 | Kararlı kimlik (`report_stable_claims`, `report_claim_matches`, `report_stable_gaps`); dilim 3'ün `source_gap_id`'si ona bağlanır | Yeniden yazma yok, eşleştirilecek bir şey yok; dilim 3 aday kökenini düz metin ve parmak iziyle kopyalar, canlı gap satırına bağlanmaz (D143) | Ertelendi. **Dilim 4 artık dilim 3'ün bıraktığı kimlik eşleştirmesini üstlenmez**; bu D143'ün §15'inde "dilim 4" diye yazılı, kayıt düzeltilir (§12, D147) |
| F5 | Bayatlama yazma anında bayrakla (§3, §4) | Okuma anında hesaplanıyor (D112, soru 6'daki sapma); tablo `report_stale_acknowledgements` | Değişmez; bu dilim yalnız atıf kaldırmanın bayatlamaya etkisini tanımlar (§4) |
| F6 | `report_claim_revisions` `kind IN ('model_write','human_edit','human_restore')`, `keep_citations` | `0056`: `kind IN ('human_edit','human_restore')`, `restored_from`, `warnings_json`; atıf bilgisi yok; metin değişmeden düzenleme reddedilir | Yeni migration `0056`'ya dokunmaz; yeni sütun/tablo ekler (§6) |
| F7 | Taslak "dilim 1 kodda yok" sonucuna göre yazılmıştı; §0 (29 Eylül) ve D112 "18 Eylül'de ilk tam rapor `valid` bitti (`4582b64`)" der | `4582b64` gerçek bir commit (kopya kütüphanede `gpt-5.6-luna` ile 11/11 bölüm, 24 model çağrısı); ama dondurulmuş P16 ölçüm serisi hiçbir tam rapor üretemedi (D124, D126, D128) ve bu ilk rapor `report_review`, D127 tutamaçları ve sekiz montaj kuralından **önceydi** | İkisi çelişmez ama ayrı iddiadır: bu not "gerçek modelle tamamlanmış bir rapor kaydı var" demez; bugünkü kodla tamamlanmış gerçek-model rapor yok. Ölçüm bu yüzden P9'a taşındı (§10) |
| F8 | `edited_after_version` düzenleme işaretidir | Taslak rapor (`report_version` boş) düzenlenince `edited_after_version = null` olur ve ekran/dışa aktarım cümlesi kaybolur (`views.report_view`, `export.py`) | Bağımsız bir `has_human_edits` alanı eklenir (§2) |
| F9 | Atıf kaldırma, kaynağın korunması | `research_cites_asset` ve `asset_impact` rapor atıflarını saymıyor (yalnız cevap, hücre, çizgi bağı, aday kanıtı); `cited_source_versions` sayıyor | Atıf kaldırmanın kaynak koruması bu açığı kapatmadan güvenli olmaz: E2'nin içinde kapatılır (§7) |

## 1. Kodda bugün olan (`58676f1`'de doğrulandı)

| Parça | Durum | Bu dilimde kullanımı |
|---|---|---|
| `report_claim_revisions` (`0056`), `report_claims.current_revision_id`/`version`, `ReportStore.edit_claim` | Eklemeli; `expected_version` (409), `Idempotency-Key` (araştırma kapsamlı, başka iddiada çakışma), yalnız `human_edit`/`human_restore`; rapor koşusu bitmeden 409; metin/kısıtlı doğrulamalar (`math_not_well_formed`, `count_not_rechecked`); boş ya da aynı metin 422 | Aynen kalır; yalnız "yalnız atıf değişen" düzenleme ve etkin atıf kümesi eklenir (§2, §6) |
| `ReportStore.evidence_changes`, `acknowledge_changes`, `report_stale_acknowledgements` | Okuma anında bayatlama; rapor düzeyi sayılar anlık görüntüyle; bölüm düzeyi atıf ve `body_ref`/`gap_ref` üzerinden; `not_checked: ["passages"]` | Sayılar değişmez; bölüm düzeyi yalnız etkin atıflardan türer (§4) |
| `assembly.run_assembly_checks` (14 kural, D116) | `report_claims.text` ve `report_citation_links` okur; `ReportStore.finalize` sonucu `valid`/`draft` | Temel (taban) davranışı değişmez; yeni "güncel" kipi eklenir (§5) |
| `domain/contracts.py` VIII sayı yeniden anma denetimi (~1444) | Bölüm yazımında VIII iddialarının kendi sayısını yeniden söylemesini reddeder; montaj kuralı değildir | Güncel kipte düzenlenmiş VIII iddialarına da uygulanır (§5) |
| `report_view` | `edited_after_version`, `evidence_changes`, iddia başına `revisions`, `model_text`, `warnings`, `edited` | Eklenir: `has_human_edits`, `edit_check`, iddia başına etkin atıflar ve `evidence_basis` (§2, §8) |
| `report/export.py` | "Edited by hand after version n; edited text was not checked again." | Üç durumlu cümle (§2) |
| `ReportView.tsx`, `api.ts` | Düzenle, geçmiş, geri yükle, "Böyle kalsın" | Atıf kaldırma, "Düzenlemeleri denetle" (E3) |
| `Store.purge_research`, `cited_source_versions`, `research_cites_asset`, `asset_impact`, backup | Rapor tabloları silme sırasında; `research_cites_asset`/`asset_impact` rapor atıfını saymaz (F9) | Yeni tablolar eklenir, açık kapatılır (§7) |
| `reports.report_version` | `finalize` ile bir kez; temel model sürümünü tanımlar | Değişmez; düzenlemeler ayrı görünür (§12 "Yayımla") |

## 2. Akış

**Düzenlemeleri denetle** (kod; model yok, yayım yok, durum ve numara değişmez). Rapor koşusu bitmiş (`valid` ya da `draft`) bir raporda sahip "Düzenlemeleri denetle" der. Kod:
1. Güncel kipte denetimi koşar (§5): düzenlenmiş iddiaların güncel metni ve etkin atıf kümesi, düzenlenmemiş iddialarda ve bölüm gövdelerinde temel veri. Çalıştırılan ve atlanan kurallar açıkça listelenir.
2. Sonucu `report_edit_checks`'e **eklemeli** yazar: maddeler (`rule`, `section_id`, `detail`, `severity` = `error` | `warning`), çalıştırılan ve atlanan kurallar ve **girdi parmak izi**. Parmak izi, denetleyici sürümünü ve denetimin okuduğu **her** girdiyi içeren kanonik bir JSON'un sha256'sıdır: denetleyici sürümü; her iddianın kimliği, güncel revizyon kimliği ve güncel metninin özeti; etkin atıf kimlikleri ve çapa metinleri; her bölümün saklı `draft_json`, `validation` ve `word_count` özetleri; plan; anlık görüntü içeriğinin özeti; `report_gaps` satırları; çapaların bulunduğu pasajların kimliği ve metin özeti (`text_source` dahil); kaynakça alanları (`references` için okunan kaynak sürümü alanları). Bu liste bir **bağımlılık manifestosudur** ve E1'de şu girdileri açıkça kapsar: her bölümün denetimin seçtiği adım girdisi (`_section_payload`'ın son girdi seçimi: adım ve girdi kimliği ile yük özeti; gap, denklem ve kalıp denetimleri bunu okur); iddia yapısı (`claim_key`, paragraf, `support_type`, `table_ref`, `equation_ref`, `axis_id`, `count_json`, `equation_origin_json`, `body_ref`/`gap_ref`); pasaj sahipliği ve türü; rapor dili ve kalıp girdileri (`report_phrase_repairs` son satırları); eksik girdi durumları da açık bir "yok" değeriyle manifestoya girer. Hiçbir bileşenin değişmezliği varsayılmaz (`report_snapshot` için tetikleyici yok): her biri içerik özetiyle girer. Değerlendirme ve kayıt **tek işlemde, tek tutarlı okuma durumu üzerinde** yapılır; yalnız seçilen adım girdisi değiştiğinde parmak izinin değiştiği bir regresyon testiyle kanıtlanır. Aynı parmak iziyle ikinci istek yeni satır yazmaz, var olan satırı döner; denetleyici sürümü parmak izinin içinde olduğundan sürüm yükseltmesi yeni bir kayıt yazar.
3. Raporun durumunu, sürüm numarasını, bölüm durumlarını, `validation`'ını ya da `report_review` kaydını **değiştirmez**. Temel modelin D118 incelemesi görünümde modelin yazdığı sürüme bağlı kalır ("model temel sürümü incelendi; düzenlemeler incelenmedi").
4. Görünüm ve dışa aktarım son denetimi okur ve parmak iziyle bugünkü durumu karşılaştırır: **güncel** (hiçbir iddia revizyonu, atıf kümesi, anlık görüntü ya da denetleyici sürümü sonradan değişmedi) ya da **eski** (değişti; kayıt tarihsel olarak kalır).

Cümle, görünümde ve dışa aktarımda: denetim yoksa "Elle düzenlendi; düzenlenen metin yeniden denetlenmedi" (bugünkü), güncel denetim varsa "Elle düzenlendi; düzenlenen metin kod kurallarıyla denetlendi ({tarih}): {n} hata, {m} uyarı; anlam desteği denetlenmedi", eski denetim varsa "... denetim sonradan değişen düzenlemeleri kapsamıyor". `has_human_edits` düzenleme varsa her durumda doğrudur (taslak raporda `edited_after_version = null` olsa bile; F8).

**Atıf kaldırma** (kod işi). İddia düzenleme isteği bir `link_ids` alanı taşıyabilir: iddianın **özgün** atıflarından tutulacak küme. Alan yoksa güncel küme taşınır. Her düzenleme ya da geri yükleme, iddianın etkin atıf kümesini eksiksiz kaydeden yeni bir revizyondur; yalnız atıfı değişen düzenleme (metin aynı) geçerlidir, ikisi de aynıysa 422. Geri yükleme (`restore_from`) o revizyonun **metnini ve atıf kümesini** birlikte geri getirir; `'model'` özgün metni ve bütün özgün atıfları. Atıf eklemek yoktur; yalnız iddianın özgün atıflarından seçilir. Bir iddianın etkin atıfı sıfır olursa iddia "Doğrudan atıf yok" diye gösterilir: `body_ref`, `gap_ref` ve `count` kayıtları hâlâ bir dayanak verebilir, bu yüzden bu bir ret değil, görünür bir durumdur.

## 3. Senaryolar

**S1. Düzenlenmiş iddia yasak sözcük taşıyor.** Sahip bir iddiayı "…bu bir boşluk" diye düzenler → kayıt serbest (D112: uyarı/ret yok) → "Düzenlemeleri denetle" yasak sözcüğü hata olarak listeler, rapor durumu `valid` kalır, sahip metni düzeltebilir.
**S2. Sayı bozulması.** `count` taşıyan bir iddiada sahip 7'yi 9 yapar → denetim `count_number_mismatch` yazar (üye sayıları donuk, metindeki tamsayı uyuşmuyor); sahip sayıyı sözcükle yazarsa ("dokuz") ya da metinden tamsayıyı kaldırırsa karşılaştırılacak tamsayı kalmaz ve denetim bu iddiayı `count_text_not_checked` diye listeler, "temiz" saymaz.
**S3. Yanlış atıf.** Sahip bir iddianın üç atfından birinin aslında başka bir kaynağa ait olduğunu görür → metni değiştirmeden `link_ids`'ten onu çıkarır → iddia iki atıfla görünür, geçmişte üç atıflı sürüm durur, geri yükleme üçünü de geri getirir. Raporun anlık görüntü değişikliği sayıları değişmez.
**S4. Hepsi kaldırıldı.** Sahip iddianın bütün atıflarını kaldırır → iddia "Doğrudan atıf yok" gösterir, `support_type` temel veri olarak kalır ama etiketlenir ("modelin yazdığı sürümün türü"); "atıflar bulundu" başarısı üretilmez; `body_ref` ile buna bağlı Özet/I/IX iddiaları, düzenlenmiş bir temele dayandıkları için işaretlenir.
**S5. Denetim eskir.** Denetimden sonra sahip bir iddiayı yeniden düzenler → görünüm denetimi "eski" gösterir; yeni denetim yeni satırdır, eskisi silinmez.
**S6. İki sekme.** Biri atıf kaldırır, öteki eski sürümle düzenler → `expected_version` uyuşmazlığı 409, ikincinin taslağı formda kalır (D113 deseni).
**S7. Kaynak sonradan araştırmadan çıkar.** Atfı kaldırılmış bir iddia o kaynağa artık atıf yapmıyorsa, kaynak çıkışı o bölümde işaret açmaz; ama rapor düzeyi sayı (anlık görüntüyle) hâlâ "bir kaynak çıktı" der.

## 4. Kurallar

- **Denetim bir hüküm değil, bir kod kontrolüdür.** Sonuç hiçbir bölümün ya da raporun durumunu yükseltmez, sürüm numarası vermez, "doğrulandı" ya da "yayımlandı" demez; anlam desteği ve atıf-iddia uyumu denetlenmez.
- **İnsan metni için kalıp (phrasebank) denetimi çalışmaz** (D112 ile aynı): zorunlu kalıp çerçeveleri ve istisna eşleştirmesi düzenlenmiş iddialarda atlanır; kalıp-dışı yasaklı ifadelerin tanılayıcıları (kendi çalışma ve çoğul kaynak ifadeleri) çalışır (§5).
- **Temel ile güncel ayrı kalır.** `run_assembly_checks`'in mevcut çağrıları (rapor koşusu sonu, `finalize`) aynen modelin metnini denetler; güncel kip yalnız yeni eylemde ve açıkça seçilir. Düzenlemeler `valid` bir raporu `draft` yapmaz.
- **Etkin atıf tek tanımdan gelir.** Denetim, bayatlama (bölüm düzeyi), numaralandırma, görünüm ve dışa aktarım aynı "etkin atıf" tanımını okur. Özgün bağlar ve çapaları geçmişte kalır, hiçbir bağ silinmez.
- **Atıf kaldırma bayatlamayı kaynağa göre değiştirir, anlık görüntü sayısını değil.** Bölüm işareti yalnız etkin atıflardan ve `body_ref`/`gap_ref`'ten türer; rapor düzeyi sayılar (değişen hücre, çıkan kaynak, eklenen kaynak, revize sütun) anlık görüntüden hesaplanmaya devam eder ve kaldırılan atıflardan bağımsızdır. Kaldırılmış bir atfın hücresi sonradan değişirse o iddiada işaret açılmaz; atıf geri yüklenirse, işaret o zamanki duruma göre yeniden türer. Kabul anahtarları değişmez.
- **Düzenlenmiş temel iddiaya bağlı iddialar görünür.** `body_ref`/`gap_ref` ile bir düzenlenmiş iddiaya dayanan başka bölüm iddiası, görünümde "dayandığı iddia elle düzenlendi" notunu taşır; metni değişmez.
- **Atlanan kural sessiz geçmez.** Bir kural girdisi eksik olduğu için (ör. atıfsız iddia için okuma derinliği) çalışamıyorsa denetim bunu `skipped` yazar ve o iddiayı "temiz" saymaz.
- **Kaldırma ve denetim geri alınabilir ya da tarihseldir, silinmez.**

## 5. Denetim kapsamı

Her satır kod işlevi adıdır (`assembly.py`); "güncel kip" düzenlenmiş iddiada güncel metni ve etkin atıfı kullanır.

| Kural | Düzenle değişebilir mi | Güncel kipte |
|---|---|---|
| `_check_duplicate_claim_keys`, `_check_body_refs`, `_check_conflict_links` (anahtar/ref yapısı) | Hayır: düzenleme anahtar ya da ref değiştirmez | Temel okuma; `conflict_links` atıfa dayanıyorsa etkin atıf |
| `_check_glossary_order` | Evet (metin) | Güncel metin |
| `_check_banned_words` | Evet (iddia metni) | Güncel metin; boşluk/başlık/dayanak metinleri modelin |
| `_check_count_fields` | Evet (metindeki tamsayılar) | Güncel metin; üyelik donuk. Metinde hiç tamsayı yoksa mevcut kural karşılaştırma yapmaz (`if numbers`); güncel kip bunu başarı saymaz, o iddia için `count_text_not_checked` (atlandı: `no_integer_in_text`) yazar. Sözcükle yazılan sayı da bu yoldan söylenir |
| `_check_corpus_counts` | Hayır (II/VIII sayıları yapısal, kod yazar) | Temel okuma |
| `_check_derived_strength`, `_check_bibliography`, `_check_gap_bases`, `_check_anchors` | Atıf kaldırmayla evet | Etkin atıflar; okuma derinliği eksikse `skipped`, sessiz muaf değil |
| `_check_word_budgets` | Evet (kelime sayısı) | Güncel iddia metinleri ve `insufficient_evidence` sebeplerinden yeniden sayılır (`sections._word_count` işleviyle); depolanan `word_count` değiştirilmez |
| `_check_equations` | Evet (metin ve atıf) | Güncel metin, etkin atıflar; OCR/Marker kökenli uyarı kuralı korunur |
| `_check_phrase_frames` | Düzenlenmiş iddiada atlanır | Zorunlu çerçeve ve istisna eşleştirmesi atlanır; `own_work_phrase_in_claim` ve `plural_sources_for_one_source` tanılayıcıları çalışır |
| `domain/contracts.py` VIII sayı yeniden anma | Evet (VIII iddia metni) | Düzenlenmiş VIII iddialarına uygulanır |

Düzenleme zamanındaki uyarılar (`math_not_well_formed`, `count_not_rechecked`) değişmez; eşleşmeyen `$` ayraçları kendi başına bulunmaz (bilinen sınır). Bu denetim anlam desteği, bir sayının sözcükle yazılması ya da düzenlenmiş metnin bilimsel doğruluğu hakkında bir şey söylemez.

## 6. Veri modeli (niyet; geçerli SQL migration'dır)

Migration numarası yazım anında `ls backend/deixis/storage/migrations/` ile son numaradan sonra alınır; `0056`'ya dokunulmaz.

- `report_claim_revisions`'a iki sütun (`ALTER ... ADD COLUMN`; `0056`'daki güncelleme tetikleyicisi şema değişimini engellemez, mevcut satırlar yeniden yazılmaz): `link_count INTEGER` (NULL = eski revizyon: "özgün atıfların tümü"; sayı = bu revizyonun etkin kümesinin boyutu, boş küme için 0) ve `request_hash TEXT` (NULL = eski revizyon; bkz. aşağıdaki idempotency maddesi).
- `report_claim_revision_links`: `revision_id` → `report_claim_revisions`, `link_id` → `report_citation_links`, `PRIMARY KEY (revision_id, link_id)`; eklemeli (güncelleme tetikleyiciyle reddedilir, silme yalnız araştırma silme yetkisiyle). **Mühürleme:** revizyon satırı `link_count = N` ile eklenir, aynı işlemde N bağ satırı eklenir; `BEFORE INSERT` tetikleyicisi, revizyonun `link_count`'u NULL ise ya da o revizyon için zaten `link_count` kadar satır varsa ekleme yapılmasını reddeder (geç ekleme, boş küme ve eski revizyon dahil), ayrıca bağın revizyonun iddiasına ait olduğunu denetler; saklama işlevi işlem içinde satır sayısının `link_count`'a eşit olduğunu doğrular. Böylece yayımlanmış bir revizyonun atıf kümesi sonradan değişemez; geç ekleme açıkça testlenir. Her yeni revizyon (düzenleme ya da geri yükleme) tam kümeyi yazar; küme önceki revizyondan taşınır, geri yükleme hedef revizyonun kümesini kopyalar (hedef `link_count IS NULL` ise bütün özgün atıflar).
- **Etkin atıf tanımı** tek yerde (bir SQL görünümü ya da tek bir saklama işlevi; ikisinden hangisi E2'de seçilir): iddianın `current_revision_id`'si yoksa ya da o revizyonun `link_count`'u NULL ise iddianın bütün `report_citation_links` satırları, aksi hâlde `report_claim_revision_links` satırları. Ham `report_citation_links` okuması bu tanım ve tarihsel yollar (geçmiş, yaşam döngüsü) dışında kalmaz; bir test bunu kaynak taramasıyla denetler.
- `report_edit_checks` (`rec_`): `report_id` → `reports`, `checker_version`, `input_fingerprint`, `result_json`, `created_at`; `UNIQUE (report_id, input_fingerprint)`; eklemeli, silme yalnız araştırma silme yetkisiyle.
- Düzenleme isteği: `link_ids` (isteğe bağlı; yoksa güncel küme taşınır), metin ve/veya `restore_from`; yalnız-atıf düzenlemesi geçerlidir; `restore_from` ile `text` ya da `link_ids` birlikte 422 (geri yükleme hedefin metnini ve kümesini taşır). **Idempotency uyumu (D112'nin bir davranışı değişir):** D112'de aynı iddiada aynı anahtar, içeriğe bakmadan önceki revizyonu döner ve `test_edit_history_restore_warnings_and_replay` bunu ister; yeni istekler için bu, içerik bağlı olur ve test buna göre güncellenir. Yeni her revizyon `request_hash` saklar: sha256(kanonik JSON: soyulmuş metin ya da `restore_from`, sıralı tekil `link_ids` ya da "belirtilmedi", not). Tekrar: aynı iddia ve anahtar için `request_hash` varsa eşit olmalı (eşitse yazmadan aynı revizyonu döner, `expected_version` bakılmadan, D112'deki sıra), farklıysa `RevisionConflict`; `request_hash` NULL olan eski revizyonlar D112 davranışını korur (yazmadan döner). Belirtilmeyen `link_ids` yeniden gönderimde belirtilmemiş sayılır; ara düzenleme sonrası tekrar özgün revizyonu döner. `edit_claim` revizyonu, atıf kümesini ve olayı tek işlemde yazar.
- `report_view`: mevcut `claim.evidence` korunur ama yalnız **etkin** atıfları taşır ve her biri `link_id` alır (numara ya da kaynak anahtarı kimlik değildir); iddia başına `original_evidence_count`, `removed_links` (kümede olmayan özgün bağlar: kimlik, çapa, kaynak; geri yükleme için), `evidence_basis` (`direct` | `none`), `support_type_note` ("modelin yazdığı sürümün türü"), düzenlenmiş temele dayanma notu; her revizyonda `link_ids` ve `link_count` (NULL = özgün tümü), böylece geçmiş "3 atıf → 2 atıf" gösterebilir ve "Geri yükle" yalnız metin **ya da** küme farklıysa sunulur; rapor başına `has_human_edits`, `edit_check` (son kayıt ve `current`). Dışa aktarım: atıfı olmayan iddia numara işareti taşımaz ve künye paragrafı "n iddiada doğrudan atıf yok" der; atlanan kurallar ve tarihsel denetim bulguları denetim cümlesinin altında listelenir; D118 incelemesi "modelin temel sürümü" ibaresini korur.

Durum için tablo yoktur: "güncel/eski" okuma anında parmak iziyle hesaplanır.

## 7. Yaşam döngüsü, bütünlük ve güvenlik

K olmadan, E1–E2'nin içinde:

1. **Silme.** `purge_research`, `report_edit_checks`'i (E1) ve `report_claim_revision_links`'i (E2) atıfların ve revizyonların **önünde** siler; araştırma çöpe atma ve geri alma her şeyi korur. `purge_sources` ve kaynak koruması tarihsel bağları da sayar: kaldırılmış bir atıf geri yüklenebilir olduğundan, onun geçmişteki pasajı korunur.
2. **Kaynak/pasaj koruması (F9).** `research_cites_asset` ve `asset_impact` `report_citation_links`'i (etkin ve kaldırılmış) sayar; `asset_impact` yeni bir `report_citations` anahtarı alır. Bu açık dilimden önce vardı; kaldırma onu daha tehlikeli yaptığından burada kapatılır.
3. **Yedek ve geri yükleme.** Yeni tablolar tam geçmişi korur (revizyon kümeleri, denetim kayıtları, yabancı anahtarlar); testlenir.
4. **Eşzamanlılık ve tekrar.** `expected_version`, içerik bağlı `Idempotency-Key`, revizyon/küme/olay tek işlemde (kısa, senkron; `await` yok).
5. **Hiçbir model çağrısı yok.** Hiçbir yeni görev, sözleşme ya da yöntem dosyası yok; `skill_package_hash` değişmez.

## 8. Arayüz (yalnız davranış)

`.impeccable.md` ve AGENTS.md hiyerarşisi geçerlidir; mevcut bileşenler yeniden kullanılır.

- **Atıf kaldırma.** Kanıt görünümünde her atfın yanında "Kaldır" (düzenleme formunda; kaydetmeden önce geri alınabilir); kaydedilen kümenin geçmişi "Geçmiş" listesinde ("3 atıf → 2 atıf") görünür; "Geri yükle" metni ve atıf kümesini birlikte getirir. Atıfı kalmamış iddia "Doğrudan atıf yok" yazar; `support_type` "modelin yazdığı sürümün türü" notuyla görünür.
- **Düzenlemeleri denetle.** Rapor başlığında, düzenleme varsa görünür; sonuç listesi hata/uyarı, atlanan kurallar ve "anlam desteği denetlenmedi" cümlesiyle; "eski" etiketi metinle (yalnız renkle değil). Kayıt yok ya da eski ise başlık cümlesi §2'deki ilgili sürüm.
- **Düzenlenmiş temele dayanan iddia** için kısa not.
- Dışa aktarım aynı cümleleri taşır (D120 ilkesi: ekran ve dosya aynı okuma modelinden).
- İngilizce ve Türkçe metin, 390 px ve masaüstü, açık ve koyu tema.

## 9. Testler

**Depolama ve saf hesap (E1–E2):** migration (boş ve dolu kopya, eski revizyonlar `link_count IS NULL` ve bütün atıflar etkin); mühürleme: geç bağ ekleme, boş küme ve eski revizyona ekleme reddedilir; D112 idempotency testi (eski anahtar yazmadan döner) ve yeni içerik bağlı tekrar (aynı içerik aynı revizyon, farklı içerik 409, ara düzenleme sonrası tekrar); `link_ids` sıra/yineleme kanonikleşmesi; `restore_from` ile `text`/`link_ids` 422; denetim parmak izi: sürüm yükseltmesi yeni kayıt, her girdi sınıfında bir değişiklik yeni kayıt; hiç tamsayı olmayan `count` iddiası `count_text_not_checked`; güncel kip her denetlenen kural için (§5 tablosu) sabit vakalarla; temel kipin eski sonuçları değişmez (mevcut `test_report_assembly` aynen geçer); atlanan kural `skipped` yazılır, temiz sayılmaz; parmak iziyle güncel/eski; aynı parmak izi ikinci kayıt yazmaz; denetim rapor durumunu, numarasını, bölüm durumunu, `report_review` kaydını değiştirmez; etkin atıf tanımı tek yerde (kaynak tarama testi); yalnız-atıf düzenleme; atıf geri yükleme; hedef revizyon `link_count IS NULL` ise bütün özgün atıf; başka iddianın bağı reddedilir; içerik bağlı idempotency ve D112 testinin güncellenmesi (eski anahtarlar korunur); bayatlama etkin atıftan türer, anlık görüntü sayıları kaldırmadan etkilenmez; kabul anahtarları kaldırma/geri yükleme sonrası tutarlı; yeni tablolar güncelleme/silme tetikleyicisi, purge, kaynak koruması, `research_cites_asset`/`asset_impact`, yedek-geri yükleme gidiş-dönüşü.
**Akış/API:** iki sekme 409, denetim rapor koşusu bitmeden 409, başka araştırmanın raporu 404, `link_ids` bilinmeyen/başka iddia 422.
**Web (E3, Playwright, senaryolu):** düzenle → denetle → hata listesi → düzelt → yeniden denetle ("eski" → "güncel"); atıf kaldır → geçmiş → geri yükle; hiç atıf kalmayan iddia; 390 px ve masaüstü, açık ve koyu tema.
**E4 senaryo dizisi (sahte model, belirleyici):** geçerli rapor → iddia düzenle → bir atıf kaldır → atıfın hücresini `cell_recheck` ile değiştir (kaldırılan atıf işaret açmaz, kalan açar) → bir kaynağı araştırmadan çıkar → denetle → yeniden düzenle (denetim eski) → "Böyle kalsın" sonra yeni değişiklik → geri yükle → purge/yedek gidiş-dönüşü. Bu dizi kod davranışını sınar, model kalitesini ya da gerçek bir korpusu değil.

## 10. Kapanış ölçümü: P9'a borç

17 Eylül taslağının "P6 kapanış ölçümü" (R18–R21, tutulmuş soru, gerçek model) bu dilimde **yoktur**; P9'a borç olarak taşındı. Sahibin dilim 2 ölçümü (D141, D142) ve dilim 3'ün K6'sı için verdiği karar ile tutarlı. Neden: ölçüm bugünkü kodla tamamlanmış gerçek-model bir rapor ister ve dondurulmuş P16 serisi böyle bir rapor üretemedi (D124, D126, D128; F7); dilim 4'ün davranışı (denetim kuralları, atıf kümesi, bayatlama) kodun kendisi olup modelin ürettiği bir şeyin kalitesi değildir ve §9'un sentetik testleri onu zaten bütün olarak sınar. Eşleme:

| Taslak satırı | Bu dilimde | P9'da |
|---|---|---|
| R18 düzenleme bütünlüğü | E4 sentetik dizisinin parçası olarak kod düzeyinde | Gerçek bir raporda düzenle-denetle-kaldır dizisi, ancak tamamlanmış bir gerçek-model rapor olunca |
| R19 bayatlama doğruluğu | E4 dizisi (yanlış negatif/pozitif sentetik) | Aynı gerçek raporda |
| R20 kimlik kararlılığı | Yok: kimlik katmanı ertelendi (§12), anlamsız | Yeniden yazma yapılırsa |
| R21 süre ve maliyet | Yok | Gerçek raporda |
| Bölüm yeniden yazma adımı (taslak §9.3 adım 5) | Yok (yeniden yazma ertelendi) | Yeniden yazma kurulursa |

P9 borcuna yazılacak: gerçek-model rapor tamamlanmışsa bir kopya kütüphanede §9'daki dizinin gerçek-rapor sürümü; beklentiler koşudan önce ayrı dosyada dondurulur; sonuç anlam desteği iddiası değildir. Bu not P9 planına yeni bir ölçüm tanımı koymaz; yalnız borcu ve ön koşulunu (tamamlanmış gerçek-model rapor) bırakır.

## 11. Varsayımlar ve sınırlar

- Denetim kod kurallarının yeniden koşmasıdır; semantik doğruluğu, atıf-iddia uyumunu ve sözcükle yazılmış sayıları göstermez.
- Güncel kip, temel kuralların bir alt kümesini düzenlenmiş veriye uygular; kural sayısı ya da kapsamı ölçülmedi, hangi düzenlemelerin ne kadarını yakaladığı bilinmiyor.
- Atıf kaldırma kanıtı azaltır, ekleyemez; yeni bir atıf eklemek (yeniden yazma ya da PDF'den alıntı) ertelendi.
- Düzenlenmiş metin hâlâ `report_view`'daki bölümün `draft`/`validation`/`word_count` alanında yoktur; onlar modelin yazdığı sürümü anlatır. Temel `report_version` ve D118 incelemesi modelin sürümüne bağlı kalır.
- Düzenleme sonrası rapor için yeni sürüm numarası yoktur: dışa aktarım dosya adı temel numarayı taşır ve "elle düzenlendi" cümlesi yanında durur.
- PDF yeniden çıkarımı ve pasaj değişiklikleri hiçbir düzeyde algılanmaz (`not_checked: ["passages"]`); bu denetim ve atıf kaldırma bunu değiştirmez.
- `purge_table` raporlu bir tabloda hâlâ başarısız olur (D112'nin açık borcu); bu dilim ona dokunmaz.
- Sentetik/sahte-model testleri iş akışı davranışını gösterir, model kalitesini ya da gerçek korpus davranışını değil.

## 12. Ertelenenler (nedeniyle)

- **"Yayımla", düzenleme sonrası yeni `report_version`, montaj denetiminin insan metniyle yeniden koşup numara vermesi** (taslak Q2a): numara semantiği (`reports.report_version` bir `finalize` anında, `(research_id, report_version)` benzersiz) yeniden tasarım ister; bu dilimin "Düzenlemeleri denetle"si aynı kaygının büyük kısmını numarasız çözer. Bir sonraki dilim ya da P9 kararı.
- **Bölüm yeniden yazma önerisi** (S3/S4), `report_section_revisions`, `claim_match`: bitmiş rapor için bölüm yeniden yazma işlemi yok; gerçek-model rapor bugünkü kodla tamamlanmadı (F3, F7).
- **Kararlı kimlik katmanı** (`report_stable_claims`, `report_claim_matches`, `report_stable_gaps`, `report_gaps.stable_gap_id`) ve **rapor sürümleri arası aday eşleştirmesi**: yeniden yazma olmadan eşleştirilecek bir şey yok ve dilim 3'ün adayı kökenini kopyalar, canlı gap satırına bağlanmaz (F4). **Dilim 3'ün D143 §15'te "dilim 4" diye yazdığı bu iş dilim 4'ten çıkarıldı**; yeniden yazma kurulursa o zaman ele alınır (D147 bunu kayda geçirir).
- **`scope_statement` düzenleme**, `report_plan_revisions`.
- **PDF yeniden çıkarım/pasaj bayatlaması** (anlık görüntüye çıkarım kimliği yazmak, slice 1 kodunu etkiler), **bölüm düzeyi sütun bayatlaması**.
- **Çizgi bağı ve aday bayatlaması:** dilim 2b/2c ve dilim 3 K3 yapılmadı.
- **Düzenlemenin isteğe bağlı `report_review`'ı**; **toplu yeniden yazma**; **iddia içi cümle düzenleme**.
- **P6 kapanış ölçümü** (§10).

## 13. Kararlar

Kararlar sahibin talimatıyla **Claude ve gpt-6.1-sol tarafından, 2 Ekim 2026'da** birlikte verildi; sahibe soru sorulmadı. Karar turu `/tmp/s4d-a1.md`. Sol üç yerde Claude'un önerisinden ayrıldı (Q2, Q3, Q8) ve Claude kabul etti; Q1, Q4–Q7 ve Q9'da aynı fikirdeydiler, Sol dört tehlike kümesi ekledi (sonuç sözleşmesi, kural kapsamı, revizyon şeması, yaşam döngüsü ve görünüm).

1. **Q1 — "Yayımla" ve yeni numara.** Ertelendi; `report_version` modelin yazdığı sürümü tanımlamaya devam eder, insan revizyonu ayrı görünür. *Claude önerdi, Sol kabul etti.*
2. **Q2 — "Not checked again" sınırı.** Yayımla yerine modelsiz, salt-okunur "Düzenlemeleri denetle"; sonuç eklemeli kayıt (kalıcılık "isteğe bağlı" değil zorunlu, Sol), girdiye bağlı parmak izi, çalıştırılan/atlanan kurallar, sürüm/numara değişmez. **Sol'un değişikliği:** kural listesi benim önerimden geniş: glossary sırası, denetim eşitlik/denklem kökeni, kendi çalışma ve çoğul kaynak tanılayıcıları dahil; kalıp çerçeveleri ve istisna eşleştirmesi insan metninde kapalı. *Claude önerdi, Sol değiştirdi, Claude kabul etti.*
3. **Q3 — Atıf kaldırma.** Dahil (E2); **Sol'un değişikliği:** geri yükleme metni ve atıf kümesini birlikte kurtarır; sıfır atıf "doğrudan atıf yok"tur (`body_ref`/`gap_ref`/`count` dayanak olabilir), ret değil. *Claude önerdi, Sol ekledi.*
4. **Q4 — Yeniden yazma, kararlı kimlik, `report_stable_gaps`.** Ertelendi; dilim 4'ün dilim 3'ün kimlik taahhüdünü artık yerine getirmediği kayda yazılır. *Claude ve Sol.*
5. **Q5 — Bayatlama uzantıları.** Ertelendi; denetim mevcut işaretleri ve "pasajlar denetlenmedi" sınırını bozmaz. *Claude ve Sol.*
6. **Q6 — Düzenleme incelemesi.** Ertelendi; D118 incelemesi modelin temel sürümüne bağlı olarak görünür kalır. *Claude ve Sol.*
7. **Q7 — Kapanış ölçümü.** P9'a borç, sentetik belirleyici dizi dilimde test olarak kalır; taslak §9.3 adım 5 (yeniden yazma) açıkça çıkarıldı (§10). Dilim 2'nin ölçümü ve dilim 3'ün K6'sı ile tutarlı. *Claude ve Sol.*
8. **Q8 — Batch'ler.** Dört batch; **Sol'un değişikliği:** boyutlar E1 M, E2 M–L (yaşam döngüsü dahil), E3 M, E4 S–M; bunlar planlama tahminidir, ölçüm değil. *Claude önerdi, Sol değiştirdi, Claude kabul etti.*
9. **Q9 — Gizli bağımlılık.** Yok: E1/E2 dilim 3 K3'e ya da bekleyen P7/P9 işine bağlı değildir; aday rozeti, kill-search geri yazımı, yasak sözcük gevşetmesi ve yeni model çağrısı dışarıda. *Claude ve Sol.*
- **X1. Taslağın "ilk tam rapor" iddiası.** `4582b64` gerçek ama dondurulmuş P16 serisi tamamlanmadı ve ilk rapor sonraki iyileştirmelerden önceydi; çelişki kayda geçti, not "tamamlanmış gerçek-model rapor kaydı var" demez (§0 F7). *Sol ekledi.*
- **X2. `has_human_edits`.** `edited_after_version` taslak raporda boş olduğundan ayrı alan (F8). *Sol ekledi.*
- **X3. `research_cites_asset`/`asset_impact` açığı.** E2'nin içinde kapatılır (F9). *Sol ekledi, Claude doğruladı.*
- **X4. Kapsam dışı kalan taslak kararları** (§12 Q1a–Q9a): soru 1 (birim iddia), 3 (otomatik inceleme yok), 4 (kabul hiç dolmaz), 6 (okuma anı) D112'de verilmişti ve değişmez; soru 2, 5, 7, 8, 9 yukarıda yeniden karara bağlandı.

## 14. Batch'ler

Her batch ayrı bir commit olur; commit ve push yalnız sahibin istediği zaman, doğrudan `main`'e (PR yok). Batch kabul edilirken tam takım (`PYTHONPATH=backend uv run pytest`, `npm run build`, `npm run lint`, tam Playwright) bir kez koşulur ve sayılar yazılır; geliştirme sırasında yalnız ilgili test dosyaları. Migration ve karar numarası yazım anında son numaradan sonra alınır. Canlı 8765 örneğine ve sahibin kütüphanesine dokunulmaz. Hiçbir batch'te model çağrısı yok: sahte adaptör. `skill_package_hash` hareket etmez; bu dilimin batch'leri H9 ölçüm penceresinin dışında kalır ya da H9 sabit bir checkout'ta koşar (dilim 3 ile aynı kural). Boyut: **S** yarım gün, **M** bir gün, **L** iki–üç gün; tahmin ölçüm değildir.

| Batch | Bağlı olduğu | Boyut | Model |
|---|---|---|---|
| E1 Düzenlenmiş raporun denetimi — yapıldı (D148); commit: bu satırı ekleyen commit | — | M | hayır |
| E2 Atıf kaldırma ve kayıtlı etkin atıf kümesi — yapıldı (D150); commit: bu satırı ekleyen commit | E1 | M–L | hayır |
| E3 Arayüz — yapıldı (D156); commit: bu satırı ekleyen commit | E1, E2 | M | hayır (senaryolu) |
| E4 Senaryo dizisi, kapanış ve P9 borcu | E1–E3 | S–M | hayır |

### E1 — Düzenlenmiş raporun denetimi (M)

**Durum:** yapıldı (D148); commit: bu satırı ekleyen commit.

**Kapsam.** `assembly.py`'ye "güncel" kip (temel kip ve mevcut çağrılar değişmez) ve tek bir etkin-atıf okuma noktası (E1'de "bütün bağlar", E2'de değişir); §5 tablosu; `report_edit_checks` migration'ı; `ReportStore.check_edits`; `POST .../reports/{id}/check-edits`; `report_view`'a `has_human_edits` ve `edit_check` (güncel/eski); dışa aktarımın üç durumlu cümlesi; VIII sayı yeniden anma denetiminin düzenlenmiş iddialara uygulanması; çalıştırılan/atlanan kural listesi; kanonik girdi parmak izi ve tek-işlemli değerlendirme+kayıt; **`report_edit_checks`'in yaşam döngüsü**: `purge_research` sırası, silme yetkisi tetikleyicisi, yedek-geri yükleme (kayıt doluyken araştırma silme ve yedek testi).
**Dosyalar.** `storage/migrations/00NN_report_edit_checks.sql`, `workflow/report/assembly.py`, `workflow/report/store.py`, `workflow/store.py` (`purge_research`), `backup.py`, `workflow/views.py`, `workflow/report/export.py`, `api/app.py`, `domain/contracts.py` (yalnız VIII denetimini yeniden kullanılabilir yapmak), `tests/test_report_edit_check.py`, `tests/test_report_assembly.py`, `tests/test_report_api.py`, `tests/test_backup.py`, `tests/test_corpus_removal.py` (purge ve yedek, kayıt doluyken).
**Testler/kontroller.** §9 E1 satırları; temel kip değişmez; durum/numara değişmez; tam pytest.
**Çıkış.** Düzenlenmiş bir rapor modelsiz denetlenir; sonuç API'de ve dışa aktarımda "güncel"/"eski" ve atlananlarla görünür; kayıt varken araştırma silinebilir ve yedeklenir. Ekranda görünüm E3'tür.
**Göstermez.** Anlam desteğini, sayıların sözcükle yazıldığı ya da hiç tamsayı bulunmayan durumların denetlendiğini (bunlar atlandı olarak yazılır), gerçek-model raporda isabeti, ekranı; atıf kaldırmayı.

### E2 — Atıf kaldırma ve kayıtlı etkin atıf kümesi (M–L)

**Durum:** yapıldı (D150); commit: bu satırı ekleyen commit.

**Kapsam.** Migration (`link_count`, `request_hash`, `report_claim_revision_links` ve mühürleme tetikleyicisi); `edit_claim`'in `link_ids`'i, yalnız-atıf düzenleme, geri yükleme ile atıf kümesi, içerik bağlı idempotency; etkin atıf tanımının tek yere bağlanması (denetim, bayatlama, numaralandırma, görünüm, dışa aktarım); `evidence_changes`'in bölüm düzeyini etkin atıflardan türetmesi; düzenlenmiş temele dayanan iddia notu; `evidence_basis`/`support_type_note`; yaşam döngüsü (§7, revizyon-bağ tablosu için): purge, `research_cites_asset`/`asset_impact` açığı, kaynak koruması, yedek.
**Dosyalar.** `storage/migrations/00NN+1_report_claim_links.sql`, `workflow/report/store.py`, `workflow/report/assembly.py`, `workflow/views.py`, `workflow/report/export.py`, `workflow/store.py`, `backup.py`, `api/app.py`, `tests/test_report_claim_links.py`, `tests/test_report_store.py`, `tests/test_asset_replacement.py`, `tests/test_backup.py`, `tests/test_migrations.py`.
**Testler/kontroller.** §9 E2 satırları; ham `report_citation_links` okumasını sınırlayan kaynak tarama testi; tam pytest.
**Çıkış.** Bir iddia atfını geri alınabilir biçimde kaybeder; denetim, bayatlama, numaralar ve dışa aktarım aynı etkin kümeyi okur; hiçbir bağ silinmez; kaynak koruması ve yedek tam geçmişi korur.
**Göstermez.** Atıf eklemeyi, atıf-iddia uyumunu, gerçek raporda davranışı.

### E3 — Arayüz (M)

**Durum:** yapıldı (D156); commit: bu satırı ekleyen commit.

**Kapsam.** §8: atıf kaldırma, geçmişte atıf kümesi, "Doğrudan atıf yok" durumu, "Düzenlemeleri denetle" ve sonuç listesi, düzenlenmiş temele dayanma notu; `api.ts`, `i18n.ts`.
**Dosyalar.** `apps/web/src/report/ReportView.tsx`, `apps/web/src/api.ts`, `apps/web/src/i18n.ts`, `apps/web/e2e/report.spec.ts`.
**Testler/kontroller.** §9 Web satırı; `npm run build`, `npm run lint`, tam Playwright; 390 px ve masaüstü, iki tema, gözle doğrulama.
**Çıkış.** Senaryolu modelle uçtan uca akış ekranda çalışır.
**Göstermez.** Gerçek rapor kalitesini.

### E4 — Senaryo dizisi, kapanış ve P9 borcu (S–M)

**Kapsam.** §9'daki belirleyici dizi (sahte model); kayıt: `decisions.md` kapanış girdisi (Evidence, Limits), `p6-report-design.md` "Durum" satırı, P9 planına borç satırı (§10), D143 §15'in "dilim 4" cümlesinin düzeltilmesi.
**Dosyalar.** `tests/test_report_edit_sequence.py`, `docs/decisions.md`, `docs/product/p6-report-design.md`, `docs/product/p9-hardening-plan.md`, `docs/product/p6-slice3-kill-search.md` (yalnız §15'in "dilim 4" cümlesine D147'ya işaret eden bir not; kabul edilmiş D143 girdisi geçmiş olarak değiştirilmez).
**Testler/kontroller.** Tam takım; `git diff --check`.
**Çıkış.** Dizi geçer; borç ve ertelenenler kayıtlı.
**Göstermez.** Gerçek-model rapor davranışını, oran ya da genellemeyi.
