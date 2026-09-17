# P6 — Toplanan kanıttan bölümlü rapor (survey biçimi): tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Taslak; §2'deki kararlar sahiple bu oturumda alındı, §11'deki inceleme `gpt-5.6-sol` (effort high) ile yapıldı. Kod değişmedi. Bu not P6'nın ilk iki dilimini tanımlar; kill-search ve aday kartı (dilim 3) ile düzenleme ve ölçüm (dilim 4) ayrı notlarla gelir.

**Kısaca:** Bugünkü kısa yanıtın yanına, aynı kanıttan yazılan bölümlü bir rapor gelir: abstract, index terms, giriş, inceleme metodolojisi, arka plan, kanıt tablolu literatür sentezi, karşılaştırmalı bulgular, cevaplanmamış yön adayları, gelecek yönler, sınırlılıklar, sonuç ve kaynakça. Rapor tek model çağrısıyla değil, bir çalışma içinde bölüm başına bir adımla yazılır; her adım aynı dondurulmuş rapor planını ve kendi bölümüne ait kanıtı alır. Related-work tablosu modelin düzyazısı değil, P5'teki kanıt tablosudur. Gap'ler ilk günden vardır ama her biri "incelenen korpusta bulunmadı, denetlenmemiş aday" etiketini ve kaynakçasını taşır; kill-search gelince durum alır. Denklemler yanıttaki kuralla LaTeX yazılır ve KaTeX ile çizilir.

## 1. Kodda bugün olan

- **Yanıt zaten bölümlü bir rapor.** `grounded_answer` talimatı "bölümlere ayrılmış kapsamlı rapor" ister; her iddia `section` başlığı, `support_type` (`source_stated` / `analyst_inference`), en fazla beş pasaj ve pasajda bulunması zorunlu bir alıntı çapası taşır (`contracts/research/grounded-answer-draft.schema.json`). Sınırlar: 60 iddia, iddia başına 2000 karakter, 300 çapa. Yapısal olarak geçerli her yanıt bir `report_version` numarası alır (migration `0023`).
- **Adımlar `operation_key` ile tekrarsız.** Başarılı adım saklanan çıktısını döndürür; duraklat/devam ve çökme kurtarma buna dayanır (`workflow/flow.py`, `worker.py`).
- **Denklem hattı.** Talimat 7. madde LaTeX ister; `domain/contracts.py::_check_math` her matematik aralığının iyi biçimli olduğunu denetler; Marker (D52) PDF'den LaTeX okur; `MathText.tsx` KaTeX ile çizer.
- **Phrasebank.** `references/phrases.md` her kalıbı İngilizce ve `tr:` satırıyla Türkçe verir; `grounded_answer` adımına tamamı yüklenir (`domain/skill.py::RUNTIME_FILES`), denetim uyarı düzeyindedir (D15).
- **Kanıt tablosu (P5 dilim 1, D37/D43).** Sütunlar kullanıcı onaylı (model önerebilir: `table_columns`), satır başına bir dahil kaynak, hücreler `cell_extraction` adımıyla alıntılı doldurulur, durumlar arasında `not_found_in_inspected_scope` vardır, okuma derinliği hücrede ayrı saklanır, insan düzenlemesi korunur, tek hücre yeniden incelenir (`cell_recheck`). Bir doldurma çalışması en fazla 25 kaynak okur (`MAX_FILL_SOURCES`); D55'te 50 kaynaklı doldurma 506–576 saniye sürdü.
- **PDF hazırlığı (D49).** Taramadan sonra `pdf_collection` çalışması açık erişimli PDF'leri toplar; `PdfReadiness.tsx` üç durumu gösterir (tarama bitti, toplanıyor, toplama bitti) ve eksikleri yükletir; "Generate source-linked answer" butonu buradadır.
- **Kaynakça dışa aktarımı.** `workflow/bibliography.py::export_sources` seçili kaynakları RIS/BibTeX olarak verir (Zotero uyumlu).
- **Yanıt incelemesi.** `answer_review` adımı yanıtın iddialarını alıntılanan pasajlara karşı ayrı bir model çağrısında denetler.
- **Yasak.** `SKILL.md` modele araştırma gap'i ya da yön önermeyi yasaklar; yalnız `unanswered_aspects` listelenir. Plan T12: boş arama özgünlük değildir. Kill-search yapılmadı.

