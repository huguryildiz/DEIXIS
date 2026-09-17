# P6 — Toplanan kanıttan bölümlü rapor (survey biçimi): tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Kabul edildi (17 Eylül 2026): §2'deki kararlar ve §15'teki üç soru sahiple bu oturumda kapandı, §11'deki iki inceleme `gpt-5.6-sol` (effort high) ve `gpt-6-astra` (effort medium) ile yapıldı; ikincisinin talepleri ve sahibin üç ek kararı bu sürüme işlendi. Kod değişmedi. Bu not P6'nın ilk iki dilimini tanımlar; kill-search ve aday kartı (dilim 3) ile düzenleme ve ölçüm (dilim 4) ayrı notlarla gelir.

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
5. **Denklemler.** Rapor bölümleri denklem kuralında yanıttan farklı olamaz: LaTeX, iyi biçim denetimi, Marker/OCR kaynaklı ifadelerde "sayfayla denetlenmeli" uyarısı, KaTeX çizimi. Soru ya da rapor planı formülasyon istiyorsa (karar değişkenleri, amaç, kısıtlar, kanal/enerji modelleri), rapor literatürdeki denklemleri **içerir**: III'te temel modeller, IV'te kaynak başına formülasyon, yanıt talimatının 7. maddesindeki düzenle (önce değişkenler ve anlamları, sonra amaç, sonra kısıtlar) ve yalnız alıntılanan pasajın yazdığı biçimde. Denklemi olan bir kaynağı denklemsiz anlatmak, tam metni varken, `report_review`'ın bulgusudur. Soru formülasyon istemiyorsa denklemler yalnız anlam için gerektiğinde girer.
6. **Yürütme bölüm başına adım.** Tek çağrı değil, farklı ajan da değil: aynı araştırma ajanı bölüm başına bir adımda çağrılır (§4).
7. **Eş zamanlı model çağrısı.** Bugün tablo doldurma kaynakları tek tek dolaşıp her çağrıyı bekler (`flow.py::_table_fill`); D55'teki 506–576 saniye bundan. Tablo doldurma ve birbirine bağlı olmayan rapor bölümleri aynı anda gönderilir; açık istek sayısı ayarlanabilir bir üst sınırla (başlangıç 6) tutulur, kota hatasında sınır düşer ve kalanlar bekler. Her adım yine kendi `operation_key`'ini, kaydını ve denetimini taşır. Tablo doldurmanın eş zamanlı hâli rapordan bağımsız bir değişikliktir ve dilim 1'den önce yapılır (§12).
8. **Phrasebank hedefli onarımla sıkı.** Bugün kalıp denetimi uyarıdır (D19). Rapor bölümlerinde kalıba uymayan cümleler bir hedefli onarım çağrısına gider (yalnız o cümleler ve her biri için en yakın üç kalıp; bölüm yeniden yazılmaz); onarımdan sonra da uymayan cümle kalırsa bölüm taslağa düşer ve cümleler listelenir (§8). Bölüm adımına kalıp bankasının yalnız o bölüme ait kısmı yüklenir. Denetim biçimseldir: kalıbın anlama uygunluğunu kod değil `report_review` okur. (Onarımsız sıkı ret ve bugünkü uyarı düzeyi reddedildi.)
9. **İnsan okur biçimi.** Rapor iddia kartları listesi olarak değil, makale gibi okunur: akan paragraflar, numaralı başlıklar, IEEE usulü sayısal atıf (`[3]`, ilk geçiş sırasına göre), numaralı tablo ve denklemler, sonda kaynakça. İddia kimlikleri, kısa tutamaçlar, destek türü etiketleri ve alıntı çapaları okuma görünümünde görünmez; kanıt, atıf numarasına tıklayınca bugünkü pasaj sayfasında açılır ve ayrı bir "kanıt görünümü" anahtarıyla satır içinde gösterilir (§9). Dışa aktarılan dosya da aynı okunur biçimdedir; içinde JSON, kimlik ya da iç durum adı bulunmaz.
10. **Yokluk yalnız tam metinden.** `corpus_absence` adayı yalnız tam metni incelenen satırlardan hesaplanır; yalnız özeti okunan satırlar o sütunda "değerlendirilemez" sayılır ve ayrı yazılır. Bir sütunda tam metinli ve uygulanabilir satır üçten azsa aday üretilmez. "Özetinde bildirilmedi" yalnız paydalı bir sayım cümlesinde geçebilir; tek kaynak hakkında kurulamaz (§6, §7). (Özet satırları da saymak reddedildi.)
11. **Taslak bölüm bağımlılarını durdurur.** Bir bölüm taslağa düşerse ona bağlı bölümler başlamaz, aynı turdaki bağımsız bölümler tamamlanır ve saklanır; çalışma "IV yeniden yazılmalı" diye durur ve o bölüm yeniden denenince kaldığı yerden sürer. Rapor sürüm numarasını yalnız bütün bölümler geçerli ve montaj denetimi temizse alır. Yarım rapor okunur ve dışa aktarılır, ama başında "TASLAK: IV doğrulanmadı" satırıyla ve sürüm numarasız (§4.2). (Taslak bölümün girdi olması reddedildi.)
12. **Kanıta sadakat kalıba sadakatten önce gelir.** Kalıp onarımı bir cümlenin anlamını bozarsa (inceleme "destek bozuldu" derse) özgün cümle geri konur ve "incelenmiş istisna" olarak kalır; bölüm geçerli sayılır. Sıkılığın tanımı: her cümle ya bir kalıba uyar ya da adıyla listelenmiş bir istisnadır (§8). (Bölümü taslağa düşürmek ve ikinci onarım reddedildi.)

## 3. Rapor iskeleti

Sabit şablon; model bölüm icat etmez, yalnız IV içinde tema alt başlıkları açabilir. Başlıklar sorunun dilinde yazılır; aşağıdaki adlar şablonun kimlikleridir.

| # | Bölüm | Kim yazar | Girdi |
|---|---|---|---|
| — | Abstract, Index Terms | model, gövdeden sonra (I ve IX ile aynı turda; onları girdi almaz) | gövde bölümlerinin (III–VIII) iddia özetleri; index terms arama planı kavram sözlüğünden (D44) seçilir, yeni terim eklenmez |
| I | Introduction | model, gövdeden sonra | rapor planı (§5), gövde bölümlerinin iddia özetleri; kapsam, sorular, katkı ve düzen |
| II | Review Methodology | kod | sağlayıcılar, derlenmiş sorgular ve tarihleri, bulunan/tekil/taranan/dahil sayıları, PDF edinme yolları ve tam metin oranı, tarama ölçütü, model kimlikleri; §9 |
| III | Background and Taxonomy | model | terim sözlüğü ve eksenler (rapor planından), tanım içeren pasajlar; denklemler LaTeX |
| IV | Literature Synthesis | tablo + model | kanıt tablosu hücreleri (alıntılarıyla) ve satırların pasajları; tema alt başlıkları modelin |
| V | Comparative Findings | model | hücreler, çelişen pasajlar; uzlaşı ve çelişki paydayla (§6) |
| VI | Candidate Unanswered Aspects | model + kod | tam metinli satırlardaki `not_found_in_inspected_scope` toplamları (kod hesaplar), kaynakların kendi sınırlamaları, çelişkiler; her aday §7'deki kaynakçayla |
| VII | Future Directions | model | VI'nın adayları ve dayandıkları pasajlar; "önerilen gelecek çalışma" sütununun hücreleri. Bir yön ya bir kaynağın kendi önerisidir (`source_stated`, o hücrenin alıntısıyla) ya da bir adaya bağlı analist çıkarımıdır; ikisi metinde ayrı yazılır |
| VIII | Limitations and Threats to Validity | kod + model | geri çağırım ölçümü varsa sayısı, açık erişim/yükleme yanlılığı, özet-tam metin oranı, model çıkarımı payı, kill-search yokluğu |
| IX | Conclusion | model | gövde özetleri; gövdede olmayan genelleme yasak (§8) |
| — | References | kod | yalnız atıf alan kaynaklar, `bibliography.py` üzerinden; sürüm bilgisi ayrı satırda |

