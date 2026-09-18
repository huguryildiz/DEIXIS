# P6 dilim 1 — yürütme devir kaydı

Tarih: 17 Eylül 2026, 18 Eylül'de güncellendi. Bu dosya yeni bir tasarım getirmez; satır düzeyindeki plan
[p6-slice1-report-run.md](p6-slice1-report-run.md)'dedir ve tek doğru kaynak odur. Buradaki iş, o planın
**neresinde olduğumuzu**, hangi sırayla devam edeceğimizi ve nelerin bilerek ertelendiğini kaydetmektir.

Yürütme biçimi: kodu `gpt-5.6-sol` (Codex) yazar, denetleyen oturum planla karşılaştırır, `pytest`'i koşar,
commit'ler ve push'lar. Codex'in kum havuzu `.git/index.lock`'a yazamıyor, bu yüzden commit'i her zaman
denetleyen atar.

## Nerede duruyoruz

`main` üzerinde, `5d6189b`'den sonraki commit'ler dilim 1'e aittir; son üçü `3d00bff`, `a374189` ve `a7bce6a`.
Uygulanmış olanlar:

| Plan | Ne geldi | Durum |
|---|---|---|
| 1a | Dört sözleşme, `report_target`, yöntem paketi, fake'ler, fixture'lar | Tam |
| 1b | Migration 0035, `ReportStore`, `build_snapshot`, `report_ready` | Tam |
| 1c Task 1–2 | `selection.py`, `plan.py` | Tam |
| 1c Task 3 | `sections.py::run_report`/`_run_section`, `flow.py`'ye `report` dalı | Tam (P2) |
| 1d Task 1–2 | Phrasebank bölüm süzgeci, `nearest_frames` | Tam |
| 1d Task 3 (yarım) | `flagged_sentences` | `repair_section` ertelendi (P8) |
| — | `report_target` tesisatı: `flow._step_input`/`_model_step` + izin listesi anahtarları | Tam (plan dışı, zorunluydu) |
| 1e Task 0 | Migration 0036: `report_sections` artık `'II'` kabul ediyor | Tam (plan dışı, zorunluydu) |
| 1e Task 1 | `review_methodology.py` — II. bölüm, model çağrısı yok | Tam |
| 1e Task 3 | `gaps.py` — `corpus_absence` adayları | Tam |
| 1e Task 4 (yarım) | `assembly.py`, kural 1, 2, 3, 4, 7, 10 | Tam (P1); kalan sekizi P7 |
| 1g | `request_report`, üç rapor rotası, `report_view`, `reportRuns` | Tam (P3) |
| — | **P3.5 plan pasajı düzeltmesi**: özeti olmayan kaynak ilk `pdf_page`'ini veriyor | Tam (plan dışı, zorunluydu) |
| — | **P2.5 kök neden turu**: plan adımı kanıt tablosunun sütunlarını ve özet pasajları görüyor; plana `limitations_column_id`/`future_work_column_id`; boş bölüm artık `valid` değil | Tam (plan dışı, zorunluydu) |

Tam backend takımı son ölçümde **664 geçti, 1 kaldı**. Kalan test
`tests/test_documents.py::test_extraction_is_stopped_when_it_exceeds_the_memory_limit`; `main` üzerinde bu işle
ilgisiz bir nedenle bozuk ("extraction timed out" diyor) ve bırakılmasına izin verilen tek başarısızlıktır.

**Rapor artık sahte modelle uçtan uca koşuyor** ve 11 bölümün 11'i de dolu geliyor (II'nin iddiası yok, çünkü
kod onu düz metin olarak yazar). Ama **gerçek modelle hiç koşulmadı**: bütün metin `FakeAdapter`'dan gelir ve
SYNTHETIC etiketlidir. Testler yapısal davranışı gösterir, rapor kalitesi hakkında hiçbir şey söylemez.

## P2.5 neden gerekti (tekrar etmemek için)

P2 bittiğinde sahte modelle koşulan ilk rapor, **11 bölümden sekizi bomboş** olduğu hâlde `valid` bitti. Zincir
şuydu: `report_plan` adımına hiç pasaj ve hiç sütun verilmiyordu (planın kendi taslağı da vermiyor), izin
listesi boş kalıyordu, `_check_report_plan` izin listesinde olmayan her sözlük pasajını ve her eksen sütununu
reddettiği için model **yasal olarak** tek bir sözlük terimi ya da eksen üretemiyordu; `selection.py` arama
sorgusunu sözlük+eksenden kurduğu için V hiç kanıt almıyordu; VI ve VII `plan["limitations_column_id"]` /
`plan["future_work_column_id"]` okuyordu ama o alanlar şemada hiç yoktu; ve montajda "bölüm boş olamaz" diye bir
kural olmadığı için sonuç sessizce geçerli sayılıyordu.

