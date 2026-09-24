# SW dilim 19 — Prob seti, kol tablosu ve sinyal tablosu (durma kuralı açık gereksinim)

**Tarih:** 25 Eylül 2026. **Durum:** dosya hazır. **Sahip A–E'yi 25 Eylül 2026'da önerildiği gibi kabul etti** (aşağıdaki
geçici yanıtlar artık sahibin kararıdır; D kaydına uygulamanın kapanışında yazılır). **Prompt:**
[sw-slice19-prompt.md](sw-slice19-prompt.md). **Ana dosya:** [sw-status.md](sw-status.md). **Karar:** yeni D
numarası (dilim yazar; en yüksek D100). **Önkoşul:** 15 (D95) ve 16 (D96), ikisi de kapandı. **Tür:** Kur.
**Uygulayan:** Opus · high. **İnceleme:** toplu. **Plan:** Opus 5.5 · high (plan turunun kuralı Fable · high; bu oturum
Opus'ta koştu). **İkinci görüş:** `gpt-6-sol` · high, salt okunur (`sol-plan.md`; "hazır değil", 9 bulgu; testleri
koşmadı). Eşgüdümcünün hükmüyle 1–8 kabul edildi ve aşağıya işlendi; 9'un zamanlama ve test kısmı kabul, git kısmı
reddedildi (uygulama promptunun pull / commit / push biçimi bu deponun standardı; prompt yalnız A–E cevaplandıktan
sonra koşar). İkinci tur (`sol-plan-2.md`): "düzeltmeyle hazır", 3 bulgu, üçü de kabul ve işlendi (tekil sinyalde
puanlanmamış kayıt ve eşitlik kuralı, gömme sonrası için zaman kuralı, ölçüm ekinin adları). **Ölçüm:** `.local/sw-slice19-plan-2026-09-25/` (`protocol.md` önce yazıldı; `measure.py` →
`measure.json`, `summary.md`; `outcome_timing.py` → `outcome_timing.json`; `timing.py`, `result.md`; salt okunur,
model ve ağ yok; `outcome_timing.py` oturum dizinindeki 0052'ye göç ettirilmiş kopyalarda koştu ve kopyaları sildi).
**Kapsam:** SW13 (hepsi; 13.6'da kurulacak bir şey yok), SW1.8, SW7.6, SW8.7.

**Goal:** Bir `sw` araştırması bugün her kaynağın kaç eser getirdiğini sayıyor (D93), ama o eserlerden hangisinin
dahil edildiğini ya da kişinin onayladığını hiçbir yerde söylemiyor. Sinyal sıraları saklanıyor (D79), okuyan yok.
Bu dilim dört şey kurar: (1) okunurken türetilen bir prob seti (kişinin onayladığı eserler, türüyle olumsuzlar,
kişinin getirdiği eserler) ve ondan ayrı, iki model koşusunun anlaşarak dahil ettikleri; (2) D93 satırlarına bu
sayılar, sorgu kökeni ve kol türüne göre "yeni" sayısı; hiçbir kolun bulmadığı problar adıyla; (3) araştırma
görünümünde kişi probu için sinyal başına betimleyici yakalama sayısı, paydası ve "karar vermeye yetmez" durumu;
gömme kurtarmasının öne aldığı ve bunlardan sonradan dahil edilenler, gözlem olarak; (4) dış bir referans kümesine
karşı karşılaştırmalı sinyal katkısını aralığıyla yazan bir betik. Durma kuralı ve maliyetli sinyalin otomatik
kapanması bu dilimde kurulmaz; açık gereksinim olarak koşuluyla kaydedilir.

## Bugün kod ne yapıyor

Kod 25 Eylül 2026'da okundu (`workflow/flow.py`, `views.py`, `ranking.py`, `queue.py`, `expansion.py`,
`chaining.py`, `protocol.py`, `decisions.py`; migration `0038`, `0049`, `0050`, `0051`).

- **Kollar.** Bir `sw` keşif koşusu her kolu bir kez çalıştırır: birinci tur (modelin sorgusu ve kodun sorgusu, her
  yönlendirilmiş kaynakta; D92, D93), ikinci tur veri genişlemesi en çok bir kez (D76), atıf zinciri tek halka (D95).
  Döngü yok: ikinci halka, üçüncü tur ya da "bir tur daha" kuralı yok. Aynı kapsamda yeni bir keşif koşusu aynı
  sorguları yeniden sorar, yeni bir tur açmaz.
- **Kol sayıları.** `views.source_counts(store, run_id)` (D93) koşu başına, tur × kaynak, getirilen eser ve "yalnız
  burada" sayısını `candidate_hits`'ten verir. Kaynak satırının "yalnız"ı yalnız **öbür kaynakların aramalarına**
  göredir (zincir o evrende değil); zincir satırının "yalnız"ı hiçbir aramanın bulmadığıdır. D93'ten önce aranmış
  koşu `counted: false` der. Transcript'in arama evresi bunu gösterir (`Transcript.tsx` ~310). Tur, onay kartının
  onaylanmış sorgu listesinin uzunluğundan (`approved.queries`) ve adımın dizininden (`search:N`) çıkar; onaylanmış
  sorgunun kökeni (`model` / `code`) o listenin aynı dizinindeki kayıtta durur. Sayılar kökene göre ayrılmıyor.
  `research_view` yalnız son 10 koşuyu döndürür.
- **Sinyaller.** `ranking.rank_records` her kaydın her koşan sinyaldeki sırasını ve üç sırayı (`fused_code`, `fused`,
  `inspection`) `record_signal_ranks`'e yazar; adım çıktısı sinyal başına `ran`, `reason`, `available`, tohumların
  türü, kaynakçasız pay ve gömmenin öne aldığı kayıtları (`rescued`) taşır. D79: "sinyal verimi raporlanmıyor; dilim
  19 okuyacak". Hiçbir ekran bu çıktıyı okumuyor.
- **Doğrulanmış kayıtlar.** `queue.verified_records` (D96) kişinin `human_include` ve `human_criterion_not_met`
  kararlarını, eskimişse `stale` işaretiyle verir. `ranking.verified_seeds` kişinin kaynak listesinde `included`
  yaptığı kayıtları ve kapsamın tohumunu doğrulanmış tohum sayar. Kuyruk cevabı başın seçimini `origin = user` yazar ve
  `human_selection_links`'e bağını ekler; listede sonradan yapılan her düzenleme (aynı duruma bile) seçimi kişinin
  kendi düzenlemesi yapar (D96). Ortak bir prob tanımı yok. Kişinin "kapsam dışı" diyebileceği bir cevap yok;
  kaynak listesindeki dışlamanın türü saklanmıyor.
- **İş sonucu.** `DecisionStore.work_outcome` kişinin kararını öne alır, iki sürümün karşıt taze kararını
  `versions_disagree` ile çözümsüz bırakır, D100'ün okunmuş kişi dosyasının kararını işin sonucu yapar. `facts()` bütün
  araştırma için bir kez türetilir.
- **Terim verimi.** `expansion.term_yields` türetilir, hiçbir yer çağırmıyor (D76).
- **Protokol gövdesi.** `arms`, `citation_chaining` ve `signals` listelerini taşır. Durma eşiği ya da prob tanımı yok.

## Elimizdeki sayılar

46 saklı `sw` araştırması okundu; 18a ve iki 18b kütüphanesi 17a `quick` kütüphanesinin kopyası olduğu için düşüldü,
43 kaldı: kuantum (q1) 34 (quick 16, standard 10, detailed 8), paket boyu (q2) 7 (quick 5, detailed 2), sepsis (q3) 2
(yalnız keşif, sıralama yok). Kollar 25'inde eserine kadar izlenebiliyor; bunların 17'sinde okuma koşusu da var.

**Referans kümeleri insan doğrusu değildir.** q1'in 31 eseri önceki bir model değerlendirmesinin
(`quantum-work-adjudication-2026-09-18`) yüksek güvenli alt kümesidir (51 doğrulanmışın 31'i); q2'ninki iki etiket
çağrısının uzlaştığı eserler. İkisi de eksik; listede olmayan bir `include` yanlış sayılmaz. Aynı konu ve eserler
birçok kütüphanede tekrar ettiği için kütüphane başına aralıklar birbirinden bağımsız değildir ve alan geneline
genellenmez.

1. **Kişinin onayladığı eser neredeyse yok.** 43 araştırmanın 2'sinde 1 eser (ikisi de dilim 16 kabulü, karar turu
   bilerek yapıldı); öbür 41'inde 0. Kişinin kendi getirdiği eser (üyelik `user_upload`, `zotero_import`,
   `library`): 43'ünde 0. Kişi probunun sinyal tablosu bugün saklı her araştırmada "karar vermeye yetmez" der.