Ölçülmüş durum (D55, 17 Eylül 2026, Claude'un incelemesi): yanlış atıf 0; yanıtlar çoğunlukla özet temelli; dahil edilen bilinen eserlerin PDF'i DEIXIS'in kendi yollarıyla 0/7 ve 0/5 alındı; tutulmuş soruda bilinen eser geri çağırımı 4/15. Bu iki sorun bu notun dışındadır ama raporun dürüstlüğünü belirler (§7, §9, §11).

## 2. Sahiple alınan kararlar (17 Eylül 2026)

1. **Gap'ler ilk günden, etiketli.** Rapor "cevaplanmamış yön adayları" bölümünü ilk dilimden itibaren içerir; her aday analist çıkarımıdır, "incelenen N kaynakta bulunmadı" der ve kill-search yapılmadığını söyler. Dilim 3'te her aday bir kill-search'e bağlanır ve `narrowed` / `closed` / `open` durumu alır. (Seçenek B "kill-search'e kadar gap yok" ve C "model serbest" reddedildi.)
2. **Dil sorunun dili.** Yanıtla aynı kural; phrasebank iki dilde hazır. Bölüm düzeni dile bağlı değildir.
3. **Related-work tablosu = kanıt tablosu.** Model raporun içinde tablo yazmaz. Rapor tabloyu şart koşar; yoksa PDF hazırlığı paneli dördüncü duruma geçer: sütun önerisi → sahip onaylar/değiştirir → doldurma bütün dahil kaynaklar bitene kadar 25'lik partilerle sürer → rapor butonu etkinleşir. Sonradan PDF yüklenen kaynağın satırı yalnız `cell_recheck` ile güncellenir.
4. **Yanıt ve rapor ayrı butonlar.** Yanıt tablo istemez ve bugünkü gibi çalışır; rapor tabloyu ister. (Raporun yanıtın yerini alması reddedildi.)
5. **Denklemler.** Rapor bölümleri denklem kuralında yanıttan farklı olamaz: LaTeX, iyi biçim denetimi, Marker/OCR kaynaklı ifadelerde "sayfayla denetlenmeli" uyarısı, KaTeX çizimi.
6. **Yürütme bölüm başına adım.** Tek çağrı değil, farklı ajan da değil: aynı araştırma ajanı bölüm başına bir adımda çağrılır (§4).

## 3. Rapor iskeleti

Sabit şablon; model bölüm icat etmez, yalnız IV içinde tema alt başlıkları açabilir. Başlıklar sorunun dilinde yazılır; aşağıdaki adlar şablonun kimlikleridir.

| # | Bölüm | Kim yazar | Girdi |
|---|---|---|---|
| — | Abstract, Index Terms | model, en son | bitmiş bölümlerin iddia özetleri; index terms arama planı kavram sözlüğünden (D44) seçilir, yeni terim eklenmez |
| I | Introduction | model, gövdeden sonra | rapor planı (§5), gövde bölümlerinin iddia özetleri; kapsam, sorular, katkı ve düzen |
| II | Review Methodology | kod | sağlayıcılar, derlenmiş sorgular ve tarihleri, bulunan/tekil/taranan/dahil sayıları, PDF edinme yolları ve tam metin oranı, tarama ölçütü, model kimlikleri; §9 |
| III | Background and Taxonomy | model | terim sözlüğü ve eksenler (rapor planından), tanım içeren pasajlar; denklemler LaTeX |
| IV | Literature Synthesis | tablo + model | kanıt tablosu hücreleri (alıntılarıyla) ve satırların pasajları; tema alt başlıkları modelin |
| V | Comparative Findings | model | hücreler, çelişen pasajlar; uzlaşı ve çelişki paydayla (§6) |
| VI | Candidate Unanswered Aspects | model + kod | `not_found` toplamları, kaynakların kendi sınırlamaları, çelişkiler; her aday §7'deki kaynakçayla |
| VII | Future Directions | model | VI'nın adayları ve dayandıkları pasajlar; her yön bir adaya bağlı analist çıkarımı |
| VIII | Limitations and Threats to Validity | kod + model | geri çağırım ölçümü varsa sayısı, açık erişim/yükleme yanlılığı, özet-tam metin oranı, model çıkarımı payı, kill-search yokluğu |
| IX | Conclusion | model | gövde özetleri; gövdede olmayan genelleme yasak (§8) |
| — | References | kod | yalnız atıf alan kaynaklar, `bibliography.py` üzerinden; sürüm bilgisi ayrı satırda |

"Open Problems" ve "Future Directions" ayrı tutulur: VI yalnız kanıt durumunu tanımlar, VII bu durumdan türeyen önerileri verir. Rapor kendini "survey" diye adlandırmaz; başlık sahibindir, gövde her zaman korpus sayılarını söyler (II ve VIII).

## 4. Yürütme: `report` çalışması ve adımları

Yeni çalışma türü `report`. Ön koşul: en az bir dahil kaynak ve dahil kaynakların tamamını kapsayan bir kanıt tablosu (§9). Adımlar sırayla; her adımın kendi `operation_key`'i vardır ve başarılı adım tekrar çağrılmaz.

1. `report_plan` (model, §5).
2. II Review Methodology (kod).
3. III, IV, V, VI, VII (model, bu sırayla; her biri önceki bölümlerin iddia özetlerini alır).
4. I Introduction (model).
5. VIII Limitations (kod çekirdek + model cümleleri).
6. IX Conclusion (model).
7. Abstract ve Index Terms (model).
8. Montaj ve denetim (kod, §8).
9. `report_review` (model; `answer_review`'ın rapor düzeyi karşılığı, §8).

**Her model adımının girdisi:** `StepInput` zarfı (`step_input_id`, `scope_revision`, `skill_package_hash`), dondurulmuş rapor planı, o bölüme kod tarafından seçilmiş kanıt kayıtları (pasajlar ve/veya hücreler, allowlist), önceki bölümlerin özetleri (iddia kimliği + bir satır; tam metin değil), phrasebank'in o bölüme ait kısmı ve bölüm şeması. Kanıt seçimi bölüme göre yapılır; 48 pasajlık yanıt girdisi her bölüme kopyalanmaz.

**Bölüm şeması** yanıt şemasının bölüm sürümüdür: `section_id` sabit; iddialar `claim_key` (kararlı, `IV.3` gibi), `text`, `support_type`, `passage_ids` ve/veya `cell_ids`, `citation_anchors`; ayrıca `terms_used` (sözlükten), `gap_refs` (VI ve VII için), `subsections` (yalnız IV). Sınırlar bölüm başına 40 iddia ve bütçe kelime sayısı (planda). Aynı çapa kuralı: çapası pasajda bulunmayan iddia bölümü taslağa düşürür, D56'daki nihai kurtarma bölüm düzeyinde uygulanır.

**Model.** Bütün adımlar araştırmanın seçili modeliyle çalışır; bir bölümde model değişmez, uyuşmazlık `model_mismatch` olarak kaydedilir ve kullanılmaz. Beklenen maliyet: 9 model çağrısı + inceleme; D55'teki yanıt sürelerine göre çağrı başına 2–3 dakika, tablo hariç 20–30 dakika. Bu tahmin ölçülmedi.

**Duraklatma, iptal, kapsam değişimi.** `_checkpoint` her adım arasında çalışır. Yeni kapsam revizyonu raporu durdurur; tamamlanmış bölümler eski revizyon etiketiyle saklanır, yeni revizyonun raporu olarak gösterilmez (T18).

## 5. Rapor planı (`report_plan`)

Bölümler arası tutarlılığın tek kaynağı. Model bir kez üretir, kod sayıları doldurur, sonra dondurulur ve her bölüm adımına aynen verilir.

- `scope_statement`: tek paragraf, sorunun dilinde.
- `research_questions`: 2–5 soru, kimlikli (`RQ1`…).
- `glossary`: terim → tanım → tanımın geldiği pasaj; bölümler tanımsız terim kullanamaz (§8).
- `axes`: sınıflandırma eksenleri, her biri bir kanıt tablosu sütununa bağlı; sütunda karşılığı olmayan eksen olmaz.
- `section_budgets`: bölüm başına kelime aralığı ve iddia üst sınırı.
- `corpus`: kod doldurur; bulunan/tekil/dahil/tam metinli sayıları, tarama ve toplama tarihleri.
- `allowed_support`: bölüm başına izinli iddia türleri (örneğin VI ve VII yalnız `analyst_inference`).

Plan model çıktısıdır ve şema denetiminden geçer; eksen–sütun bağı ve sözlük pasajları allowlist'ten denetlenir. Plan değişirse (sahip düzenlerse) sonraki bölümler yeniden yazılır, önceki bölümler `stale` işaretlenir (dilim 4).

## 6. Kanıt tablosu ve IV/V tartışma kuralları

Tablo P5'teki tablodur; bu not hücre şemasına yeni durum eklemez (dilim 1 karar 5: `not_found_in_inspected_scope` kuralı kalır). Okuma derinliği hücrede zaten ayrıdır ve tartışma adımına verilir.

Sütun önerisi (`table_columns`) rapor için çağrılırken talimata şu tercih eklenir: araştırma amacı, uygulama alanı, problem modeli, yöntem, veri/deney ortamı, karşılaştırıcılar, ölçütler, temel bulgu, yazarların belirttiği sınırlamalar ve sorunun sorduğu X/Y/Z kapsam sütunları. Sütun tanımları doldurmadan önce donar; sonradan sütun eklemek yeni doldurma demektir.

IV ve V adımlarının talimatına giren kurallar (ihlali `report_review` yakalar, montaj denetimi mümkün olanları kodla yakalar):

- `not_found_in_inspected_scope` hücresi "çalışma bunu incelemedi/ele almadı" diye yazılamaz; yalnız "incelenen kapsamda (özet / tam metin) bildirilmedi" denir.
- Olumsuz önerme ("X'i dikkate almaz") yalnız kaynak bunu açıkça dışladıysa ya da sınırlama olarak yazdıysa kurulur; o hücrenin alıntısı atıf olur.
- Her toplulaştırma payda verir: "tam metni incelenen 6 çalışmanın 4'ü"; özet hücreleri ile tam metin hücreleri aynı sayıma katılmaz.
- Çelişki iddiası ancak aynı kavram, koşul ve ölçüt karşılaştırılabilirse kurulur; koşul farkı varsa "farklı koşullarda farklı sonuç" denir (T11).
- Hücreler arası boşluktan yöntem ya da sonuç çıkarımı yapılmaz.
- Tema alt başlıkları eksenlerden türetilir; eksende olmayan tema açılmaz.

## 7. Cevaplanmamış yön adayları (VI)

Her aday bir kayıttır, düzyazı değil. Üç tür; her birinin dayanağı kodla denetlenir:

| Tür | Dayanak | Kod denetimi |
|---|---|---|
| `stated_limitation` | bir ya da daha çok kaynağın kendi yazdığı sınırlama | atıf çapası "sınırlamalar" hücresinde ya da pasajda bulunur |
| `conflicting_evidence` | V'te kurulmuş bir çelişki | V'teki iddia kimliğine bağ |
| `corpus_absence` | bir eksende dahil kaynakların hiçbirinde bildirilmemiş olması | ilgili sütunda bütün hücreler `not_found` ya da `not_applicable`; tam metin oranı eklenir |

Her adayın kaydı: `gap_id`, tür, metin (analist çıkarımı), dayandığı hücre ve pasaj kimlikleri, en yakın kısmi eşleşme (varsa hangi kaynak, hangi hücre), ve kod tarafından eklenen kaynakça: arama tarihi, sağlayıcılar, sorgu sürümü, bulunan/dahil sayıları, tam metin oranı, `kill_search_status: not_run`. VII'deki her yön bir `gap_id`'ye bağlıdır; bağsız yön şema hatasıdır.

Sözcük kuralı: kill-search yapılmadan "gap", "open problem", "novel", "first" ve eşdeğerleri VI ve VII'de kullanılmaz; "candidate unanswered aspect / cevaplanmamış yön adayı" kullanılır. Bu, `SKILL.md`'deki yasağın rapor için gevşetilmiş biçimidir: yasak yanıt için aynen kalır, rapor bölümleri VI ve VII için bu türlerle ve etiketle açılır.

## 8. Montaj denetimi ve rapor incelemesi

Montaj kod işidir ve model çağırmaz. Hata bulursa rapor `unverified_draft` olur ve hangi bölümün yeniden yazılacağını söyler:

- Aynı `claim_key` ya da aynı metinli iddia iki bölümde.
- Sözlükte olmayan terim `terms_used`'da; sözlükteki terimin bölümde başka adla geçmesi uyarıdır.
- Abstract, I ve IX'daki her iddia gövdede bir `claim_key`'e bağlanır; bağsız iddia hatadır.
- II ve VIII'deki sayılar `corpus` ile birebir aynıdır (kod yazdığı için farkı model üretemez; model cümleleri sayı içeremez).
- Her atıf kaynakçada, kaynakçadaki her kayıt en az bir atıfta.
- VII'deki her yön bir `gap_id`'ye, VI'daki her aday §7'deki dayanağa bağlı.
- Toplam ve bölüm kelime sayısı plandaki bütçede.
- Matematik aralıkları iyi biçimli; Marker/OCR kaynaklı ifadeler uyarı taşır.

`report_review` bir model adımıdır: bölümlerin iddialarını alıntılanan pasaj ve hücrelere karşı okur, §6 kurallarını ve abstract–gövde tutarlılığını denetler, `answer_review` gibi bulgu listesi verir ve ana metne yazmaz.

## 9. Arayüz ve dışa aktarma

- **PDF hazırlığı paneli, 4. durum "Tablo dolduruluyor".** Sütun önerisi kartı (onayla / düzenle), parti ilerlemesi ("25 / 52 kaynak okundu, 2. parti sürüyor"), tamamlanınca "Write report" birincil buton. "Generate source-linked answer" bugünkü yerinde kalır ve tablo istemez. Yükleme yapılmadan devam edilebilir; özet temelli satırlar tabloda ve raporda öyle görünür.
- **Rapor görünümü.** Bölümler sırayla, iddialar bugünkü atıf çipleriyle (`citations.tsx`), IV'te tablo `EvidenceTable.tsx` ile gömülü, VI'daki adaylar tür ve "kill-search yapılmadı" rozetiyle. Taslağa düşen bölüm kırmızı değil, "bu bölüm yeniden yazılmalı" satırıyla gösterilir; diğer bölümler okunabilir kalır.
- **Dışa aktarma.** Dilim 1: Markdown (tablo Markdown tablosu, denklemler `$…$`, kaynakça numaralı). Dilim 2: IEEEtran LaTeX (`\cite{}` anahtarları `source_key`'den, tablo `table*`, denklemler değişmeden). İki çıktı da "DEIXIS ile üretildi; korpus: … sayıları" satırını II'den alır.
- **Zaman çizelgesi.** `report` çalışması bugünkü çalışma satırlarıyla görünür: her bölüm bir adım satırı ("III yazıldı · 12 iddia · 9 kaynak"), montaj ve inceleme ayrı satır.

## 10. Veri modeli taslağı

SQL'in geçerli hali migration dosyası olur; bu taslak niyettir.

- `runs.kind` listesine `report`.
- `reports(id, research_id, run_id, scope_revision, status, language, plan_json, report_version, created_at)`; `report_version` yanıttaki gibi yalnız geçerli raporlarda sayılır.
- `report_sections(id, report_id, section_id, step_id, status, draft_json, validation_json, word_count, order)`; iddialar ve çapalar yanıttaki `claims` tablosunun aynı yapısıyla, `section_id` ile.
- `report_gaps(id, report_id, gap_id, kind, text, basis_json, provenance_json, kill_search_status)`.
- `report_table(report_id, table_id, table_revision)`: raporun hangi tablo sürümüne dayandığı; tablo değişince rapor `stale` (dilim 4).

## 11. Sol incelemesi (17 Eylül 2026) ve alınan/alınmayan öneriler

`gpt-5.6-sol`, effort high, Codex üzerinden, araçsız; tam yanıt `.local/`'e değil oturum scratchpad'ine yazıldı. On öneri verdi:

| # | Öneri | Karar |
|---|---|---|
| 1 | Geri çağırım ve tam metin eşiği sağlanana kadar "survey" değil "bounded evidence report" de | Kısmen: rapor kendini adlandırmaz, sayılarını söyler (§3); ad sahibindir |
| 2 | Ölçüm ve stale işaretlemeyi ilk dilime al, önce arama/PDF sorunlarını çöz | Kısmen: ölçüm beklentileri dilim 1'den önce yazılır (§13); stale dilim 4; PDF edinme ayrı not (P5 açık ucu) |
| 3 | Metodolojiyi sentezin önüne al; kapsam/sınıflandırma/katkı ekle | Alındı (§3, §5) |
| 4 | Dondurulmuş `ReportContract`; kararlı claim/term/gap kimlikleri | Alındı (§5) |
| 5 | Montaj sonrası rapor düzeyi JSON denetimi | Alındı (§8) |
| 6 | Hücrede sonuç ve derinlik ayrı alan; `not_reported` "incelenmedi" diye yorumlanamaz | Derinlik zaten ayrı; yorum yasağı alındı (§6); yeni hücre durumu eklenmedi |
| 7 | Gap adayı kaynakçalı | Alındı (§7) |
| 8 | Kill-search'ten önce "open problem"/yenilik dili yasak | Alındı (§7) |
| 9 | Limitations and Threats to Validity bölümü | Alındı (§3 VIII) |
| 10 | İlk sürüm Markdown; IEEEtran ve serbest alt bölüm sonra | Markdown önce alındı; IV'te eksen bağlı alt başlık kaldı (§6) |

Beş türlü gap sınıflaması (Sol'un `reporting_absence`, `corpus_absence`, `conflicting_evidence`, `stated_limitation`, `research_opportunity`) üçe indirildi (§7): kalan ikisi kodla denetlenemiyordu.

## 12. Dilimler

1. **Rapor çalışması.** `report` türü, `report_plan`, bölüm adımları ve şemaları, phrasebank bölüm yükleme, montaj denetimi, `report_review`, hazırlık panelinde tablo doldurma durumu, rapor görünümü, Markdown dışa aktarma. Sentetik testler: fixture'lara bölüm girdileri ve sahte çıktılar; montaj denetiminin her kuralı için bir test. Gerçek modelle bir rapor `gpt-5.6-luna` ile yazılır ve §13'teki beklentilerle karşılaştırılır.
2. **Modelsiz bölümler ve LaTeX.** II ve VIII'in kod çekirdeği, gap kaynakçası, IEEEtran dışa aktarımı, `source_key` tabanlı `\cite`.
3. **Kill-search ve aday kartı.** Ayrı not; VI'daki adaylara durum verir.
4. **Düzenleme, bayatlama, ölçüm.** Bölüm düzenleme (T09), tablo/kanıt değişince `stale`, ölçüm koşusu.

Ayrı iş, bu notun dışında: **PDF edinme** (D55 M3 = 0/7 ve 0/5) için tasarım notu. Raporun kalitesi ona bağlıdır; bu not onu çözmez, yalnız sayıyı görünür kılar.

## 13. Ölçüm beklentileri (dilim 1'den önce dondurulur)

P5 dilim 5'teki kural: beklenti koşudan önce yazılır ve commit'lenir; sonuç sonradan yorumlanıp beklentiye uydurulmaz. Sayısal aralıklar bu notta değil, koşudan önce ayrı bir dosyada donar. Ölçülecekler:

| # | Ne | Payda |
|---|---|---|
| R1 | Geçerli bölüm oranı ve yeniden yazma sayısı | bölüm adımları |
| R2 | Yanlış atıf (iddia–pasaj), Claude incelemesi | rastgele 20 iddia |
| R3 | §6 ihlali: `not_found` hücresinin "incelemedi" diye yazılması | IV ve V'teki olumsuz önermeler |
| R4 | Abstract/I/IX'daki bağsız iddia (montaj yakalamalı) | o bölümlerin iddiaları |
| R5 | Terim tutarsızlığı | sözlük terimleri |
| R6 | Denklem aktarımı: PDF sayfasıyla karakter karakter | denklem içeren iddialar |
| R7 | Süre, çağrı, token | çalışma |

Sahibin okuma değerlendirmesi ayrı raporlanır; Claude'un okuması "insan denetimi" sayılmaz.

## 14. Varsayımlar ve sınırlar

- Rapor, korpusun kapsamını iyileştirmez; D55'teki geri çağırım ve PDF edinme sorunları rapora aynen yansır ve II/VIII'de görünür.
- Phrasebank uyumu güvenilirlik ölçütü değildir; uyarı düzeyinde kalır.
- Bölüm başına adım tutarlılığı garanti etmez; plan, özetler ve montaj denetimi bunu azaltır, `report_review` kalanı bulur. Ölçülmedi.
- Tablo doldurma ve rapor birlikte 50 kaynaklı bir araştırmada bir saate yaklaşabilir; süre ölçülmedi.
- Bir bölüm "structurally valid" olsa da semantik doğrulama değildir; T01'deki kural rapor için de geçerlidir.

## 15. Sahibe kalan sorular

Her birinde önerilen seçenek ilk sırada; cevap gelmezse ilk seçenekle ilerlenir.

1. **Rapor başlığı.** (a) `research_title` adımı raporun başlığını da yazar, sahip düzenler; (b) sahip başlığı raporu başlatırken girer.
2. **Bölüm bütçeleri.** (a) Varsayılan toplam 4000–7000 kelime, IV en geniş; (b) sahip raporu başlatırken kısa/orta/uzun seçer.
3. **Özet temelli satırlar tabloda.** (a) Tabloda kalır, raporda "özet" rozetiyle sayılır ve paydaya ayrı girer; (b) rapor yalnız tam metinli satırları tartışır, özet satırlar yalnız listelenir.