Buradan çıkan ders: **bir modelin bir alanı doldurabilmesi için izin listesinin o alanı taşıması gerekir.** Yeni
bir çıktı alanı eklerken `_step_input`'un izin listesini de beslediğinden emin ol, yoksa alan doğuştan ölüdür.

## Bu oturumda karara bağlananlar (planda yoktu)

1. **Hücre atıflarının `anchor_match`'i.** Migration 0035 yalnız `exact`/`normalized`/`fuzzy` kabul ediyor,
   sütun nullable. Hücre alıntısı da `contracts.locate_anchor` ile dondurulmuş anlık görüntüdeki saklı alıntıya
   karşı eşlenir; eşleşme yoksa `NULL` yazılır. Bunu hataya çevirmek montaj kuralı 12'nin işi (P7).
2. **`report_gaps.provenance_json`** hiçbir yerde tanımlı değildi ama sütun `NOT NULL`:
   `{"origin": "code"|"model", "section_id": "VI", "step_input_id": ...}`. `origin`, boşluğun kodun ürettiği
   `corpus_absence` adaylarından mı yoksa modelin kendi bulduğu bir boşluk mu olduğunu kaydeder.
3. **`freeze_plan` model zarfını düşürür.** `report_plan` çıktısı `schema_version`, `step_input_id`,
   `scope_revision`, `skill_package_hash` taşıyor; `report_target.plan` şeması `additionalProperties: false`.
   Dondurulmuş plan kodun sahibi olduğu bir nesne, model yanıtının zarfı ona ait değil.
4. **Kesilme kaydının yeri:** `select_evidence(...)["truncated"]`, bölümün `validation_json`'ına
   `{"ok", "issues", "truncated"}` olarak yazılır. Migration eklenmedi.
5. **`report_plan` çıktısı v1 → v2.** İki yeni zorunlu alan eklendi. Hiç rapor koşulmadığı için saklı v1
   çıktısı yok; yerinde yükseltildi, ayrı bir v1 dosyası tutulmadı. Yöntem paketi değiştiği için
   `skill_package_hash` de değişti.
6. **`Store.create_run`'ın stage eşlemesine `{"report": "synthesis"}` eklenmedi.** O tur `store.py` başka bir
   işin altındaydı; rapor koşusu şimdilik `extraction` stage'iyle duruyor. Tek satırlık iş, P3 ya da sonrası.

## Bilinen zayıflık: bölüm başarısızlığının nedeni kayboluyor

`_run_section` model adımını `optional=True` ile çağırır, böylece bir tur bitmeden hiçbir bölüm koşuyu
duraklatmaz (aksi hâlde uçuştaki kardeş çağrılar duraklamış bir koşuya yazmaya devam ederdi). Bedeli: model
bağlantısı düştüğünde ya da bütçe bittiğinde koşunun `pause_reason`'ı `section_failed` olur, gerçek neden yalnız
o bölümün `validation_json`'ında kalır. **P13 (1k kesinti testleri) tam olarak bunu sınayacak; orada yeniden ele
alınmalı.**

## Sıra neden değişti

Planın kendi sırası (1a → 1n) yürütülebilir değil: 1c Task 3'ün `run_report`'u 1d, 1e ve 1f'in işlevlerini
çağırıyor, 1d Task 3 `_model_step`'in `report_target` taşımasını bekliyordu, 1e Task 4 ise rapor hiç koşmadan
14 kuralı denetliyor. Bu yüzden **model çağırmayan saf parçalar önce**, orkestrasyon sonra yazıldı.

Bundan sonraki sıranın tek ölçütü şu: **en kısa yoldan çalışan bir rapora ulaşmak.** Arayüz, dışa aktarma ve
kalan denetimler, çıkan ilk gerçek rapora bakılarak önceliklendirilecek; şu an hangisinin önemli olduğu
tahmin edilerek yazılıyor.

## Partiler

Her parti bir Codex turu. Ön koşulu olmayan partiler sıradan bağımsız yapılabilir.