2. **İki koşunun anlaşarak dahil ettikleri** (D85, `model_agreement`): q1 quick 1–14, standard 2–19, detailed 16–37;
   q2 quick 1–3. Referans listesinde olanı q1 quick 47 / 98 (%48), standard 39 / 99 (%39), detailed 58 / 151 (%38);
   q2'de 0 / 9. İş düzeyi kural (`work_outcome`) ile sürüm başına ham sayım 25 izlenebilir kütüphanenin hepsinde aynı
   çıktı (0 fark; `outcome_timing.json`).
3. **Araştırmanın kendi dahil ettikleri sıranın seçtikleridir.** Bir `include` iki model okuması ister; okuma planı
   sıranın başından ve grup sınırlarından kurulur (tam metin okuma sınırı 40 / 50 / 150, `quick` getirme 80,
   `rules.py`). Okuma koşusu olan 25 q1 kütüphanesinde dahil edilen 348 eserin 348'i planda ve tam metin önerisi
   kaydedilmiş (tanım gereği); referans listesinin 612 gözleminin 246'sı (%40) planda, 195'inin (%32) tam metin önerisi
   kaydedilmiş (`model_proposals`; önerisi saklanmadan düşen çağrı sayılmaz, yani bu "modele gönderildi" değildir). **Saklı birleşik sıranın özet okuma
   sınırı (40 / 100 / 300) içindeki konum:** dahil edilenlerin 308 / 343'ü (%90), listenin 286 / 778'i (%37). Birleşik
   sıradan bir sinyal tek tek çıkarılınca, 25 araştırmada üç sinyal üzerinden, dahil edilen bir eser bu sınırın
   dışına toplam 200 kez düşer, 35 kez içeri girer (5,7 : 1); listede 33 araştırmada 180 ve 120 (1,5 : 1). Bu bir
   seçim yanlılığının göstergesidir, nedensel katkının ölçüsü değil. Liste koşulunda ilk 200'deki değişimin %95 eşli
   bootstrap aralığı (bu havuz ve bu liste koşulunda): graph 33 araştırmanın 6'sında sıfırın üstünde, 1'inde altında,
   blocks 1'inde altında, bm25 hiçbirinde ayrılmıyor; dahil edilenlerle bm25 25'in 3'ünde üstünde, graph hiçbirinde.
4. **İki sinyal hiç koşmadı.** TF-IDF (doğrulanmış tohum ister) ve gömme (anlamsal arama ayarı ister) 43 araştırmanın
   hiçbirinde koşmadı. Gömme kurtarmasının hiç verisi yok.
5. **Kol satırları hesaplanabiliyor ve bilgi taşıyor.** Örnek, 17a standard: OpenAlex'te kodun sorgusu 863 eser,
   13 dahil; modelin sorgusu 793 eser, 8 dahil; IEEE kod 445 / 8, model 316 / 4; zincir 101 eser, 3 dahil (1'ini
   hiçbir arama bulmadı); ikinci tur OpenAlex 660 / 7. D92'nin "iki sorgu farklı eser bulur" bulgusu dahil
   edilenlerde de görünüyor.