"Open Problems" ve "Future Directions" ayrı tutulur: VI yalnız kanıt durumunu tanımlar, VII bu durumdan türeyen önerileri verir. Rapor kendini "survey" diye adlandırmaz; başlık sahibindir, gövde her zaman korpus sayılarını söyler (II ve VIII).

## 4. Yürütme: `report` çalışması ve adımları

Yeni çalışma türü `report`. Ön koşul: en az bir dahil kaynak ve dahil kaynakların tamamını kapsayan bir kanıt tablosu (§9). Her adımın kendi `operation_key`'i vardır ve başarılı adım tekrar çağrılmaz. Adımlar bağımlılık sırasına göre turlarda yürür; bir turun adımları aynı anda gönderilir (§2 karar 7), bir tur bitmeden sonraki başlamaz.

0. Ön koşul denetimi ve **kanıt anlık görüntüsü** (kod, §4.2).
1. `report_plan` (model, §5). Girdisi plan değil; soru, kapsam, arama planı kavramları, tablo sütunları ve kaynak listesidir.
2. `research_title` (model; planın kapsam cümlesinden rapor başlığı, §15.1) ve II Review Methodology (kod).
3. **Tur A:** III, IV, V birlikte (model; yalnız plana ve kendi kanıtlarına bağlı).
4. **Tur B:** VI (model; V'in çelişkilerini ve IV'ün toplamlarını alır).
5. **Tur C:** VII (model; VI'nın adaylarını alır).
6. VIII Limitations (kod çekirdek + model cümleleri; VI'ya bağlı).
7. **Tur D:** I Introduction, IX Conclusion, Abstract ve Index Terms birlikte (model; üçü de yalnız gövde bölümlerinin iddia özetlerini alır, birbirini almaz).
8. Montaj ve denetim (kod, §8).
9. `report_review` (model; `answer_review`'ın rapor düzeyi karşılığı, §8).

Bir bölümün kalıp onarımı (§8) kendi turunun içinde, o bölümün adımı olarak yapılır; tur, onarımlar bitince kapanır.

**Özetleri kod üretir:** bir bölümün özeti, geçerli iddialarının `claim_key`'i, ilk cümlesi, destek türü ve en zayıf okuma derinliğidir; model özet yazmaz. Yalnız geçerli bölümlerin özetleri girdi olur (§2 karar 11).

**`report_plan` dışındaki her model adımının girdisi:** `StepInput` zarfı (`step_input_id`, `scope_revision`, `skill_package_hash`), dondurulmuş rapor planı, o bölüme kod tarafından seçilmiş kanıt kayıtları (pasajlar ve/veya hücreler, allowlist), önceki bölümlerin özetleri (iddia kimliği + bir satır; tam metin değil), phrasebank'in o bölüme ait kısmı ve bölüm şeması. Kanıt seçimi bölüme göre yapılır; 48 pasajlık yanıt girdisi her bölüme kopyalanmaz.

**Bölüm şeması** yanıt şemasının bölüm sürümüdür: `section_id` sabit; iddialar `claim_key` (kararlı, `IV.3` gibi), `text`, `support_type`, `passage_ids` ve/veya `cell_ids`, `citation_anchors`; ayrıca `paragraph` (okuma biçimi için, §9), `table_ref` / `equation_ref`, `body_refs` (Abstract, I ve IX'da: dayandığı gövde `claim_key`'leri), `axis_id` (IV alt başlıklarında), `count` (toplulaştırma cümlelerinde: pay ve payda üyelerinin kaynak kimlikleri ve sütun), `equation_origin` (denklem içeren iddiada: pasaj kimliği ve `text_source`), `gap_refs` (VI ve VII için), `subsections` (yalnız IV). `claim_key` ve `gap_id` bir rapor içinde benzersizdir ve bölüm yeniden yazılınca yeniden verilir; düzenleme sonrası kararlılık dilim 4'ün konusudur. Hücreye dayanan iddianın çapası hücrenin saklı alıntılarında aranır, pasaja dayananınki pasaj metninde; alıntı normalleştirmesi yanıttakiyle aynıdır. Tam sürümlü şemalar dilim 1 uygulama planında yazılır. Sınırlar bölüm başına 40 iddia ve bütçe kelime sayısı (planda). Aynı çapa kuralı: çapası pasajda bulunmayan iddia bölümü taslağa düşürür, D56'daki nihai kurtarma bölüm düzeyinde uygulanır.

**Model.** Bütün adımlar araştırmanın seçili modeliyle çalışır; bir bölümde model değişmez, uyuşmazlık `model_mismatch` olarak kaydedilir ve kullanılmaz. Çağrı sayısı adım grafiğinden: plan, başlık, III, IV, V, VI, VII, VIII, I, IX, abstract ve inceleme, yani 12; onarımlar hariç. Süre çağrı sayısına değil en uzun bağımlılık zincirine bağlıdır: plan → tur A → VI → VII → VIII → tur D → inceleme, yedi ardışık bekleme; D55'teki sürelerle (çağrı başına 1–3 dakika) kabaca 10–20 dakika, onarım ve kota beklemesi hariç. Tablo doldurma eş zamanlı hâliyle 50 kaynakta birkaç dakika. Bu tahminler ölçülmedi (§13 R7).

**Eş zamanlılık kuralları.** Bugünkü depolama kuralı değişmez: tek bağlantı, kısa eşzamansız olmayan işlemler, bir işlem içinde `await` yok; model çağrısı sürerken açık işlem bulunmaz. Yazmalar olay döngüsünde sırayla yapıldığı için ayrı bir yazıcı kuyruğu gerekmez. Üst sınır süreç genelinde tektir ve tablo doldurma ile rapor arasında paylaşılır; sınır 1 iken aynı hat aynı çıktıyı üretir (test). `_checkpoint` her gönderimden önce ve her sonuç yazılmadan önce çalışır:

- **Duraklatma:** yeni istek gönderilmez; uçuştaki isteklerin sonuçları normal kaydedilir; devamda kalanlar gönderilir.
- **İptal ve yeni kapsam revizyonu:** yeni istek gönderilmez; geç dönen sonuç kendi adım satırına eski revizyon etiketiyle kaydedilir ve kullanılmaz (T18); rapor yeni revizyonun raporu olarak gösterilmez.
- **Aynı anahtar:** bir `operation_key` için aynı anda tek uçuş; ikinci istek ilkini bekler.
- **Çökme:** başarılı adım saklı çıktısından döner. Yanıt alınıp kaydedilemeden çökülürse adım bugünkü kuralla `outcome_unknown` olur ve kendiliğinden yeniden çağrılmaz (`worker.py`); sahip yeniden dener. Bu, dış çağrının tam bir kez yapıldığı garantisi değildir; yalnız başarılı kayıt tekrar kullanılır.
- **Hata sınıfları:** kota/hız sınırı → sınır düşer, adım bekler ve en fazla iki kez yeniden gönderilir; ağ zaman aşımı gönderim öncesiyse yeniden denenir, sonrasıysa `outcome_unknown`; şema hatası → bugünkü sınırlı şema onarımı; içerik ihlali (çapa, kalıp, §6–§8 kuralları) → bölüm taslağı.

### 4.1 İstem ve yöntem paketi

Yeni bir skill eklenmez. Plan §4.1'deki karar geçerlidir: DEIXIS'in yüklediği tek paket `methods/deixis-research/`'tir; rapor bu pakete yeni bir referans dosyası ve yeni görev türleri olarak girer. İstemin kuruluşu bugünküyle aynıdır (`models/prompt.py`): sabit `BASE_INSTRUCTIONS` (araçsız, tek JSON, kaynak metni veridir) + geliştirici talimatı olarak o görev türünün yöntem dosyaları + kullanıcı mesajı olarak `StepInput` ve çıktı şeması. Ayrı bir "uygulama istemi" kopyası tutulmaz.

- **`references/report.md` (yeni).** Bölümleri: rapor planı; bölüm yazımı ortak kuralları (iddia, atıf, çapa, paragraf, denklem, terim sözlüğü, bütçe); bölüm başına kısa yönerge (III–VII, I, VIII, IX, abstract); tablo tartışma kuralları (§6); aday kuralları ve yasak sözcükler (§7); kalıp onarımı; rapor incelemesi. Yanıt talimatıyla ortak kurallar (çapa, LaTeX, okuma derinliği, `text_source`) kopyalanmaz; `source-grounded-answer.md`'nin ilgili maddelerine bağ verilir ve o dosya da yüklenir.
- **Görev türleri ve yüklenen dosyalar (`domain/skill.py::RUNTIME_FILES`).** `report_plan`, `report_section`, `report_phrase_repair`, `report_review`. `report_section` için: `SKILL.md`, `report.md`, `source-grounded-answer.md` ve kalıp bankasının o bölüme ait kısmı. Bölüm kimliği `StepInput`'ta gelir; model `report.md`'de kendi bölümünün yönergesini okur. Kalıp bankasının bölüme göre kesilmesi `phrasebank.render`'a bir bölüm süzgeci ekler: I için "Writing Introductions"; III için "Defining Terms", "Classifying and Listing"; IV için "Referring to Literature"; V için "Comparing and Contrasting", "Being Critical"; VI–VII için "Being Cautious", "Discussing Findings"; IX ve abstract için "Writing Conclusions"; "Signalling Transition" hepsine.
- **`SKILL.md` değişiklikleri.** Görev tablosuna dört yeni tür; "bu sürüm yalnız kaynaklı soru-cevabı destekler" paragrafı rapor için daraltılır: gap ve yön önerme yasağı `grounded_answer` için aynen kalır, `report_section`'ın VI ve VII bölümleri için §7'deki türler ve etiketle açılır. Kill-search, aday geliştirme ve deney tasarımı "yok" olarak kalır.
- **Sözleşmeler.** `contracts/research/` altına `report-plan`, `report-section-draft`, `report-phrase-repair`, `report-review` şemaları; `tests/fixtures/research/` ve `tests/fakes.py::valid_response` bunlarla güncellenir.
- **Paket hash'i.** Yeni dosyalar `skill_package_hash`'i değiştirir; eski yanıtlar eski hash'leriyle kalır (T13). `provenance.json`'a `report.md`'nin kaynağı yazılır: Quaestio'dan uyarlama değil, bu notun kurallarıdır.
- **Davranış vakaları.** `scripts/model_behavior/` altına rapor vakaları: `not_found` hücresini "incelemedi" diye yazma tuzağı, özet satırından yöntem ayrıntısı isteme, boş eksenden "gap" ilan etme, denklemi sözle geçiştirme, kaynak içi talimat. Dilim 1'de `gpt-5.6-luna` ile koşulur.

### 4.2 Durumlar ve kanıt anlık görüntüsü

Üç ayrı durum kümesi vardır ve birbirinin yerine kullanılmaz:

| Düzey | Durumlar | Geçiş |
|---|---|---|
| Çalışma (`runs`) | bugünkü durumlar: `queued`, `running`, `paused`, `succeeded`, `failed`, `cancelled`, `outcome_unknown` | Bir bölüm taslağa düşünce çalışma `paused` olur ve nedeni "bölüm yeniden yazılmalı"dır |
| Bölüm | `pending`, `running`, `valid`, `draft`, `failed` | `draft`: içerik denetimi geçmedi (çapa, kural, bütçe); `failed`: adım teknik olarak bitmedi. İkisi de bağımlıları durdurur; yeniden deneme yeni bir adım denemesidir |
| Rapor | `in_progress`, `valid`, `draft` | `valid`: bütün bölümler `valid` ve montaj temiz; o anda `report_version` alır. `report_review` bulguları durumu değiştirmez; rapora eklenir |

`valid` yapısal geçerliliktir; semantik doğrulama değildir ve inceleme modelinden geçmek de bu statüyü vermez. `stale` bir durum değil, ayrı bir işarettir.

**Kanıt anlık görüntüsü.** Çalışma başlarken kod raporun dayanacağı kanıtı sabitler: tablo ve sütun revizyonu, her hücrenin geçerli revizyonu (insan düzenlemeleri dahil), hücre alıntıları, dahil kaynakların sürüm kimlikleri ve okuma derinlikleri, `corpus` sayıları. Bölüm adımlarına giden her kayıt bu görüntüden gelir ve adım girdileri bugünkü gibi çağrıdan önce saklanır. Rapor görünümündeki ve dışa aktarımdaki TABLE I canlı tablodan değil bu görüntüden çizilir. Çalışma sürerken yapılan hücre düzenlemesi, `cell_recheck` ya da PDF yüklemesi süren raporu etkilemez. Görüntüden sonra tablo, hücre ya da kaynak değişmişse rapor görünümü tek bir bant gösterir: "Bu rapordan sonra kanıt değişti"; bölüm bölüm bayatlama işareti dilim 4'tedir.

### 4.3 Bölüm başına kanıt seçimi

Seçimi kod yapar ve kaydeder; allowlist yalnız izinli kimlikleri sınırlar, neyin verilmediğini söylemez. Her bölüm için:

| Bölüm | Uygun kayıtlar | Sıralama |
|---|---|---|
| III | sözlük terimlerinin tanım pasajları; eksenlerle ilgili en iyi pasajlar; görüntülenen denklem içeren pasajlar (formülasyon isteniyorsa önce) | bugünkü sözcük + anlam sıralaması (RRF), kaynak başına en az bir |
| IV | bütün satırların hücreleri ve alıntıları; satır başına en iyi iki pasaj | tablo sırası |
| V | eksen sütunlarının hücreleri; aynı sütunda farklı değer taşıyan satırların pasajları | sütun, sonra kaynak |
| VI | kodun hesapladığı yokluk toplamları (tam metinli satırlar), "sınırlamalar" sütunu hücreleri, V'in çelişki iddiaları | tür, sonra sütun |
| VII | VI'nın adayları ve dayanak kayıtları; "önerilen gelecek çalışma" hücreleri | aday sırası, sonra kaynak |

Her bölümün bir bağlam bütçesi vardır; bütçeye sığmayan kayıtlar **kesilme kaydına** yazılır (hangi kaynak, hangi kayıt türü) ve VIII'de sayı olarak görünür. Bir kaynaktan birkaç pasaj okumak "tam metni kapsamlı inceleme" değildir; okuma derinliği alanı bunu ayrı söyler. Gerekli kanıt yoksa (örneğin III için tanım pasajı olmayan terim) model bölümü doldurmaz; `insufficient_evidence` kaydı üretir ve bu kayıt raporda açık eksiklik olarak yazılır. Önemli bir karşı kanıtın bölüme hiç verilmemesi bu seçimle önlenemez; bilinen sınırdır (§14).

## 5. Rapor planı (`report_plan`)

Bölümler arası tutarlılığın tek kaynağı. Model bir kez üretir, kod sayıları doldurur, sonra dondurulur ve her bölüm adımına aynen verilir.

- `scope_statement`: tek paragraf, sorunun dilinde.
- `research_questions`: 2–5 soru, kimlikli (`RQ1`…).
- `glossary`: terim → tanım → tanımın geldiği pasaj. D44 kavram sözlüğünden farklıdır: o arama sözcükleridir ve kaynaksızdır, bu ise kaynaklı tanımlardır; index terms yalnız D44 listesinden seçilir. Kod, sözlük terimlerinin bölüm metinlerinde geçişini dize eşleşmesiyle sayar (§8).
- `axes`: sınıflandırma eksenleri, her biri bir kanıt tablosu sütununa bağlı; sütunda karşılığı olmayan eksen olmaz.
- `section_budgets`: bölüm başına kelime aralığı ve iddia üst sınırı. Kelime sayımı düzyazıyı sayar; tablo, kaynakça ve matematik aralıkları sayılmaz. Dahil kaynak sayısı $n < 10$ ise bütçeler $n/10$ ile çarpılır, alt sınır toplam 1200 kelime. Alt bütçeye kanıt yetmiyorsa bölüm kısa kalır; model metni uzatmaya zorlanmaz ve montaj yalnız üst sınırı hata sayar.
- `corpus`: kod doldurur ve anlık görüntüden gelir. Tanımlar: *bulunan* = başarılı sağlayıcı aramalarının döndürdüğü kayıt toplamı; *tekil* = DOI ve sürüm ailesi birleştirmesinden sonraki eser sayısı; *taranan* = tarama adımına giren aday sayısı; *dahil* = geçerli kapsam revizyonunda dahil edilmiş kaynak sayısı (sahibin düzeltmeleri dahil); *tam metinli* = dahil kaynaklardan PDF metni olanlar, paydası *dahil*. Başarısız aramalar ayrı sayılır. Rapor üretim istatistikleri (çağrı, onarım, istisna, kesilme) `corpus`'a girmez; VIII'de ayrı yazılır.
- `allowed_support`: bölüm başına izinli iddia türleri (VI yalnız `analyst_inference`; VII `analyst_inference` ve, kaynağın kendi önerdiği gelecek çalışma için, `source_stated`).

Plan model çıktısıdır ve şema denetiminden geçer; eksen–sütun bağı ve sözlük pasajları allowlist'ten denetlenir. Plan değişirse (sahip düzenlerse) sonraki bölümler yeniden yazılır, önceki bölümler `stale` işaretlenir (dilim 4).

## 6. Kanıt tablosu ve IV/V tartışma kuralları

Tablo P5'teki tablodur; bu not hücre şemasına yeni durum eklemez (dilim 1 karar 5: `not_found_in_inspected_scope` kuralı kalır). Okuma derinliği hücrede zaten ayrıdır ve tartışma adımına verilir.

Sütun önerisi (`table_columns`) rapor için çağrılırken talimata şu tercih eklenir: araştırma amacı, uygulama alanı, problem modeli, yöntem, veri/deney ortamı, karşılaştırıcılar, ölçütler, temel bulgu, yazarların belirttiği sınırlamalar, **yazarların önerdiği gelecek çalışma**, **ölçülmemiş varsayımlar**, **kanıt statüsü** ve sorunun sorduğu X/Y/Z kapsam sütunları. Bu liste sahibin [alan örneğindeki](../methods/domain-example.md) ayrıntı düzeyinden gelir; sütunlar alana uyarlanır, örneğin alanına kilitlenmez. Kanıt statüsü kapalı bir seçimdir: `demonstrated` (deney ya da ölçümle gösterilmiş), `modelled` (analitik model ya da simülasyon), `proposed` (öneri, değerlendirme yok), `inferred` (kaynağın yazmadığı, okuyanın çıkardığı); bir simülasyon gösterim sayılmaz. Hücre kuralı aynıdır: statü, alıntılanan pasajın söylediğine dayanır ve özet satırında çoğu zaman `not_found_in_inspected_scope` kalır. Sütun tanımları doldurmadan önce donar; sonradan sütun eklemek yeni doldurma demektir.

IV ve V adımlarının talimatına giren kurallar (ihlali `report_review` yakalar, montaj denetimi mümkün olanları kodla yakalar):

- `not_found_in_inspected_scope` hücresi "çalışma bunu incelemedi/ele almadı" diye yazılamaz. Tam metinli satır için "incelenen metinde bildirilmedi" denebilir. Yalnız özeti okunan satır için tek kaynak hakkında hiçbir yokluk cümlesi kurulmaz; o satır yalnız paydalı sayımda "yalnız özeti incelenen k çalışma değerlendirilemedi" diye geçer (§2 karar 10).
- Teknik hata ya da okunmamış kapsam yokluk değildir: doldurması başarısız hücre `not_found` sayılmaz, paydalara girmez.
- Olumsuz önerme ("X'i dikkate almaz") yalnız kaynak bunu açıkça dışladıysa ya da sınırlama olarak yazdıysa kurulur; o hücrenin alıntısı atıf olur.
- Her toplulaştırma payda verir: "tam metni incelenen 6 çalışmanın 4'ü"; özet hücreleri ile tam metin hücreleri aynı sayıma katılmaz. Model `count` alanında pay ve paydanın kaynak kimliklerini verir; kod üyelerin o sütunda o değeri ve o okuma derinliğini taşıdığını, tekil kaynak olduklarını ve cümledeki sayıların üye sayılarıyla aynı olduğunu denetler.
- Çelişki iddiası ancak aynı kavram, koşul ve ölçüt karşılaştırılabilirse kurulur; koşul farkı varsa "farklı koşullarda farklı sonuç" denir (T11).
- Hücreler arası boşluktan yöntem ya da sonuç çıkarımı yapılmaz.
- Kanıt statüsü karıştırılmaz: V'teki uzlaşı ve çelişki cümleleri statüyü söyler ("dört çalışma modelledi, biri deneyle gösterdi"); `modelled` bir sonuç `demonstrated` bir sonuçla aynı ağırlıkta çelişki ya da doğrulama sayılmaz.
- Tema alt başlıkları eksenlerden türetilir; her alt başlık bir `axis_id` taşır, eksende olmayan tema şema hatasıdır.
- Bu kurallar türetilmiş iddialara taşınır: Abstract, I ve IX'daki bir iddia, `body_refs` ile bağlandığı gövde iddialarının en zayıf okuma derinliğini ve destek türünü miras alır (kod hesaplar); gövdede "özet temelli" ya da "analist çıkarımı" olan bir şey özette kesin bulgu diye yazılamaz.

**Tablo hazır koşulu.** Rapor butonu şu koşulda açılır: her dahil kaynak × her sütun için hücre son durumdadır (değer, `not_found_in_inspected_scope`, `not_applicable` ya da insan düzenlemesi) **ya da** satır `failed` işaretlidir ve sahip "hatalı satırlarla devam et"i seçmiştir. Hatalı satırlar yeniden denenebilir; devam edilirse paydalara girmez ve VIII'de adlarıyla listelenir. Onay bekleyen model önerisi (insan düzenlemesinin üstüne gelen) son durum sayılır; geçerli olan insan değeridir. Sütun onayı en az üç sütun ister; daha dar tabloda panel uyarır ama engellemez.

## 7. Cevaplanmamış yön adayları (VI)

Her aday bir kayıttır, düzyazı değil. Üç tür. Kod yalnız yapıyı doğrular; anlamı `report_review` okur, o da kaçırabilir (§8 tablosu):

| Tür | Dayanak | Kodun doğruladığı yapı |
|---|---|---|
| `stated_limitation` | bir ya da daha çok kaynağın kendi yazdığı sınırlama | atıf çapası "sınırlamalar" hücresinde ya da pasajda bulunur; metnin gerçekten yazarın sınırlaması olduğunu kod bilemez |
| `conflicting_evidence` | V'te kurulmuş bir çelişki | V'teki iddia kimliğine bağ; çelişkinin gerçek ve koşulların karşılaştırılabilir olduğunu kod bilemez |
| `corpus_absence` | bir eksende tam metni incelenen kaynakların hiçbirinde bildirilmemiş olması | adayı kod üretir, model yalnız metnini yazar: sütunda tam metinli ve uygulanabilir (`not_applicable` olmayan) en az üç satır vardır ve hepsi `not_found_in_inspected_scope`'tur; özet satırları "değerlendirilemez" diye ayrı sayılır; `not_applicable` yokluk kanıtı değildir |

Etiket türe göre yazılır: `corpus_absence` için "tam metni incelenen N kaynakta bildirilmedi; k kaynak yalnız özetinden okundu ve değerlendirilemedi"; `stated_limitation` için "şu kaynakların kendi belirttiği sınırlama"; `conflicting_evidence` için "şu kaynaklar arasında uyuşmazlık". Üçü de "denetlenmemiş aday; kill-search yapılmadı" ibaresini taşır.

Her adayın kaydı: `gap_id`, tür, metin (analist çıkarımı), dayandığı hücre ve pasaj kimlikleri, en yakın kısmi eşleşme (üç durumdan biri: `found` + kaynak ve hücre, `none_in_corpus`, `not_searched`), ve kod tarafından eklenen kaynakça: arama tarihi, sağlayıcılar, sorgu sürümü, bulunan/dahil sayıları, tam metin oranı, `kill_search_status: not_run`. VII'deki her yön ya bir `gap_id`'ye ya da "önerilen gelecek çalışma" sütunundan bir hücreye bağlıdır; ikisine de bağlı olmayan yön şema hatasıdır. Kaynağın kendi önerisi `source_stated` yazılır ve kaynağa atfedilir; rapor onu kendi önerisi gibi sunmaz.

Sözcük kuralı: kill-search yapılmadan "gap", "open problem", "novel", "first" ve eşdeğerleri (iki dilde sabit bir liste) **başlık dahil raporun hiçbir yerinde** kullanılmaz; kod bu listeyi bütün metinde arar. VI ve VII'de "candidate unanswered aspect / cevaplanmamış yön adayı" kullanılır. Bu, `SKILL.md`'deki yasağın rapor için gevşetilmiş biçimidir: yasak yanıt için aynen kalır, rapor bölümleri VI ve VII için bu türlerle ve etiketle açılır.

## 8. Montaj denetimi ve rapor incelemesi

Montaj kod işidir ve model çağırmaz. Hata bulursa rapor `unverified_draft` olur ve hangi bölümün yeniden yazılacağını söyler:

- Aynı `claim_key` iki yerde (hata). Aynı metnin iki gövde bölümünde geçmesi uyarıdır; Abstract ve IX'un gövdeyi yinelemesi beklenen şeydir ve `body_refs` ile bağlıdır.
- Sözlük terimleri metinde dize eşleşmesiyle aranır: tanımı III'ten önce kullanılan terim uyarıdır. Eşanlamlı kullanımı ve kavramsal tutarlılığı kod bulamaz; `report_review` okur.
- Abstract, I ve IX'daki her iddia `body_refs` ile gövdede en az bir `claim_key`'e bağlanır; bağsız iddia hatadır. Bağın varlığı anlamın korunduğunu göstermez; o `report_review`'ın işidir.
- Türetilmiş iddia, bağlandığı gövde iddialarından daha güçlü bir destek türü ya da okuma derinliği taşıyamaz (kod hesaplar, §6).
- `count` alanları §6'daki gibi doğrulanır.
- Yasak sözcük listesi başlık dahil bütün metinde aranır (§7).
- II ve VIII'deki sayılar `corpus` ile birebir aynıdır (kod yazdığı için farkı model üretemez; model cümleleri sayı içeremez).
- Her atıf kaynakçada, kaynakçadaki her kayıt en az bir atıfta.
- VII'deki her yön bir `gap_id`'ye, VI'daki her aday §7'deki dayanağa bağlı.
- Toplam ve bölüm kelime sayısı plandaki bütçede.
- Matematik aralıkları iyi biçimli; görüntülenen her denklemin `equation_origin` pasajı girdide vardır ve o pasajda matematik aralığı bulunur; Marker/OCR kaynaklı ifadeler uyarı taşır. Sözdizimi denetimi aktarım doğruluğu değildir; o R6'da sayfayla ölçülür, matematiksel doğruluk hiç denetlenmez.

**Denklem kuralı.** Zorunluluk erişime değil gözleme bağlıdır: formülasyon isteyen raporda, bölümün girdisine giren pasajlarda görüntülenen denklemi olan bir kaynak denklemiyle anlatılır. Değişken, amaç ve kısıt düzeni yalnız pasajın verdiği parçalar için uygulanır; pasajda tanımı olmayan simge tamamlanmaz, "verilen pasajda tanımlanmamış" diye yazılır; farklı pasajlardaki parçalar tek formülasyon gibi birleştirilmez.

**Kalıp denetimi (bölüm düzeyinde, montajdan önce).** Bölümün her cümlesi bugünkü biçimsel denetimden geçer (`phrasebank.unframed`: bir kalıbın sabit sözcüklerinin en az %70'i sırayla). Uymayan cümle varsa bölümün adımı bir **hedefli onarım** çağrısı yapar: girdi uymayan cümleler (kararlı cümle kimliğiyle: `claim_key` + sıra), her biri için kod tarafından seçilmiş en yakın üç kalıp, cümlenin destek türü, alıntı çapaları ve önceki ile sonraki cümle; çıktı aynı kimliklerle yeniden yazılmış cümleler. Talimat anlamı, niteleyicileri (may, some, in the inspected text), olumsuzluğu ve sayıları korumayı ister. Onarım bölümün geri kalanına dokunmaz; atıf ve çapalar değişmez; kod sayıların, matematik aralıklarının ve atıfların önce/sonra aynı kaldığını denetler; önce ve sonra metni saklanır. Onarım en fazla bir kez. Onarılan cümleler `report_review`'a işaretli gider ve her biri destek açısından yeniden okunur. İnceleme "destek bozuldu" derse özgün cümle geri konur ve **incelenmiş istisna** olur (§2 karar 12). Onarımdan sonra hâlâ uymayan cümle de istisna olur; bölüm bu yüzden taslağa düşmez. İstisnalar kanıt görünümünde listelenir, VIII'de sayılır ve R8'de ölçülür. Kod anlam kaymasını göremez; inceleme de kaçırabilir. `own_work_phrase_in_claim` ve `plural_sources_for_one_source` aynı yolu izler, ama istisna olamaz: onarımdan sonra kalırsa bölüm taslağa düşer, çünkü bunlar biçim değil atıf yanlışıdır. Yanıt adımındaki uyarı düzeyi (D19) değişmez; bu kural yalnız rapor bölümleri içindir.

`report_review` bir model adımıdır: bölümlerin iddialarını alıntılanan pasaj ve hücrelere karşı okur, §6 kurallarını, onarılan cümleleri ve abstract–gövde tutarlılığını denetler, `answer_review` gibi bulgu listesi verir ve ana metne yazmaz; tek istisna, destek bozan onarımın geri alınmasıdır, onu da kod yapar. Bağlam sığmazsa inceleme bölüm bölüm yapılır (her çağrı bir bölüm ve onun kanıtı), abstract–gövde denetimi ayrı bir çağrıdır. İnceleme başarısız olursa rapor geçerliliğini korur, "incelenmedi" diye işaretlenir. İncelemenin yakalama oranı bilinmiyor; §13'te ekilmiş hatalarla ölçülür.

**Kim neyi doğrular:**

| Kural | Kodun doğruladığı yapı | Modelin değerlendirdiği anlam | Doğrulanmayan |
|---|---|---|---|
| Atıf ve çapa | çapa pasajda ya da hücre alıntısında birebir var | alıntı iddiayı destekliyor mu | bağlamın doğru aktarıldığı |
| Sayım cümleleri | üyeler, derinlik, sayılar | — | sütun değerinin kendisinin doğruluğu (R2, M5) |
| Yokluk | tam metinli ≥ 3 satır, hepsi `not_found`, `not_applicable` hariç | aday metni yokluğu abartıyor mu | korpus dışında var olup olmadığı (kill-search) |
| Çelişki | V iddiasına bağ | koşullar karşılaştırılabilir mi | — |
| Türetilmiş iddia | `body_refs`, miras alınan derinlik | anlam gövdeyle aynı mı | — |
| Terimler | sözlük terimlerinin geçişi | eşanlamlı ve tutarlılık | — |
| Denklem | köken pasajı, iyi biçim | pasajdaki ifadeyle aynı mı | matematiksel doğruluk |
| Kalıp | %70 sabit sözcük; onarımda sayı/atıf/matematik değişmedi | onarım anlamı korudu mu | kalıbın anlama uygunluğu |
| Yasak sözcükler | liste eşleşmesi | listede olmayan yenilik iması | — |

## 9. Arayüz ve dışa aktarma

- **PDF hazırlığı paneli, 4. durum "Tablo dolduruluyor".** Sütun önerisi kartı (onayla / düzenle), parti ilerlemesi ("25 / 52 kaynak okundu, 2. parti sürüyor"), tamamlanınca "Write report" birincil buton. "Generate source-linked answer" bugünkü yerinde kalır ve tablo istemez. Yükleme yapılmadan devam edilebilir; özet temelli satırlar tabloda ve raporda öyle görünür.
- **Okuma biçimi (§2 karar 9).** Bölüm şemasındaki her iddia bir `paragraph` sıra numarası taşır; kod aynı paragraftaki iddiaları sırayla birleştirip tek paragraf yapar, böylece metin cümle cümle kartlara bölünmez. Atıflar kodla numaralanır: bir kaynağın numarası raporda ilk geçtiği yere göre verilir ve kaynakçadaki sırayla aynıdır; aynı cümledeki birden çok kaynak `[2], [5]` diye yazılır. Tablo "TABLE I", görüntülenen denklemler `(1)`, `(2)` diye kodla numaralanır; model metinde numara yazmaz, `table_ref` ve `equation_ref` alanlarıyla işaret eder ve kod numarayı yerine koyar. Analist çıkarımı olan cümleler okuma görünümünde de ayırt edilir, ama etiketle değil dille: kalıp bankasının temkinli ifade kalıplarıyla yazılır (§8) ve kanıt görünümünde işaretlenir. VI'daki adayların "denetlenmemiş aday" ibaresi ve II/VIII'deki korpus sayıları okuma görünümünde de metnin parçasıdır; gizlenmez.
- **Rapor görünümü.** Bölümler sırayla, iddialar bugünkü atıf çipleriyle (`citations.tsx`), IV'te tablo `EvidenceTable.tsx` ile gömülü, VI'daki adaylar tür ve "kill-search yapılmadı" rozetiyle. Taslağa düşen bölüm kırmızı değil, "bu bölüm yeniden yazılmalı" satırıyla gösterilir; diğer bölümler okunabilir kalır.
- **Dışa aktarma.** Dilim 1: Markdown (tablo Markdown tablosu, denklemler `$…$`, kaynakça numaralı). Dilim 2: IEEEtran LaTeX (`\cite{}` anahtarları `source_key`'den, tablo `table*`, denklemler değişmeden). İki çıktı da "DEIXIS ile üretildi; korpus: … sayıları" satırını II'den alır.
- **Zaman çizelgesi.** `report` çalışması bugünkü çalışma satırlarıyla görünür: her bölüm bir adım satırı ("III yazıldı · 12 iddia · 9 kaynak"), montaj ve inceleme ayrı satır.

## 10. Veri modeli taslağı

SQL'in geçerli hali migration dosyası olur; bu taslak niyettir.

- `runs.kind` listesine `report`.
- `reports(id, research_id, run_id, scope_revision, status, language, plan_json, report_version, created_at)`; `report_version` yanıttaki gibi yalnız geçerli raporlarda sayılır.
- `report_sections(id, report_id, section_id, step_id, status, draft_json, validation_json, word_count, order)`; iddialar ve çapalar yanıttaki `claims` tablosunun aynı yapısıyla, `section_id` ile.
- `report_gaps(id, report_id, gap_id, kind, text, basis_json, provenance_json, kill_search_status)`.
- `report_snapshot(report_id, table_id, table_revision, snapshot_json)`: §4.2'deki kanıt anlık görüntüsü; görünüm ve dışa aktarım bunu kullanır. Görüntüden sonraki değişiklik bandı bununla hesaplanır; bölüm düzeyi `stale` dilim 4'te.
- `report_phrase_repairs(report_id, section_id, sentence_id, before, after, outcome)`; `outcome`: `kept`, `reverted_exception`, `unframed_exception`.
- `report_section_inputs`: yeni tablo değil; bugünkü `step_inputs` kaydı kesilme kaydını da taşır.

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

### 11.1 Astra incelemesi (17 Eylül 2026)

`gpt-6-astra`, effort medium, Codex üzerinden, araçsız; §4.1 ve okuma biçimi eklenmeden önceki sürümü okudu, kodu görmedi. 21 talep verdi (16 MUST). Sonuç:

| Talep | Karar |
|---|---|
| 1 II/VIII kod çekirdeği ve aday kaynakçası dilim 1'e | Alındı (§12) |
| 2 Değişmez kanıt görüntüsü; değişiklik işareti | Alındı (§4.2); bölüm düzeyi bayatlama dilim 4'te kaldı |
| 3 Çalışma/bölüm/rapor durumları ayrı | Alındı (§4.2) |
| 4 Eş zamanlılıkta duraklatma, iptal, revizyon | Alındı (§4); ayrı yazıcı kuyruğu gerekmedi, tek bağlantı kuralı yetiyor |
| 5 `operation_key` sözleşmesi, hata sınıfları | Alındı kısa hâliyle (§4); kodda var olan `outcome_unknown` kuralına bağlandı |
| 6 Tablo hazır koşulu | Alındı (§6) |
| 7 Şema alanları | Alanlar alındı (§4); tam sürümlü şemalar uygulama planına |
| 8 Adım grafiği çelişkileri | Alındı (§3, §4) |
| 9 Kanıt seçimi sözleşmesi | Alındı (§4.3); karşı kanıt garantisi verilemiyor, sınır olarak yazıldı |
| 10 Phrasebank çelişkisi ve onarımda anlam kayması | Alındı (§8, §14); sahip karar 12'yi verdi |
| 11 Yapı ile anlamı ayır | Alındı (§8 tablosu) |
| 12 Yokluk ve özet kuralları | Alındı; sahip karar 10'u verdi (§6, §7) |
| 13 Dürüstlük kuralları bütün rapora | Alındı (§6, §7, §8) |
| 14 Denklem zorunluluğu gözleme bağlı | Alındı (§8, R9) |
| 15 Deterministik tanımlar | Alındı (§5) |
| 16 Kod denetimlerinin kapsamı | Alındı (§8) |
| 17–18 Metrik tanımları | Alındı (§13) |
| 19 Ekilmiş hata vakaları, ilk ölçüm dilim 1'de | Alındı (§13); ilk ölçüm zaten dilim 1'deydi |
| 20 Çağrı ve süre hesabı | Alındı (§4) |
| 21 Eş zamanlılığı ve kalıp onarımını ertele | Alınmadı: ikisi de sahibin kararı. "Sınır 1 iken aynı hat" testi alındı |

## 12. Dilimler

0. **Eş zamanlı tablo doldurma (dilim 1'den önce, rapordan bağımsız).** `_table_fill` kaynak çağrılarını üst sınırlı eş zamanlı gönderir; kota hatasında sınır düşer; her kaynak adımı bugünkü gibi kendi kaydını yazar. Test: sahte adaptörle 12 kaynaklı doldurmada aynı anda açık çağrı sayısı sınırı aşmaz, bir kaynağın hatası diğerlerini durdurmaz, çıktı sıralı hâlle aynı. Ölçüm: D55'teki doldurma ile aynı kopyada süre karşılaştırması (506–576 s başlangıç).
1. **Rapor çalışması.** `report` türü, kanıt anlık görüntüsü, `report_plan`, bölüm adımları ve şemaları, II ve VIII'in kod çekirdeği, aday kayıtları ve kaynakçaları, phrasebank bölüm yükleme ve hedefli onarım, montaj denetimi, `report_review`, durumlar, tablo hazır koşulu ve hazırlık panelinde tablo doldurma durumu, okuma biçimli rapor görünümü, değişiklik bandı, Markdown dışa aktarma. Kesinti testleri: kota hatası, çökme, iptal, kapsam değişimi ve geç sonuç. Sentetik testler: fixture'lara bölüm girdileri ve sahte çıktılar; montaj denetiminin her kuralı için bir test. Gerçek modelle bir rapor `gpt-5.6-luna` ile yazılır ve §13'teki beklentilerle karşılaştırılır.
2. **LaTeX.** IEEEtran dışa aktarımı, `source_key` tabanlı `\cite`, KaTeX ile IEEEtran arasında farklı davranan makroların denetimi.
3. **Kill-search ve aday kartı.** Ayrı not; VI'daki adaylara durum verir.
4. **Düzenleme, bayatlama, kapanış ölçümü.** Bölüm düzenleme (T09), bölüm düzeyinde `stale`, düzenleme sonrası kimlik kararlılığı, tutulmuş soruyla kapanış ölçümü.

Ertelenen, dilim 2'den sonra ayrı madde: **alan tabanı** (alan örneğinin Task 1'i). III'e "kurucu makale, en önemli derleme, en yakın birincil çalışmalar" alt başlığı; her seçim neye dayandığını söyler (atıf sayısı, kurucu etki, derlemelerde anılma sıklığı ya da doğrudan ilgi) ve "en ünlü" nesnel bir olgu gibi yazılmaz. Sağlayıcı kayıtlarındaki atıf sayısının kaynağıyla ve tarihiyle saklanmasını ister; bugün rapor girdisinde yok.

Yöntem dayanağı: dilim 3'ün notu [research-methods.md](../methods/research-methods.md) §4'ten çıkar (aday kartı, iddia–pasaj matrisi, örtüşme/geçerlilik/değer ayrımı, elenen adayın sürümlenmesi); oradaki değerlendirme tablosundan R10'a iki ekilmiş hata daha alınır: aynı sonucun başka terminolojiyle zaten var olması ve atıf var diye gelişim ilişkisi kurulması.

Ayrı iş, bu notun dışında: **PDF edinme** (D55 M3 = 0/7 ve 0/5) için tasarım notu. Raporun kalitesi ona bağlıdır; bu not onu çözmez, yalnız sayıyı görünür kılar.

## 13. Ölçüm beklentileri (dilim 1'den önce dondurulur)

P5 dilim 5'teki kural: beklenti koşudan önce yazılır ve commit'lenir; sonuç sonradan yorumlanıp beklentiye uydurulmaz. Sayısal aralıklar bu notta değil, koşudan önce ayrı bir dosyada donar. Ölçülecekler:

| # | Ne | Payda ve tanım |
|---|---|---|
| R1 | Bölüm geçerliliği | ilk denemede geçerli bölüm / yazılan bölüm; onarım ya da yeniden denemeden sonra geçerli / yazılan; ayrıca tamamlanmış (`valid`) rapor / başlatılan rapor |
| R2 | Yanlış atıf | sabit tohumla, bölüm × destek türü × okuma derinliği katmanlarından çekilen 30 iddia; birim iddia–kayıt bağı; karar: destekler / kısmen / desteklemez. Sıfır hata, korpus genelinde hatasızlık diye yorumlanmaz |
| R3 | Yokluğun abartılması | inceleyenin raporu okuyup işaretlediği bütün olumsuz ve yokluk cümleleri; her biri dayandığı hücrelere karşı: kurala uygun / uygunsuz |
| R4 | Türetilmiş iddia | (a) yapısal: `body_refs`'i olmayan iddia (montaj yakalamalı, beklenen 0); (b) anlamsal taşma: Abstract, I, IX iddialarından gövdeden güçlü yazılanlar / o bölümlerin bütün iddiaları |
| R5 | Terim tutarsızlığı | sözlük terimi başına: metinde başka adla anıldığı yer sayısı; payda sözlük terimleri |
| R6 | Denklem aktarımı | görüntülenen denklem başına PDF sayfasıyla karşılaştırma; hata türleri: simge, indis, operatör, koşul/aralık, eksik parça. Eşdeğer LaTeX yazımı hata değildir |
| R7 | Süre ve maliyet | uçtan uca süre; ardışık zincirin süresi; kuyruk ve kota beklemesi; çağrı ve token sayısı (onarım ve başarısız denemeler ayrı) |
| R8 | Kalıp | özgün cümle kimlikleri üzerinden: ilk denemede uymayan / bütün cümleler; onarımdan sonra uyan; `reverted_exception` ve `unframed_exception` sayıları |
| R9 | Denklem kapsamı | koşudan önce işaretlenen (kaynak, formülasyon) çiftleri: girdide görüntülenen denklemi olan kaynaklar; her çift için raporda var mı ve pasajın verdiği parçalar (değişken, amaç, kısıt) eksiksiz mi |
| R10 | İncelemenin yakalama oranı | geçerli bir rapora bilerek ekilen 12–14 hata (anlamı değişmiş onarım, özetten yöntem ayrıntısı, yanlış payda, karşılaştırılamaz koşullardan çelişki, dayanaksız aday, yenilik iması, simülasyonun gösterim diye yazılması, atıf var diye gelişim ilişkisi kurulması); `report_review`'ın yakaladığı / ekilen; montajın yakaladığı ayrı |
| R11 | Sessiz eksik kanıt | kesilme kaydındaki kayıt sayısı ve `insufficient_evidence` sayısı; inceleyenin "bölümde olması gerekirdi" dediği, girdiye hiç verilmemiş pasaj sayısı |

Payda sıfırsa metrik "ölçülemedi" diye yazılır, 0 ya da 1 diye değil. Yarıda kalan çalışma R1 ve R7'ye girer, diğerlerine girmez. Davranış vakaları (§4.1) ve R10'un ekilmiş hataları etiketli vaka kümesidir ve dilim 1'de koşulur.

Sahibin okuma değerlendirmesi ayrı raporlanır; Claude'un okuması "insan denetimi" sayılmaz.

## 14. Varsayımlar ve sınırlar

- Rapor, korpusun kapsamını iyileştirmez; D55'teki geri çağırım ve PDF edinme sorunları rapora aynen yansır ve II/VIII'de görünür.
- Phrasebank uyumu güvenilirlik ölçütü değildir. Rapor bölümlerinde kural sıkıdır (§2 karar 8 ve 12), ama biçimseldir; yanıt adımında uyarı düzeyinde kalır (D19).
- Kod yalnız yapıyı doğrular (§8 tablosu); `report_review` bir modeldir, kaçırabilir ve yakalama oranı ölçülmeden bilinmez.
- Kanıt seçimi önemli bir karşı kanıtı bölüme hiç vermeyebilir; kesilme kaydı bunu görünür kılar, önlemez.
- Bölüm başına adım tutarlılığı garanti etmez; plan, özetler ve montaj denetimi bunu azaltır, `report_review` kalanın bir kısmını bulabilir. Ölçülmedi.
- Tablo doldurma ve rapor birlikte 50 kaynaklı bir araştırmada bir saate yaklaşabilir; süre ölçülmedi.
- Bir bölüm "structurally valid" olsa da semantik doğrulama değildir; T01'deki kural rapor için de geçerlidir.

## 15. Sahibe sorulanlar (17 Eylül 2026'da yanıtlandı)

Sahip üç soruda da ilk seçeneği seçti.

1. **Rapor başlığı.** `research_title` adımı rapor planındaki kapsam cümlesinden raporun başlığını da yazar; yanıttaki başlık kuralları geçerlidir; sahip görünümde düzenler. (Başlığı sahibin başlatırken girmesi reddedildi.)
2. **Bölüm bütçeleri.** Sabit varsayılan: toplam 4000–7000 kelime, en geniş pay IV'e, sonra III ve V'e. Rapor planı bütçeyi bölümlere dağıtır; dahil kaynak 10'dan azsa orantılı küçültür; montaj denetimi aşımı yakalar. (Kısa/orta/uzun ön ayarları reddedildi.)
3. **Özet temelli satırlar.** Tabloda "özet" rozetiyle kalır ve tartışmaya girer; sayımlar ayrı paydayla yazılır ("tam metni incelenen 17 çalışmanın 11'i…, yalnız özeti incelenen 6 çalışmanın 2'si…"). Özet satırından yöntem ayrıntısı, denklem ya da "bildirmedi" çıkarımı yapılmaz (§6). (Yalnız tam metinli kaynakları tartışmak reddedildi: bugünkü PDF edinme oranıyla rapor çok az kaynağa dayanırdı.)

Astra incelemesinden sonra üç soru daha soruldu; sahip üçünde de ilk seçeneği seçti. Kararlar §2'de 10, 11 ve 12 numaradır: yokluk adayı yalnız tam metinli satırlardan ve en az üç satırla; taslak bölüm bağımlılarını durdurur ve sürüm numarası yalnız tam geçerli rapora verilir; anlamı bozan kalıp onarımı geri alınır ve özgün cümle incelenmiş istisna olarak kalır.

§15.3 ile §6 arasındaki eski çelişki karar 10 ile kapandı: özet satırından tek kaynak hakkında yokluk cümlesi kurulmaz; "yalnız özeti incelenen k çalışma değerlendirilemedi" sayım cümlesi serbesttir.