**P1 — Montaj kuralları, ilk yarı.** ✅ `d645f3a`.

**P2 — Orkestrasyon.** ✅ `b13546b`. 1f'in `run_report_review`'ı ve 1d'nin `repair_section`'ı hiç çağrılmıyor;
montaj yalnız P1'in altı kuralını koşar.

**P2.5 — Kök neden turu.** ✅ `7b4dfff`. Yukarıdaki "P2.5 neden gerekti" bölümüne bak.

**P3 — API ve görünüm modelleri.** ✅ `3d00bff`. `ReportStore.request_report`,
`POST /api/researches/{id}/reports` (202, gövde `{"table_id"}`, `Idempotency-Key`, sonunda `worker.wake()`),
`GET .../reports/{id}`, `GET .../reports`, `views.py`'de `report_view` + `research_view`'a `reportRuns`.
İstem: `docs/product/p6-slice1-p3-prompt.md`. Planla üç fark: hazır olmayan tablo **409** döndürüyor (plan 422
diyordu, `RevisionConflict` handler'ı 409 üretiyor); `create_report` var olan bir rapor koşusu istediği için
sıra "run yarat → rapor yarat → `update_run` ile target'a `report_id` yaz" oldu, üçü tek transaction'da;
`tests/test_views.py` yok, görünüm testleri `tests/test_report_api.py`'de. `apps/web/src/api.ts` tipi
bilerek atlandı, arayüz partisine kaldı.
**Adlandırma tuzağı:** `research_view` bugün *cevaplar* üzerinde `report_version`/`report_title` yayınlıyor ve
arayüzün Artifacts sekmesi `view.answers`'tan türeyen yerel bir `reports` değişkeni kullanıyor. Bunlar kaynak
bağlantılı cevaplar, bu dilimin raporu değil. Mevcut cevap tarafı adlandırması **değiştirilmedi**; eklenen şey
ayrı bir `reportRuns` listesidir.

**P3.5 — Plan adımının pasaj boşluğu (plan dışı, zorunluydu).** ✅ `a374189`. `sections.py` plan adımına yalnız
`kind='abstract'` pasajları veriyordu; ekli PDF'le kurulan bir araştırmada hiç abstract yok, izin listesi boş
kalıyordu — P2.5'in kök nedeninin aynısı, başka kılıkta. Yeni kural: kaynak başına bir pasaj, özeti varsa özet,
yoksa ilk `pdf_page`, liste `budget["max_answer_passages"]` ile sınırlı. İki test bunu saklanan `StepInput`
üzerinden denetliyor. P3 testindeki sentetik abstract koltuk değneği kaldırıldı; yüklenen PDF tek başına
raporu tamamlıyor. İstem: `docs/product/p6-slice1-p35-prompt.md`.

**P4 — Sahte modelle API üzerinden uçtan uca koşu.** ✅ `a7bce6a`. Planın adıyla belirttiği
`test_report_run_completes_with_fake_adapter_and_produces_a_valid_report`, `tests/test_report_api.py`'de
(rota yardımcıları orada). Rotalar üzerinden: 202 → worker → `completed` → `GET .../reports/{id}` `valid`,
`report_version 1`, on bir bölüm, her bölümün taslağı dolu, III–VII atıf taşıyor, II'nin iddiası yok (kod
yazıyor). **Planın test taslağı eskimiş:** on bölüm ve tur sırası bekliyordu, gerçek çıktı on bir bölüm ve
ordinal sıra.

**P5 planı (koşulmadan önce yazılmıştı).** `gpt-5.6-luna`, küçük bir araştırma, kütüphanenin **kopyası** üzerinde,
8799 portunda; canlı 8765 servisine asla dokunulmaz. Sahibin onayı gerekir. Aynı koşuda dilim 0'ın hiç
yapılmamış süre ölçümü (`scripts/p6_eval/measure_fill.py`) de halledilir.

**P5 — Gerçek modelle ilk koşu. ✅ koşuldu, ❌ tamamlanmadı.** 18 Eylül, kütüphanenin `sqlite3 .backup`
kopyası üzerinde, 8799 portunda; canlı 8765 servisine dokunulmadı. Araştırma: "Moleküler Haberleşmede Yöneylem
Araştırması", 3 dahil kaynak, 7 sütunlu hazır tablo, `codex` + `gpt-5.6-luna`, efor `standard`.
Koşu `run_embUJviBM9urKW1UbZL9`, rapor `rpt_rT4aAdRIknsa7MUMbrIK`.