6. **Durma kuralının girdisi gürültü.** Koşu sırasıyla kol türü başına yeni dahil edilen: veri genişlemesi 17 koşunun
   8'inde en az 1 (1–4 eser, %5–11), zincir 15 zincirli koşunun 9'unda 1 (q1'de 11'in 5'i). 8–37 dahil edilen eserde
   tek eser %3–13 eder; 20'nin altında %5 çizgisi tek eserle aşılır.
7. **Doğrulama geç gelir.** Keşfin bitişinden ilk okuma koşusunun bitişine: q1 quick 1,7–8,1 dk, standard 5,3–12,3,
   detailed 20,0–28,5; q2 quick 3,2–7,0. Kişinin kararı daha da sonra.
8. **Maliyet** (`outcome_timing.json`; en büyük dört izlenebilir kütüphanenin göç ettirilmiş kopyaları, 2.592–5.756
   iş; bir ısınma çağrısından sonra 5 tekrarın ortancası): `research_view` 1,80–5,62 sn; bir `facts()` türetmesi
   0,032–0,072 sn; bütün işlerin `work_outcome`'u 0,006–0,011 sn; `queue_counts` 0,062–0,127 sn;
   `verified_records` 0,061–0,123 sn (kendi `facts`'ini yeniden türetiyor); revizyonun bütün keşif koşularında
   `source_counts` 0,010–0,018 sn. `verified_records` ayrıca çağrılırsa tek başına bütçenin yarısını yer; ortak
   `facts` ile ek maliyet birkaç yüz milisaniyenin çok altında kalır.

İki konunun gösteremediği: q2'de bir havuzda 1–4 liste eseri var ve dahil edilen 9 eserin hiçbiri listede değil; q2
tabloların hesaplanabildiğini gösterir, ne söylediklerini göstermez. Üçüncü bir alan, gömme ve TF-IDF'in katkısı,
kişinin gerçekte kaç karar verdiği bilinmiyor.

## SW maddeleri: kurulan, betiğe giden, açık kalan

| Madde | Bugün | Bu dilimde |
|---|---|---|
| SW13.1 kol: bulunan pozitif, yalnız onun bulduğu, dönen satır | Eser ve "yalnız" var (D93); pozitif yok | Kurulur (karar 3) |
| SW13.1 sinyal: pozitif ve terfi eden olumsuz | Sıralar saklı, okuyan yok | Kişi probu için betimleyici sayı ürün içinde (karar 6); olumsuz ve karşılaştırma betikte (karar 7) |
| SW13.1 kod kapısı satırı | Kapı yok (dilim 23) | Yok |
| SW13.2 olumsuzlar türüyle; kapsam dışı yoksa "yok" | Kişinin `criterion_not_met`'i var, kapsam dışı cevabı yok | Kurulur, rapor biçiminde (karar 1) |
| SW13.3 sinyal katkısı aralığıyla, karar sahibin | Yok | Betikte, referans kümesine karşı, koşullu aralıkla (karar 7) |
| SW13.3 sıradan sinyal otomatik kapanmaz | Kapanmıyor | Aynen (karar 8) |
| SW13.3 maliyetli sinyalin otomatik kapanması | Yok | **Açık gereksinim, şimdilik uygulanamaz** (karar 8, soru C) |
| SW13.4 kol türüne göre durma | Hiçbir kol tekrar etmiyor | **Açık gereksinim, şimdilik uygulanamaz**; tür başına sayı gösterilir (karar 4, 9, soru D) |
| SW13.5 doğrulama gelene kadar geçici rakam | Doğrulama keşiften 1,7–28,5 dk sonra | Sayılar okunurken türer; okuma yoksa "henüz okunmadı" (karar 3); kurala bağlı kısmı SW13.4 ile açık |
| SW13.6 yakala-yeniden yakala kullanılmaz | Kullanılmıyor | Kurulacak bir şey yok; betik de hesaplamaz |
| SW13.7 hiçbir kolun bulmadığı problar kimlikle | Yok | Kurulur (karar 5) |
| SW1.8 her arama ve sinyal prob setine karşı; turlarda dur | Yok | Arama: karar 3; sinyal: karar 6–7; durma: SW13.4 ile açık |
| SW7.6 sinyal verimi her araştırmada; alanda kapatma | Yok | Kişi probu için betimleyici verim her araştırmada (karar 6); karşılaştırmalı verim betikte; alan kapatması açık (SW13.3) |
| SW8.7 gömme kolunun katkısı; kapatma | Yok | Öne alınan ve sonradan dahil edilen, gözlem olarak (karar 6); kapatma açık |

## Kararlar

1. **Prob seti saklanmaz, okunurken türetilir** (`workflow/probes.py`; kuyruk ve bekleme listesi gibi). Güncel kapsam
   revizyonunun üye işleri üzerinde, iş düzeyinde, **tek öncelik kuralıyla**. Her iş için başın güncel seçimine
   bakılır:
   - Seçim `origin = user` değilse iş kişi probu değildir.
   - Seçimin **o sürümüne** bağlı açık bir kuyruk kararı varsa (`human_selection_links`, `queue.queue_answers`'ın
     okuduğu bağ) prob o karara uyar: karar eskimişse (`DecisionStore.is_stale`, `verified_records`'ın `stale`
     bilgisiyle aynı test) iş prob değildir ve `look_again` sayılır; eskimemişse `human_include` onaylı pozitif,
     `human_criterion_not_met` türü `criterion_not_met` olan olumsuzdur.
   - Seçimin o sürümüne bağlı kuyruk kararı yoksa seçim kişinin kendi liste düzenlemesidir (kuyruk cevabından sonra
     aynı duruma yapılan düzenleme dahil, D96): `included` onaylı pozitif, `excluded` türü `not_recorded` olan
     olumsuzdur. Liste düzenlemesi bir ölçüte bağlı değildir, eskimez; bu yazılı bir sınırdır.
   - Kapsam dışı türü hiçbir yoldan yazılamıyor; rapor "kapsam dışı olumsuz kaydedilmedi" der ve olumsuz sayısını
     yanlış-pozitif oranı gibi sunmaz (SW13.2).
   - *Kişinin getirdiği eser:* üyeliği `search` dışında eklenmiş (`user_upload`, `zotero_import`, `library`) ya da
     kapsamın tohumu olan iş. Pozitif sayılmaz; yalnız karar 5'e girer.
   **Neden:** SW11.13; bugün iki ayrı "doğrulanmış" tanımı var (`verified_records`, `verified_seeds`); dilim 20 aynı
   tanımı okuyacak. Sol bulgu 5: kuyruk kararı eskidiğinde seçim yine `user` kalıyor ve eski planda prob hem sayılıp
   hem sayılmıyordu.
2. **Sütun tanımları, üçü ayrı ve ayrık.**
   - `verified` (kişi probu): karar 1'in onaylı pozitifi.
   - `included` (iki koşu anlaştı): işin `work_outcome` sonucu (D100 dahil) `include` ve `decided_by =
     model_agreement`, ve iş kişi probu (pozitif ya da olumsuz) değil. `versions_disagree` ile çözümsüz iş burada yok.
   - Başın seçimi bu sütunlara girmez; `included` bir tam metin sonucudur, seçim değil.
   Kişinin onayıyla hiçbir yerde toplanmaz; ekranda "iki model koşusu anlaştı, siz onaylamadınız" anlamında
   adlandırılır, "doğrulanmış" denmez. **Neden:** Sol bulgu 6. Saklı veride bu tanım planın ham sayımıyla 25
   kütüphanenin hepsinde aynı; kabul bu yüzden eşitlik ister. **(Soru A.)**
3. **Kol tablosu D93'ün satırlarını genişletir.** `source_counts`'un şekli ve anlamı kalır (tur × kaynak, zincir ayrı,
   `counted`); her satıra: dönen kayıt (`rows`, sayfaların `result_count` toplamı), `included`, `included_only`,
   `verified`, `verified_only`. "Yalnız" D93'ün evreniyle: kaynak satırında "bu koşuda başka kaynağın araması
   bulmadı", zincir satırında "bu koşuda hiçbir arama bulmadı"; ekran etiketi bu evreni söyler, yalın "yalnız burada"
   yazmaz. Birinci turda bir kaynağa iki köken de sorgulandıysa satır `by_origin` taşır: köken başına eser ve dahil
   ("yalnız" yok). Köken, adımın dizini (`search:N`) ile onay kartının `approved.queries[N].origin`'inden okunur,
   sorgu metninden değil (aynı metin iki turda geçebilir); ikinci turun dizinleri (`N ≥` onaylı sorgu sayısı)
   `expansion`'dır; kökeni olmayan eski kart `by_origin` vermez. Kollar için olumsuz sayı yok (SW13.1). Revizyonda hiçbir
   işin tam metin kararı yoksa `read: false` ve ekran "tam metin henüz okunmadı" der; sayılar okuma kararları geldikçe
   değişir (SW13.5). **Neden:** sayı 5; Sol bulgu 7.
4. **Kol türü satırı, sayı olarak.** Koşu sırasıyla anahtar sözcük (birinci tur), veri genişlemesi (ikinci tur), atıf
   zinciri: tür koştu mu, eser, yeni eser (koşuda önceki türlerin bulmadığı), dahil, yeni dahil, onaylı, yeni onaylı.
   Eşik yok, "dur" ya da "bir tur daha" yok. Onay kartındaki model terim önerileri (D82) birinci turun sorgusuna girer;
   eserleri ayrılamaz, anahtar sözcük türünde sayılır ve bu yazılır.
5. **Hiçbir kolun bulmadığı problar, adıyla** (SW13.7). Onaylı pozitifler ve kişinin getirdiği eserlerden, güncel
   revizyonun **bütün** keşif koşularında (`runs` tablosundan, `research_view`'ın son-10 penceresinden değil) hiçbir
   arama ya da zincir isteğinin bulmadığı işler: başlık, DOI ya da başka kimlik, neden prob (onay / getirilen).
   **İzlenebilirlik şartı:** revizyonun sonuç döndürmüş her aramasının `candidate_hits` satırı olmalı (D93'ün
   testi, her koşu için). Hiçbir koşu izlenemiyorsa liste yerine "sayılmadı"; bir kısmı izlenebilir, bir kısmı D93
   öncesiyse izlenebilir koşularda bulunmayan her prob `unknown` olur, "bulunamadı" değil. **Neden:** kişinin
   bildiği bir makaleyi aramanın bulamadığını ürünün kendi verisi ancak böyle söyler; Sol bulgu 7.
6. **Sinyal tablosu, araştırma görünümünde, betimleyici.** Koşunun anahtar sözcük sıralama adımından:
   - Sinyal başına koştu mu, koşmadıysa nedeni (`no_verified_seeds`, `no_seed_with_references`, `embedding_off`,
     `no_stored_similarity`), kaç kaydı puanlayabildi, tohumların kaç doğrulanmış kaç kod tohumu olduğu, kaynakçasız pay.
   - **Kişi probu için yakalama:** her koşan sinyal ile `fused` ve `inspection` sırasında, onaylı pozitiflerden ilk 100
     ve ilk 200'de olanların sayısı, **paydası** ve durum. **Payda:** o sıralama adımının satırlarında bulunan, iş
     düzeyindeki onaylı pozitifler; adımın her kaydı saklı `record_signal_ranks.source_version_id` üzerinden `source_versions.work_id` ile işine bağlanır (sıra tablosu `work_id` saklamaz), böylece işin başı sonradan
     değişse de iş bulunur (bir işin birden çok satırı varsa en iyi yeri). **Tekil sinyalde yakalama:** yalnız sinyalin
     puanladığı satır (`available = true`) sayılır; sinyalin puanlayamadığı kayıtların ortak kuyruk sırası 100'ün
     altında kalsa da sayılmaz. **Eşitlik:** saklı sıra eşit puanlı grubun ortalamasıdır; grubun son konumu
     (`rank + (grup boyu − 1) / 2`, grup boyu aynı adımda aynı sinyalde aynı sırayı paylaşan puanlı kayıtların sayısı)
     kesimin içindeyse eser yakalanmış sayılır. Kesimi aşan bir gruptaki eserler yakalanmış sayılmaz, ayrıca "kesimde
     eşit" diye sayılır. Neden: "ilk 100" hiçbir zaman 100'den fazla kayıt tutmaz ve eşitlik keyfi bir sırayla bozulmaz;
     orantılı sayım kesirli sayı verirdi ve bir kişiye okunaklı değil. **`fused` ve `inspection`:** saklı kesin sıra
     (tam sayı, kimlikle bozulmuş; D79), eşitlik yok. Payda
     `PROBE_JUDGE_MIN`'in (30, elle seçildi: SW13'te 20–29 pozitifle her aralık sıfırı içerdi) altındaysa durum
     `too_few` ve ekran "karar vermeye yetmez" der; üstündeyse `descriptive`, ekran "yalnız sayı; karşılaştırma dış
     referans kümesiyle yapılır" der. Hiçbir durumda karar verilmez, bir şey kapatılmaz. Bu sabit hiçbir kaydı
     etkilemez; protokol eşiği değildir.
   - **İki koşunun anlaştıkları ayrı satırda**, aynı sayılarla ve sabit bir notla: "bu eserler sıranın başında olduğu
     için okundu; sinyalin başarısı değildir" (sayı 3). Kişi probuyla toplanmaz.
   - **Gömme kurtarması, gözlem olarak:** gömme koştuysa öne aldığı kayıt sayısı (`moved_up`; her biri kodun kendi
     sırasında ilk 200'ün dışındaydı, D79) ve ayrıca bunlardan **o sıralama adımından sonra** dahil edilen
     (`moved_up_then_included`) ve onaylanan (`moved_up_then_verified`). "Sonra" saklı zamanlarla kurulur: işin
     `included` sütununa giren kararının `stage_decisions.created_at`'i, onaylı pozitifte seçimi yazan kuyruk kararının
     `created_at`'i (bağ `human_selection_links`'te) ya da liste düzenlemesinin `selections.updated_at`'i, sıralama
     adımının `run_steps.finished_at`'inden sonra olmalı; ikisi de aynı süreçte aynı saatle yazılır. Karar adımdan önce
     yazılmışsa (aynı kapsamda ikinci bir keşif koşusu önceden dahil edilmiş bir işi yeniden sıralayıp öne aldıysa) iş
     bu sütunlarda değil, `moved_up_already_decided`'da sayılır. Zaman okunamazsa (bir alan boş) ya da karar ile adım bitişi aynı milisaniyeyi taşıyorsa (eşit damga önceyi de sonrayı da kanıtlamaz; `decisions.py` karar geçmişinde aynı çakışmayı tanır) iş o sütunlara girmez,
     `moved_up_already_decided` da değil, `moved_up_time_unknown`'da sayılır. İkincisi gözlemsel verimdir: öne alınan
     eser okunduğu için etiket alabildi, alınmayan hiç okunmadı; "gömme olmasaydı bulunmazdı" denmez.
   **Neden:** Sol bulgu 3 ve 4; SW1.8, SW7.6 ve SW8.7'nin "her araştırmada rapor" kararı. Döngüsellik model
   kararlarını sinyal başarısı diye göstermeyi engeller, kişi probunu paydasıyla göstermeyi engellemez.
7. **Karşılaştırmalı katkı ve aralık betikte, referans kümesine karşı** (`scripts/probe_report.py`). Bir saklı
   kütüphaneyi salt okunur açar ve bir **referans kümesi** dosyası alır (JSONL; başlıkta `origin`: kümenin nasıl
   yapıldığı, `completeness`: bilinen eksiklik; satırlarda anahtar, başlık, DOI'ler, OpenAlex kimlikleri, isteğe bağlı
   olumsuzlar). Yazar: karar 3–4'ün işlevleriyle kol tablosu ve kol türü satırı, sinyal başına ilk 100 / 200'deki
   pozitif ve olumsuz, ortanca sıra, bir sinyal çıkarılınca ilk 200'deki değişim ve %95 eşli bootstrap aralığı (2.000
   tekrar, tohum 0, pozitifler anahtar sırasıyla). Liste girdisi işlerinden biri DOI, OpenAlex kimliği ya da
   normalleştirilmiş başlıkla eşleşince bulunur, bir kez sayılır, en iyi yeriyle. Çıktı her aralığı "bu havuz ve bu
   referans kümesi koşulunda" diye adlandırır, kütüphaneler arasında aralık birleştirmez, alan düzeyinde kapatma
   sonucu yazmaz; referans kümesinde olmayan bir `include`'u yanlış saymaz. Yakala-yeniden yakala yok (SW13.6).
   Başvuru yordamı planın `measure.py`'si. Dilim 24'ün kampanyası bunu koşar; sahip sinyal kararını oradan verir.
   **Neden:** SW13.3'ün raporu ancak sıranın seçmediği bir kümeyle anlamlı; Sol bulgu 2. **(Soru B.)**
8. **Sıradan sinyal kapanmaz; maliyetli sinyalin kapanması açık gereksinim.** SW13.3 gereği bm25, blocks, tfidf, graph
   hiçbir zaman kodla kapatılmaz. SW13.3'ün istisnası (anahtar, model çağrısı ya da indirme isteyen sinyal: gömme,
   modelin terim genişlemesi; SW7.6, SW8.7'nin ikinci cümleleri) bu dilimde **uygulanamaz ve açık kalır**. Koşul:
   sinyal araştırmalarda koşuyor olmalı ve "birkaç araştırma, aynı alan" sayılabilmeli. Bugün gömme 43 araştırmanın
   hiçbirinde koşmadı, model terim önerisi yalnız kişi isteyince ve kişi eklerse sorguya girer (D82), araştırmalar
   arası sayaç ve alan tanımı yok. **Yeniden açılacağı olay:** dilim 24 kampanyasında gömme en az bir soruda koştuğunda
   ya da gömme varsayılan açık hale geldiğinde; o zaman kural araştırmalar arası bir sayaçla ayrı bir dilimde kurulur.
   İstisnayı bu dilimde kurmamak sahibin açık kararıdır. **(Soru C.)**
9. **Durma kuralı açık gereksinim** (SW13.4–5, SW1.8'in ikinci cümlesi). Bugün **uygulanamaz**: ürün içinde hiçbir
   kol tekrar etmiyor, kuralın durduracağı ya da sürdüreceği bir tur yok (tek halka, D95; ikinci tur en çok bir kez,
   D76). **Yeniden açılacağı olay:** bir tür ikinci kez koşabilir hale geldiğinde (SW4.5'in ikinci halkası, yeni bir
   anahtar sözcük ya da genişleme turu, ya da "daha ara" eylemi); o dilim SW13.4'ü kendi durma kuralı olarak kurar,
   SW13.5'in geçici rakamıyla. Karar 4'ün sayıları kuralın girdisini bugünden gösterir. Sayı 6 ve 7 o dilim için
   uyarıdır: %5 çizgisi 20'nin altında tek eserle aşılıyor, doğrulama dakikalar sonra geliyor. **(Soru D.)**
10. **Veri akışı ve maliyet.** `research_view` tek bir okuma anlık görüntüsünde ve tek bir `DecisionStore.facts()`
    türetmesiyle çalışır: `queue_counts`, prob seti, kol sayıları ve sinyal tablosu aynı `facts`'i ve aynı
    `work_outcome` sonuçlarını paylaşır; `verified_records` ayrıca çağrılmaz, eskime testi aynı `facts`'in
    `stale_key`'iyle yapılır. Arka uç `research_view`'da: her keşif koşusunun `source_counts`'u (karar 3–4) ve
    `signals`'ı (karar 6), araştırma düzeyinde `probes` (karar 1, 2, 5). Ekran: Transcript'in arama evresindeki D93
    satırlarına dahil ve onaylı sayıları, köken ayrımı, kol türü satırı ve "Aramanın bulmadığı eserleriniz"; tarama
    evresinde, benzerlik satırının yanında sinyal tablosu. Yeni sekme yok; `legacy`'de yeni alanlar `null`.
    **Bütçe ve ölçüm yöntemi:** yeni türetmenin kendisi (prob seti + kol sayıları + sinyal tablosu, ortak `facts`
    verilmiş olarak) en büyük dört izlenebilir kütüphanenin göç ettirilmiş kopyalarında, bir ısınma çağrısından sonra
    5 tekrarın ortancasıyla en çok 0,25 sn sürer. `research_view`'ın toplam süresi aynı yöntemle dilimden önceki
    commit'te ve sonra ölçülüp yazılır; kendi yayılımı büyük olduğu için (1,8–5,6 sn) kapı o değil, türetmenin kendi
    süresidir. **Bütçe aşılırsa:** `probes` ve `signals` `research_view`'dan çıkar, `GET
    /api/researches/{id}/probes`'a taşınır ve ekran onları bölüm açılınca okur; kayıt satır 19'a ve D kaydına yazılır.
    `source_counts`'un yeni alanları görünümde kalır.
11. **Hiçbir şey yazılmaz.** Migration yok, adım yok, karar yok, olay yok, seçim yok. Protokol gövdesi değişmez
    (`PROBE_JUDGE_MIN` bir gösterim sabitidir, betiğin 100 / 200 ve bootstrap ayarı betiğin). Keşif, getirme, okuma ve
    yanıt aynen kalır.

## Sahibin vereceği kararlar (geçici; kabul edilmedi, D kararı değil)

Dosya aşağıdaki önerilerle yazıldı. Sahip farklı karar verirse satır 19'a yazılır ve etkilenen karar ve task değişir.
Uygulama bu beş cevap satır 19'da yazılı olmadan başlamaz.

- **A — Prob pozitifi kim?** Öneri: yalnız kişinin onayı (karar 1); iki koşunun anlaşarak dahil ettikleri ayrı
  sütunda, adıyla (karar 2). *Seçenek:* anlaşarak dahil edilenleri de prob saymak; tablolar dolu olur ama kişinin
  denetlemediği model çıktısı "doğrulanmış" diye okunur (SW11.13'e aykırı).
- **B — Karşılaştırmalı sinyal katkısı betikte.** Öneri: ürün kişi probu için betimleyici sayıyı paydası ve "karar
  vermeye yetmez" durumuyla gösterir (karar 6); karşılaştırmalı katkı ve aralık referans kümesine karşı betikte
  (karar 7). *Seçenek:* ürüne araştırmanın kendi dahil ettikleriyle aralıklı katkı koymak; sayı 3'teki 5,7 : 1 yüzünden
  önerilmiyor.
- **C — Maliyetli sinyalin otomatik kapanması.** Öneri: bu dilimde kurulmaz, açık gereksinim olarak kalır; yeniden
  açılma olayı karar 8'de.
- **D — Durma kuralı ve tekrar eden kol.** Öneri: kural bu dilimde kurulmaz, açık gereksinim (karar 9); ikinci zincir
  halkası (SW4.5) gibi tekrar eden bir kolun kurulup kurulmayacağı dilim 24'ün sonucundan sonra ayrı karar.
- **E — "Kapsam dışı" cevabı.** Öneri: bu dilimde eklenmez; rapor "kapsam dışı olumsuz kaydedilmedi" der. Kuyruğa yeni
  bir cevap dilim 16–17'nin alanıdır ve yeni neden kodu ister.

## Global constraints

- **Yalnız `sw`.** `legacy` araştırmada yeni alanlar `null`, eski alanlar aynı.
- **Salt okuma.** Türetme hiçbir tabloya yazmaz; `research_view` çağrısı hiçbir tablonun satır sayısını değiştirmez.
- **Model sözleşmesi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır; yöntem paketi, şemalar ve model
  adımları dokunulmaz. Yeni neden kodu yok. Migration yok (en yüksek `0052` kalır). Protokol gövdesi değişmez.
- **Birim iştir.** Sayılar iş düzeyinde, DOI ve iş birleştirmesinden sonra (D46, D48); sonuç `work_outcome`'la.
- **Belirlenimcilik.** Her liste kalıcı kimlikle sıralanır (SW14.6); betiğin bootstrap'ı sabit tohumla.
- **Konuya özgü hiçbir şey yok.** Kaynak, köken ve tür adları koddaki tablolardan.
- **Kanıt sözcükleri.** Ekran "iki koşu anlaştı" ile "onayladınız"ı ayırır; model kararına "doğrulanmış" denmez; tek
  başına bir sayıdan "bu sinyal işe yarıyor / yaramıyor" cümlesi kurulmaz (AGENTS.md).

## Task taslağı

1. **Prob seti** (`workflow/probes.py`, karar 1, 2, 5). Testler: kuyruk `include`'u onaylı pozitif; kaynak listesinden
   `included` onaylı pozitif; kuyruk `criterion_not_met`'i türüyle olumsuz; listeden `excluded` `not_recorded`;
   **eskime iki durum:** (i) R1'de kuyruk `include`'u, kapsam R2'ye geçer, seçim hâlâ `user/included` ve bağ o sürümde
   → prob değil, `look_again` 1; (ii) aynı iş, R2'de kişi listeden seçimi yeniden `included` yapar (yeni seçim sürümü,
   bağ yok) → onaylı pozitif; `not_sure` ve `pdf_wrong` prob değil; `model_agreement` `include` yalnız `included`
   sütununda; kişi probu olan iş `included`'da değil; `versions_disagree` iş hiçbir sütunda; D100'ün okunmuş kişi
   dosyası kararı işin sonucu; kapsamın tohumu ve `user_upload` üyeliği getirilen eser; hiçbir aramanın bulmadığı
   getirilen eser listede, zincirin bulduğu listede değil; revizyonun 10'dan eski bir koşusunun bulduğu eser listede
   değil; bir koşusu D93 öncesi, biri sonrası olan revizyonda bulunmayan prob `unknown`; hiçbiri izlenemiyorsa
   "sayılmadı"; `legacy` `None`.
2. **Kol tablosu** (`views.source_counts` genişler, karar 3–4). Testler: D93'ün mevcut alanları ve sayıları aynı
   (mevcut testler değişmeden geçer); `rows`; "yalnız" D93'ün evreniyle (zincirin de bulduğu anahtar sözcük işi kaynağın
   "başka kaynak bulmadı" sayısında kalır); köken dizinden: iki turda aynı metinli sorgu ikinci turda `expansion`;
   kökeni olmayan kart `by_origin` vermez; okuma yoksa `read: false`; okuma kararı yazılınca sayı değişir, hiçbir şey
   yazılmadan; tür satırı sırası ve "yeni" sayıları; zinciri kapalı koşuda zincir türü `ran: false`; `counted: false`
   koşuda yeni alanlar yok.
3. **Sinyal tablosu** (karar 6). Testler: koşmayan sinyalin nedeni; payda ve `too_few` / `descriptive` sınırı
   (29 ve 30 onaylı pozitifle); **puanlanmamış iş:** graph'ın puanlayamadığı (`available = false`) ve kuyruk sırası
   100'ün altında kalan küçük havuzdaki onaylı iş graph'ın ilk 100'ünde sayılmaz, bm25'inkinde sayılır; **eşitlik:**
   kesimi aşan bir eşit grup (ör. 98–103. konumlar, ortalama 100,5) yakalanmış sayılmaz, "kesimde eşit"te sayılır;
   tamamı içeride kalan grup sayılır; **baş değişimi:** sıralamadan sonra işin başı başka sürüme geçen onaylı iş paydada
   ve yakalamada yine bulunur; `fused` / `inspection` saklı tam sayı sırayla; anlaşarak dahil edilenler ayrı satırda ve
   kişi sayısına eklenmez; gömme kapalıyken `moved_up` yok; betikli benzerlikle öne alınan bir kayıt sıralamadan sonra
   dahil edilince `moved_up` 1, `moved_up_then_included` 1; **önceden verilmiş karar:** sıralamadan önce dahil edilmiş ve
   öne alınmış iş `moved_up_then_included`'da değil, `moved_up_already_decided`'da; zincir sıralama adımı okunmaz.
4. **Görünüm ve maliyet** (karar 10–11). Tek `facts`, `verified_records` çağrılmaz (bir sayaçla ya da `facts`'i
   sayan bir sahteyle sınanır). Testler: `research_view` öncesi ve sonrası bütün tabloların satır sayıları aynı;
   `legacy` alanları `null`.
5. **Arayüz.** `.impeccable.md` önce. Arama evresi: kaynak satırına dahil ve onaylı sayıları, "başka kaynak
   bulmadı" / "hiçbir arama bulmadı" etiketleriyle; iki köken sorgulandıysa kısa köken ayrımı; kol türü satırı;
   "Aramanın bulmadığı eserleriniz" (`unknown` ve "sayılmadı" ayrı metinle); okuma yoksa "tam metin henüz okunmadı".
   Tarama evresi: sinyal tablosu, payda ve "karar vermeye yetmez"; anlaşma satırı notuyla; gömme satırı. Metinler
   `i18n.ts` / `labels.ts`'ten. Playwright: tam metin kararına varan mevcut bir `sw` senaryosuna (J ya da L) dahil
   sayısı, "henüz okunmadı" ve "karar vermeye yetmez" eklenir; hiçbiri uymuyorsa yeni M. Ekran görüntüsüyle masaüstü ve
   telefon genişliğinde kendim doğrularım.
6. **Betik** (`scripts/probe_report.py`, karar 7). Testler (`PYTHONPATH=backend:.`): sentetik kütüphanede kol ve
   sinyal sayıları elle hesaplananla aynı; aynı girdiyle iki koşu bayt bayt aynı; kütüphane salt okunur açılır;
   referans kümesinde olup kütüphanede olmayan eser "havuzda yok"; başlıksız (`origin` / `completeness` yok) referans
   kümesi reddedilir; çıktıda aralık koşul cümlesi var.
7. **Kabul** (model ve ağ yok; sonuçlar `.local/sw-slice19-acceptance-<tarih>/`).
   (a) Planın 25 izlenebilir kütüphanesinin oturum dizinindeki 0052'ye göç ettirilmiş kopyalarında: köken başına
   eser ve dahil sayıları (`by_origin`, ikinci tur ve zincir satırları) planın `measure.json`'undaki `arms`
   satırlarındaki eser ve `P_code` sayılarıyla **eşit**. Beklenen fark yok: iş düzeyi kural ham sayımla 25'inde aynı
   (`outcome_timing.json`) ve iki kütüphanedeki tek kişi probu eserinde model anlaşması yok. "Yalnız" sayıları
   karşılaştırılmaz (plan her köken satırını öbür bütün satırlara, zincir dahil, karşı saydı).
   (b) Karar 10'un bütçesi karar 10'un yöntemiyle; `research_view` önce / sonra süreleri yazılır.
   (c) Betik q1 ve q2 kütüphanelerinde `measure.json`'un referans kümesi (`P_ref`) sinyal sayılarını (ilk 100 / 200,
   ortanca, bir sinyal çıkarılınca değişim ve aralığı) yeniden üretir. Plan tekil sinyallerde puanlanmamış satırları ve
   eşit grupları ürünün kuralıyla saymadı (`rank ≤ kesim`); betik ürünün karar 6 kuralını kullanır, bu yüzden tekil
   sinyal yakalamalarında fark beklenebilir: her fark puanlanmamış ya da kesimde eşit bir kayda bağlanarak yazılır.
   Birleşik sıradan bir sinyal çıkarma sayıları kesin sıra kullandığı için aynı olmalı.
   (d) `research_view` hiçbir tablonun satır sayısını değiştirmez.
8. **Kapanış.** Yeni D numarası (A–E'nin sahip cevabıyla; açık gereksinimler, koşulları ve yeniden açılma olaylarıyla,
   Limits'te). `search-workflow-review-2026-09-18.md`'de SW13, SW1, SW7 ve SW8'in durum satırları (kurulan, betiğe
   giden, açık kalan, koşuluyla). `sw-status.md` satır 19.

## Kabul koşulları

- Pytest tam koşu: bilinen tek hata (`test_extraction_is_stopped_when_it_exceeds_the_memory_limit`) ayrı, kalan tam
  koşu geçti; build temiz; lint uyarı sayısı 17'yi aşmaz; Playwright A–L (ve varsa M) geçer.
- Task 7'nin (a)–(d)'si yazılı; (a) eşit.
- `skill_package_hash` aynı; migration yok; protokol gövdesinin özeti sentetik bir akışta dilimden öncekiyle aynı.

## Bu dilimde yok

- Durma kuralı (SW13.4–5) ve tekrar eden kollar: açık gereksinim, karar 9.
- Maliyetli sinyalin otomatik kapanması ve araştırmalar arası, alan başına sayaç: açık gereksinim, karar 8.
- Ürün içinde karşılaştırmalı sinyal katkısı, aralığı ve olumsuz terfisi (betikte).
- Kod kapısı ve onun satırı (dilim 23).
- Kişinin "kapsam dışı" cevabı (soru E).
- Terim verimi ekranı (`expansion.term_yields`, SW1.3; plan maddesi 19'da yok).
- Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dökümü (dilim 20; prob tanımını `probes.py`'den okur).
- Yakala-yeniden yakala (SW13.6).
- `legacy`'de hiçbir şey.

## Ölçülmedi

Kişinin kol ve sinyal satırlarını okuyup bir şeye karar verip vermediği. Gerçek kullanımda kişinin kaç eser
onayladığı (saklı veride 43 araştırmanın 2'sinde 1). Gömme kurtarması ve TF-IDF (43'ünün hiçbirinde koşmadı).
`PROBE_JUDGE_MIN = 30`'un yeterli olup olmadığı (SW13 kaç pozitifin yeteceğini hesaplamadı). Üçüncü bir alan; q2
tabloların hesaplandığını gösterir, söylediklerini değil. Dahil edilen eserlerin doğruluğu (referans listesiyle
örtüşme %38–48, liste eksik ve model kökenli). Referans kümelerinin kütüphaneler arası tekrarından gelen bağımlılık.
Eskime ve liste düzenlemesi durumları saklı veride yok (revizyon değişen kütüphane yok); yalnız testlerle sınanır.
Planın bütün sayıları saklı kütüphanelerden; canlı koşu yok.