**Sonuç: A turundan sonra `section_must_be_rewritten` ile duraklıyor.** 88 saniyede 4 model çağrısı (plan 22 s;
III/IV/V eş zamanlı, 39/53/59 s — eş zamanlılık çalışıyor). II kod tarafından yazıldı, `valid`, 203 kelime.
III, IV ve V **üçü de `draft`** kaldı, çünkü `flagged_sentences` sırasıyla 4, 2 ve 5 cümleyi kalıp dışı buldu;
`_run_section` kalıp dışı cümle bulunca bölümü `valid` saymıyor ve tur bitince koşu duraklıyor. Onaracak kod
(`repair_section`, **P8**) henüz yok. **Yani P8 isteğe bağlı bir sonraki parti değil, gerçek modelle rapor
alabilmenin ön koşulu.** Sahte modelle hiç görünmemesinin nedeni, `FakeAdapter` metninin kalıplara zaten
uymasıydı.

**Kalıp denetimi neden patladı (18 Eylül'de ölçüldü).** İlk teşhis ("Türkçe kalıp bankası zayıf") **yanlıştı**:
1618 kalıbın 1618'inin Türkçe karşılığı var ve çeviriler düzgün. Gerçek tablo şu: bayraklanan 11 cümlenin hiçbiri
kıl payı kaçırmıyor — en iyi puanları −0.40 ile −0.70, en yakın kalıpla paylaştıkları sabit sözcük sayısı 0 ya
da 1. Yani model kalıpları kullanmadı, doğal Türkçe yazdı; `report.md` "kalıpları yeniden kullan" diyor ama
zorunlu tutmuyor.

Bunun iki sonucu var. Birincisi, **`nearest_frames` tam da gerektiği anda işe yaramıyor:** hiçbir kalıp
tutmayınca sıralama, kalıp bankasının kendi örnek cümlelerinden rastgele parçalar döndürüyor ("Kadınlar, ...",
"ve b) ...", "Bunlar: ..."). P8'in onarım çağrısı bu üç kalıbı modele verecekse, düzgün bir cümleyi anlamsız bir
kalıba sokmasını istemiş oluruz. İkincisi, küçük ama gerçek bir hata: `phrasebank._SLOT` yalnız `x/y/z/xs/ys/zs`
biçimlerini yer tutucu sayıyor, `Xi`/`Xii`/`Xiii` biçimlerini **sabit sözcük** sanıyor; bu yüzden 2058 desenin
8'i (7'si "Classifying and Listing" içinde, o kümenin %11'i) hiçbir cümleyle eşleşemiyor — İngilizce tarafta da
aynı.

**Asimetri:** cevap yolunda kalıp uyumu yalnız uyarı üretir; rapor yolunda `_run_section` bayraklı cümlesi olan
bölümü `valid` saymıyor, yani fail-closed. Bu ayrım plana yazılmadı, koda düştü.

**Çalıştığı doğrulanan taraf:** plan adımı gerçek içerik üretti — kapsam cümlesi, pasaja bağlı sözlük, kanıt
tablosunun gerçek sütunlarına bağlı beş eksen, kod hesaplı korpus (`found` 128, `unique`/`screened` 105,
`included` 3, `full_text` 2). Atıf zinciri gerçek modelde de tutuyor: Türkçe iddia metni, İngilizce kaynak
çapasıyla saklı pasajda bulunuyor. IV ve V'te altışar kayıt `cell_missing_evidence` diye kesildi (kanıt bağı
olmayan hücreler bölüm girdisine alınmıyor).

**P5.5 — yöntem paketi sıkılaştırıldı ve ölçüldü.** ✅ `758f304`. `report.md`'nin bölüm talimatı artık kalıp
kullanımını zorunlu kılıyor (kanıt kuralı açıkça üstte: kalıba uydurmak için iddia değiştirilemez, dürüst kalıp
yoksa cümle sade kalır). `provenance.json`'ın eskimiş "yalnız grounded_answer" cümlesi düzeltildi.
İstem: `docs/product/p6-slice1-p55-prompt.md`.

**Aynı araştırma aynı kopyada yeniden koşuldu** (`run_Bqa3k0BVwwidaZ1aU4CI`, rapor `rpt_ztCV5o1NaqHqP5fc24V3`,
18 Eylül 03:44). Tek değişken talimattı.

| bölüm | önce | sonra |
|---|---|---|
| II (kod) | valid, 203 kelime, 0 bayrak | valid, 203, 0 |
| III | draft, 142, **4 bayrak** | **valid**, 143, **0** |
| IV | draft, 130, 2 | draft, 135, **1** |
| V | draft, 161, 5 | draft, 105, **1** |

**Bayrak sayısı 11 → 2.** Daha önemlisi, kalan iki bayrak artık kıl payı: cümleler kalıp diliyle yazılmış,
yalnız kalıbın bir sabit sözcüğü eksik ("… ele almaktadır" vs. kalıptaki "sorusunu ele almaktadır"), ve
`nearest_frames` bu sefer **işe yarar** kalıplar döndürüyor. Yani P8'in onarım çağrısı artık anlamlı ve küçük
bir iş. Koşu yine de duruyor: tek bayraklı cümle bölümü `valid` olmaktan çıkarıyor.

**Kalan açık konu — uzunluk.** Yazılan bölümler bütçenin alt sınırının çok altında: III 143 (en az 244),
IV 135 (313), V 105 (244). `plan.section_budgets` varsayılanı 5500 kelime ve on kaynaktan az dahil edildiyse
kaynak sayısıyla oranlanıyor; bu araştırmada 3 kaynak var, bütçe 1650'ye iniyor. Sahibin 18 Eylül'deki
beklentisi **10–15 referans için en fazla 15–20 sayfa**, yani tek sütunlu düzende 8–11 bin, iki sütunluda
13–17 bin kelime — bugünkü 5500 hedefinin 2–3 katı. Ayrıca sahip raporun **öğretici** olmasını istiyor; bugünkü
III talimatı kasten yalnız tanım odaklı. İkisi de ayrı tur, ikisi de karar bekliyor.

**Ölçüm yapılmadı:** dilim 0'ın `scripts/p6_eval/measure_fill.py` süre ölçümü bu koşuda halledilmedi; ayrı
gerçek-model maliyeti olduğu için sahibin ayrı onayını bekliyor.

**Buradan sonrası P5'in çıktısına bakılarak sıralanır.** Bugünkü tahmini sıra:

**P6 — VIII'in sayısal çekirdeği** (1e Task 2). Şema turunun sütun rolü kısmı P2.5'te yapıldı; kalan iş
VIII. bölümün sayılarını kodun üretmesi. `selection.py`'nin VIII için hiç seçim dalı yok, bölüm şu an yalnız
modelin yazdığıyla doluyor.

**P7** — kalan sekiz montaj kuralı (5, 6, 8, 9, 11, 12, 13, 14). Kural 12 için yukarıdaki karar 1'e bak.
**P8 — 1d Task 3: `repair_section` ve istisna kayıtları. ⬅ SIRADAKİ, P5 bunu zorunlu kıldı.**
**P9** — 1f: `report_review` ve destek-bozan onarımın geri alınması.
**P10** — 1h: hazırlık panelinin dördüncü durumu.
**P11** — 1i: okuma biçimli rapor görünümü, değişiklik bandı, zaman çizelgesi satırları.
**P12** — 1j: Markdown dışa aktarma ve numaralandırma.
**P13** — 1k: kesinti testleri (kota, çökme, iptal, kapsam değişimi, geç sonuç). Yukarıdaki
"bölüm başarısızlığının nedeni kayboluyor" zayıflığı burada karara bağlanmalı.
**P14** — 1l: scriptlenmiş modelle Playwright kabul testi.
**P15** — 1m: davranış vakaları ve R10 ekilmiş hata kümesi.
**P16** — 1n: beklenti dosyası (koşudan **önce** donar ve commit'lenir), ölçüm raporu, karar kaydı, tasarım
notunun durum güncellemesi.

Gerçekçi tahmin, 18 Eylül'de güncellendi: P1, P2 ve plan dışı P2.5 bir oturum sürdü ve dört tasarım boşluğu
çıkardı. Arayüzde bakılabilir bir rapor görmek P3 + P4 + P10/P11 demek, yani en az üç tur daha. Bütün dilim 1,
ölçüm dahil, iki oturum daha.

## Sahibe sorulan açık kararlar

1. **D12 atıf tutamakları.** `with_citation_handles` yalnız `grounded_answer`, `answer_review` ve
   `cell_extraction` için uygulanıyor. Rapor bölümleri de pasaj ve hücre alıntılıyor. Eklenirse
   `with_citation_handles`, `citation_handles` ve `resolve_citation_handles` `report_target`, izin listesi ve
   çıktı alanlarını da çevirmeli. Dışarıda bırakmak doğruluğu bozmuyor ama raporu D12'nin kayda geçirdiği
   uzun-kimlik kopyalama hatalarına açık bırakıyor. Karar ölçümden önce mi sonra mı, sahibin.
2. **Gerçek model koşusu onayı** (P5). Sahip 18 Eylül'de "önce kök nedeni düzeltelim" dedi; düzeltme bitti
   (P2.5 ve P3.5), onay hâlâ alınmadı.
3. **`quick` efor bütçesi bir raporu bitiremiyor.** `TEST_EFFORT_BUDGETS["quick"]` altı model çağrısı veriyor,
   rapor en az on bir bölüm yazıyor; `quick` bir araştırmada koşu VIII civarında `budget_exhausted` ile duruyor.
   Seçenekler: rapor koşusuna kendi bütçesini vermek, `quick`'te raporu reddetmek, ya da bütçeyi yükseltmek.
   Karar verilmedi; P3'te bilerek karıştırılmadı.
4. **Dilim 2, 3, 4'ün tasarımı yok** — sırasıyla 10, 10 ve 9 açık soru. Dilim 2 öne alınmalı, çünkü raporun
   içeriğini değiştiriyor: VI'ya dördüncü aday türü, III'e alanın gelişimi alt başlığı. Dilim 1 buna yer
   bıraktı (`report_gaps.kind` kapalı liste değil, III alt bölüm kabul ediyor), ama karar ne kadar gecikirse
   dilim 1'in çıktısı o kadar çok yeniden yazılır.

## Bilerek ertelenenler

- **Kesilme kaydının tablosu yok.** §4.3 bütçeye sığmayan kayıtların saklanmasını ve VIII'de sayı olarak
  görünmesini istiyor; migration 0035'te yeri yok. Nereye yazılacağı P2'de kararlaştırılmalı
  (`report_sections.validation_json` en yakın aday).
- **Montaj kuralı 7 kırılgan.** II ve VIII'in sayılarının dondurulmuş korpusla aynı olduğunu, bölümün
  düzyazısında İngilizce/Türkçe etiket sözcüklerini (`found`/`bulunan`, `unique`/`tekil`, …) arayıp yanındaki
  sayıyı okuyarak denetliyor. Etiket başka türlü ifade edilirse denetim sessizce kaçırır. Sağlam tasarım,
  bölümün sayılarını yapılandırılmış olarak saklayıp düzyazıyı onlardan üretmektir; P7'de ya da ölçümden sonra
  karara bağlanmalı.
- `CAPABILITIES["supported_tasks"]` rapor görevlerini saymıyor.
- `report_phrase_repair` bölüm kalıplarını alıyor ama çalışma zamanı dosya listesinde `phrases.md` yok, yani
  şimdilik etkisiz.
- `tests/test_api_flow.py`'de ~35 test fonksiyonu iki kez tanımlı (kötü bir birleştirme); pytest yalnız
  ikincisini topluyor. Bu dilimin konusu değil, ayrı bir temizlik.

## Tur nasıl koşulur

```sh
codex exec -s workspace-write -m gpt-5.6-sol -c model_reasoning_effort="medium" - < <istem.md>
```

`/Applications/ChatGPT.app/Contents/Resources/codex` ikilisi doğrudan çağrılır; `~/.local/bin/codex` sembolik
bağı `code-mode-host`'u bulamadığı için Codex hiçbir komut çalıştıramaz. İstem stdin'den `-` ile verilir.

İstemin her turda taşıması gerekenler: okunacak dosyalar, dokunulmayacak dosyalar (**başka bir oturum
`apps/web/`, `api/app.py`, `workflow/store.py`, `docs/decisions.md` üzerinde çalışıyor olabilir**),
"durum değiştiren hiçbir git komutu yok", tur öncesi ve sonrası test sayıları, ve "uydurma, bulamadığını
bildir".

Test koşumu `PYTHONPATH=backend:.` ister; belgelenen `PYTHONPATH=backend` ile `tests/test_p4_eval.py`
`ModuleNotFoundError: No module named 'scripts'` veriyor. Codex'in kum havuzu varsayılan uv önbelleğine
erişemiyorsa `UV_CACHE_DIR=/tmp/deixis-uv-cache` gerekir.
