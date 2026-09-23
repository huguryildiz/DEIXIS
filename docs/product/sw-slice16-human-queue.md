# SW dilim 16 — İnsan kuyruğu (arka uç)

**Tarih:** 24 Eylül 2026. **Durum:** plan yazıldı, sahip onayı bekliyor. **Plan promptu:**
[sw-slice16-plan-prompt.md](sw-slice16-plan-prompt.md). **Ana dosya:** [sw-status.md](sw-status.md). **Karar:** D96
(dilim yazar). **Önkoşul:** 12 (kapandı, D85); 15 kapandı (D95). **Tür:** Kur. **Uygulayan:** Opus · high.
**İnceleme:** tam (karar sessizce kanıtı bozabilir: kullanıcının kararı seçimlere, okuma planına ve özet okumasına
dokunur). **Plan:** Opus 5.5 · high, 24 Eylül 2026 (prompt Fable · high diyordu; bu oturum Opus'ta koştu).
**Ölçüm:** `.local/sw-slice16-queue-measure-2026-09-24/` (`protocol.md`, `result.md`, `table.md`, betikler).
**İkinci görüş:** `gpt-6-sol` · high, salt okunur (`sol-review.md`; testleri koşamadı). Sol yedi kararın ikisine
katıldı, beşine itiraz etti. İtirazların hepsi aşağıya işlendi (karar 1, 3, 4, 5, 7 ve Task 2, 4); sıra kararında
(5) Sol'un önerisi alındı.

**Goal:** SW11.4–7, 11.10–11 ve 11.13'ün arka ucunu kurar. Dilim 12'den beri beş neden kodu (ve
`pdf_identity_unconfirmed`) işleri `human_queue`'ya yolluyor, ama onları okuyan bir şey yok. Bu dilimden sonra kod
kuyruğu saklı kararlardan türetir. Her satır tek bir soru sorar ve alıntıyı, sayfayı, sürüm etiketini taşır. Kişinin
cevabı `stage_decisions`'a `decided_by = 'human'` olarak yazılır ve seçime ulaşır. Cevap kesindir, geri alınabilir, o
eser için model bir daha sorulmaz. Ölçüt değişince karar silinmez, "eski ölçütle verildi, yeniden bak" diye işaretlenir.
Ekran yok (dilim 17). Keşif, getirme ve okuma sonuçları değişmez.

## Elimizdeki sayılar

Ölçüm yalnız saklı kütüphanelerde koştu: dilim 15 kabulünün 11 kütüphanesi (kuantum 7, paket 4), yan kontrol olarak
14a'nın 2'si ve üçüncü D88 ölçümünün 3'ü. Ağ yok, model yok. Kod × efor tablosu `table.md`'de, ayrıntı `result.md`'de.

1. **Okuma sınırı hiçbir uygun eseri dışarıda bırakmadı.** 16 kütüphanenin hiçbirinde okunmayı bekleyen metin kalmadı
   (`not_read_yet` 0, `not_reached` 0); bir `standard` koşusunda okunabilir eser tam 50 / 50 idi. Getirme
   okumaya sınırdan az metin veriyor: `quick` 27–29 / 40, `standard` 45–53 / 50, `detailed`
   126–140 / 150, paket `quick` 5–8 / 40. Prompt'un "çoğu iş okuma sınırında kalır" varsayımı tutmadı: açık kalan
   eserleri kararsızlık değil, önceki sınırlar ve eksik metin bırakıyor. Örnek, kuantum `standard` (~3.100 eser):
   ~2.200 özeti okunmadı (`abstract_not_read`), ~450–600 getirme planına girmedi, 65–77'nin açık metni yok
   (`no_fulltext`, dilim 18'in listesi).
2. **Kuyruk bugün şu kadar satır tutardı** (eser başına bir satır): kuantum `quick` 8 ve 21, `standard` 15, 30 ve 40,
   `detailed` 90 ve 100; paket `quick` 1, 3, 3 ve 4. Zincirle gelen eserlerin satırı: `quick` 0–2, `standard` 3–11,
   `detailed` 5–12. Kuantum `detailed`'da okunan 137 eserin 100'ü kuyrukta. SW11'in 160 eserde 140 satırlık eski
   kuyruğunun kusuru ("liste kuyruk olmuş") başka bir yoldan geri geliyor.
3. **Satırların üçte ikisi `part_without_evidence`**, sebebi ölçütün biçimi. 315 satırın 223'ü bu kodla geliyor. Bu
   satırlarda iki koşunun da `present` dediği parça hemen her zaman konu parçası ("end-to-end entanglement
   distribution", "distribution task"). Modelin önerdiği ölçüt, SW15.1'e aykırı olarak, 7 kuantum koşusunun 5'inde
   böyle bir parça taşıyor. O zaman formülasyon içermeyen her konu makalesi `partial` olur ve `criterion_absent` yerine
   kuyruğa düşer. Ölçütü konu parçası taşımayan iki koşunun kuyruğu 8 ve 15 satır.
4. **Gerçek karar isteyen satır üçte bir.** Farklı eserlerden sabit bir örnek (74 eser) satır satır okundu:
   | neden | okunan | gerçek soru | cevap belli "hayır" | cevap belli "evet" | yanlış PDF |
   |---|---:|---:|---:|---:|---:|
   | `part_without_evidence` | 25 | 9 | 16 | 0 | 0 |
   | `fulltext_runs_disagree` | 20 | 13 | 4 | 3 | 0 |
   | `include_quote_unverified` | 18 | 2 | 0 | 16 | 0 |
   | `pdf_identity_unconfirmed` | 8 | 0 | 0 | 8 (doğru PDF) | 0 |
   | `fulltext_runs_agree_unresolved` | 3 | 0 | 3 | 0 | 0 |

   Doğrulanamayan 18 alıntının 16'sı gösterilen sayfada bulanık eşleşmeyle duruyor (oran 0,94–0,998; satır
   numaraları, glifler, satır sonu). 8 kimlik satırının 8'inde PDF doğru makale (tire, İngiliz yazımı, kısa başlık,
   çeviri). "Bir parça iki koşuda da `absent` ise `criterion_not_met`" kuralı `part_without_evidence` satırlarının
   %37'sini kapatırdı, ama bir koşuda doğrulanmış g087'yi dışlardı. SW16.3'ün kendi ölçütüyle (doğrulanmış kayıtta
   yanlış kapatma yok) bu kural geçmiyor.
5. **Satırın verisi saklı, iki parça hariç.** 315 satırın hepsinde sürüm etiketi var. Doğrulanmış her alıntının
   sayfası, her önerinin pasajı saklı. Modelin gerekçe cümlesi yalnız adım çıktısında duruyor. Saklı olmayan iki şey
   sunarken hesaplanabilir: "hayır" için ipucu cümleleri (299 satırın 39'unda metinde hiç ipucu ifadesi yok) ve
   reddedilen alıntının en yakın pasajı (58 alıntının 50'sinde gösterilen sayfada bulanık eşleşme var, 8'inde yok).
6. **Sıra.** Kuyruktaki 37 doğrulanmış kuantum eserinin (11 kütüphane) 8'i birleşik sırada ilk 10 satırda, 19'u ilk
   20'de. Önce iki koşunun da dahil dediği satırlar, sonra birinin dediği, sonra kimlik, sonra parça; her grup kendi
   içinde birleşik sırayla dizilince ilk 10'da 18, ilk 20'de 25. Nedene göre doğrulanmış payı:
   `include_quote_unverified` 6 / 21, `fulltext_runs_disagree` 10 / 45, `part_without_evidence` 12 / 221. Tek konu, aynı
   eserler birden çok koşuda: bağımsız bir doğrulama değil.
7. **SW maddeleri.** Özet aşaması kimseyi kuyruğa göndermiyor (SW11.4): kodda doğru. SW5.4'e bugün ulaşılamıyor,
   çünkü kapı kapalı ve derlemeler getirilmiyor (16 kütüphanede metni olan derleme 0). SW6.6'nın verisi var
   (araştırma başına 2–16 açık `probable_version` bağı) ama hiçbir aşama kararı onu kuyruğa yollamıyor. Kapı–model
   çelişkisine ve `abstract_promise_absent`'e de ulaşılamıyor: kapı kapalı, kod kurulmadı.

## Sahibin vereceği kararlar

1. **Kuyruğun nedenleri: bugünkü altı kod ve `versions_disagree` girer, bu dilimde hiçbiri kuralla kapatılmaz.**
   Öneri böyle. Gerekçe: bu dilim okuma sonucunu değiştirmemeli. Sayıyı en çok düşürecek kural ("bir parça iki
   koşuda da `absent`") doğrulanmış bir eseri kaybediyor. `fulltext_runs_agree_unresolved` (3 eser, üçü de "hayır"
   gibi) girer: kuralla kapatmak, yöntem dosyasının "başka yerde olabilirse `unclear` de" talimatını geri almak olur.
   SW maddeleri tek tek:
   - SW1.6, iki koşu anlaşmazlığı: **girer** (`fulltext_runs_disagree`).
   - Kapı–model çelişkisi: **ulaşılamaz**, kapı kapalı (SW16). Kapı açılırsa (dilim 23) kod o dilimle gelir.
   - SW5.4: **ulaşılamaz**, derleme getirilmiyor, kapı yok.
   - SW6.6, `probable_version`: **bu dilimde yok.** Soru "bu iki kayıt aynı eser mi" sorusu; cevabı bir bağ
     kaydıdır (`record_links`, `links.py`'nin geri alma yolu), aşama kararı değil. Ayrı iş olarak yazılır.
   - `versions_disagree` (saklanmaz, `work_outcome` iki sürümün taze kararından türetir; 16 kütüphanede 0): **girer**,
     ama saklı bir kararı yok. Sol'un bulgusu. Kişinin kararı satırın adını verdiği sürüme (dahil eden sürüm) yazılır;
     `work_outcome` insan kararını her sürümün önünde okuduğu için eser bununla çözülür. Çakışma jetonu tek bir karar
     kimliği değil, eserin bütün sürümlerinin güncel tam metin kararlarıdır (karar 7). İki sürümlü çatışma adıyla
     sınanır.

   Kuyruğu küçültecek üç düzeltme bu dilimin değil, sebebi başka adımlarda. K8'in ruhuyla ayrı iş olarak yazılır
   (sahip sırasını seçer; hiçbiri 16'yı bekletmez):
   - (a) **Ölçütte konu parçası** (dilim 06'nın alanı, SW15.1). En büyük kazanç burada.
   - (b) **Alıntı doğrulaması satır numarasını ve glifleri kaçırıyor** (dilim 12). 18 satırın 16'sı.
   - (c) **Kimlik denetimi tireyi, İngiliz yazımını ve kısa başlığı kaçırıyor** (dilim 10). 8 satırın 8'i.
2. **Satır: yeni tablo yok, yeni saklanan alan yok; kuyruk saklı kararların görünümüdür.** Öneri: satır her okunuşta
   `work_outcome`'dan türetilir. Saklı veriden okunanlar: öneriler, alıntı, doğrulama, sayfa ve pasaj
   (`model_proposals`), gerekçe (adım çıktısı), gösterilen sayfalar (StepInput), sürüm etiketi (`source_versions`),
   ölçüt (plan adımında donmuş). Sunarken hesaplananlar: soru, ipucu cümleleri ve sayfaları, en yakın pasaj.
   Gerekçe: kuyruğun ayrı bir kaydı ölçüt ya da revizyon değişince eskir. Türetilen görünüm eskiyemez. Hesaplananlar
   yalnız satır ayrıntısında (tek eser) çalışır, liste hafif kalır.
3. **Karar: `stage_decisions` ve `selections` ikisi birden, tek işlemde.** Öneri:
   - İnsan kodu, kuyruk satırının kararının yazılı olduğu sürüme (okunan sürüm) yazılır. Oradaki kod kararını
     kapatır, geçmiş tek sürümde kalır. Bu sürüm çoğu zaman baş kayıt değildir (315 satırın 164'ü); seçim yine baş
     kayda yazılır.
   - `human_include` ve `human_criterion_not_met` işin baş kaydının seçimini `origin = 'user'` ile `included` ya da
     `excluded` yapar: `set_user_selection`'ın geçmiş satırı, seçim revizyonu ve olayı, gerekçe olarak insan kodu.
     Gerekçe: yanıtın okuduğu tek şey `selections` (§2 kural 2). Kullanıcının kararı her yerde "kullanıcının"
     görünmeli, `answer_order_facts` onu kullanıcı seçimi saymalı.
   - `human_not_sure` ve `human_pdf_wrong` yalnız aşama kararını yazar. Seçimi `derive_selection` `pending` türetir.
   - Geri alma: `undo_human` (dilim 02) insan kararını kapatır, önceki kod kararını kendi revizyonu ve özetleriyle
     geri getirir. Seçim yalnız bu kararın yazdığı seçim hâlâ yerindeyse bırakılır. Sol'un bulgusu: "son değişiklik"
     tahmin edilmez, bağ saklanır. Migration `0051` `stage_decisions`'a iki sütun ekler: `selection_head` ve
     `selection_version` (kararın yazdığı seçim satırının baş kaydı ve sürüm numarası). Geri almada o baş kaydın
     seçimi hâlâ o sürümdeyse `origin` `code_rule` olur ve `derive_selection` yeniden türetir. Kaynak listesinden
     yapılan her değişiklik, aynı duruma olsa da, sürümü artırır ve kazanır. Baş kayıt değiştiyse
     (`_settle_work_head` kullanıcının seçimini yeni başa taşır) seçime dokunulmaz, bunu son ileti ve yanıt söyler.
     Satır kuyruğa geri döner.
   - Kimlik satırı için beşinci cevap önerilir: **"PDF doğru, model okusun"**. 8 kimlik satırının 8'inde PDF doğru;
     bu cevap olmadan kişi dahil etme kararını PDF'i kendisi okuyarak vermek zorunda kalır. Bu bir dahil etme kararı
     değildir: model okur. SW11.7'nin "bir daha sorulmaz" kuralı dahil etme kararına aittir. Sol'un bulgusu üzerine
     sözleşme şöyle:
     - Onay dosyaya bağlı ve açık kayıtlıdır: migration `0051` `source_assets`'e `identity_confirmed_at` ekler.
       Yalnız o anda okunan sürümün güncel dosyası onaylanabilir (jeton dosya kimliğini taşır). Dosya sonradan
       değişirse yeni dosyanın işareti yoktur, kimlik yeniden denetlenir.
     - `_user_supplied_pdf` onaylı dosyayı da muaf sayar. `pdf_identity_unconfirmed` kararı kodla, `not_read_yet`
       ile kapanır. Notu makine okunur: `pdf_confirmed:<asset_id>`. Bu, adım dışında yazılan tek kod kararıdır
       (`step_id` NULL), sebebi nottan ve dosyanın işaretinden okunur.
     - Geri alma yalnız güncel karar hâlâ o `not_read_yet` ise: işaret silinir, `pdf_identity_unconfirmed` kodla
       yeniden yazılır. Okumadan sonra geri alma yok, kişi eser hakkında karar verir.
     - Okuma koşusunu bu dilim kendiliğinden başlatmaz.

     Seçenek: beşinci cevap olmadan kurmak (migration `0051` yine gelir, yalnız iki `stage_decisions` sütunuyla). O
     zaman 8 satırın her biri kişinin PDF'i okumasını ister.
   - **Model bir daha sorulmaz.** Getirme ve okuma planı bunu bugün `fulltext.group_of` ile sağlıyor. İki açık yer
     var:
     - Özet okuması: `abstract_stage.read_plan` yalnız özet aşamasındaki insan kararına bakıyor. Aynı revizyonda
       sonraki bir keşif koşusu ya da zincirin özet okuması (`_abstract_stage(chain=…)`, aynı işlev), tam metni kişi
       tarafından karara bağlanmış bir eserin özetini modele yeniden yollayabilir. Dilim bunu kapatır: herhangi bir
       aşamada insan kararı olan eser özet okumasına girmez.
     - **Uçuştaki koşu** (Sol'un bulgusu): okuma koşusu planını dondurur ve işleri gönderirken insan kararına yeniden
       bakmaz (`flow.py` `_fulltext_adjudication` `jobs()` / `call()`). Kişi koşu sürerken karar verirse model yine
       çağrılır. Dilim gönderim anında denetim ekler: işin herhangi bir sürümünde insan tam metin kararı varsa çağrı
       yapılmaz, iş özette `human_decided` sayılır, bütçeye yazılmaz. Özet okumasında da parti gönderilmeden önce
       kararlı kayıtlar partiden çıkar; gönderilen liste StepInput'ta saklanır, plan adımı değişmez.
   - `human_not_sure` ve `human_pdf_wrong` eserleri kuyruğa kendiliğinden dönmez: kodun sonraki adımı `none` ya da
     `waiting_for_pdf`'tir, `human_queue` değil (SW11.11). `human_pdf_wrong` iş PDF bekleyenler listesine (dilim
     18) düşer. Dilim 18'in bu işi kullanıcının PDF'iyle yeniden açma yolu o dilimin işidir; `group_of` insan kararlı
     işi getirmez, 18 bunu bilerek kurmalı.
4. **Eskime: saklanan bir şey değişmez, görünüm ayırır.** Karar `record`'un bugün yazdığı revizyon, protokol özeti ve
   ölçüt özetiyle saklanır (D71). Soru ya da ölçüt değişince:
   - açık kod satırları kuyruktan çıkar: eskimiş kod kararı `work_outcome`'da konuşmuyor (D85.6), iş özet sonucuna
     döner, sonraki okuma koşusu yeni ölçütle okur;
   - eskimiş insan kararı sayılmaya devam eder (yanıt, seçim), kuyruğun sonunda ayrı bir tür olarak listelenir:
     `look_again`, "eski ölçütle verildi, yeniden bak";
   - aynı cevabı yeniden vermek taze bir karar yazar (`record` protokol özeti değişince yeni satır açıyor), başka
     cevap vermek eskisini kapatır.

   - Satır sunulduktan sonra revizyon değişirse o satıra verilen cevap reddedilir (409): jeton revizyonu ve ölçüt
     özetini taşır (karar 7, Sol'un bulgusu). Aksi hâlde eski satırın sorusuyla yeni revizyonda taze bir insan kararı
     yazılırdı.

   Bu madde için saklanan yeni bir şey yok. Gerekçe: eskime D71'den beri hesaplanıyor. Kuyruğun ayrı bir durumu olsaydı
   iki yer tutarsız kalabilirdi. Eskimiş bir insan `include`'u yanıtta dahil kalır (SW11.10: saklanır, taşınmaz ama
   silinmez); yanıtın ve raporun bunu işaretlemesi dilim 20'nin akış sayılarının işidir.
5. **Sıra ve boy: birleşik sıra (SW11.7), sınır yok; soru türü satırda alan olarak durur.** Birleşik sıra: anahtar
   sözcük eserleri son `code:ranking` sırasıyla, zincir eserleri arkadan `code:chain_ranking` sırasıyla (okuma
   planının sırası, D95). Eşitlikte baş kimliği. `look_again` en sonda. İlk önerim, önce soru türüne göre gruplamaktı
   (iki koşunun da dahil dediği → birinin dediği → sürüm → PDF → parça bul → yokluğu onayla); doğrulanmış eserleri ilk
   10'da 8'den 18'e çıkarıyordu. Sol itiraz etti: kazanç tek konuda, aynı eserlerin koşular arasında tekrarlandığı 37
   satırda ölçüldü, bağımsız değil. Ortak karar: SW11.7 olduğu gibi kalır. Tür her satırda `kind` alanıdır, dilim 17
   ekranda onunla süzebilir. Türe göre sıra dilim 24'te ikinci soruyla ölçülür. Sınır önerilmiyor: en büyük kuyruk 100
   satır, sınırla kesmek karar vermeden eser düşürmek olur. Boyut ve nedenler özette raporlanır.
6. **Doğrulanmış sayılan: yalnız `human_include` ve `human_criterion_not_met`; bu dilim yalnız sunar, tüketen 19'dur.**
   `queue.verified_records(store, rid)` bu kararları eser, sonuç, ölçüt özeti, revizyon ve eskime işaretiyle
   döndürür. Prob seti ve SW2.5'in sözcük kuralı dilim 19'da onu okur. Hiçbir eşik, kural ya da sabit bu kayıtlarla
   değişmez (SW11.13). `human_not_sure` ve `human_pdf_wrong` doğrulanmış sayılmaz. Kişinin kodu ya da modeli kaç kez
   ezdiği (SW11.13 son cümle) dilim 20'nin sayısıdır. Veri burada saklanır: insan kararının kapattığı kod kararı.
7. **API: dört uç nokta, hepsi `sw`'ye özel.** Loopback ve Host / Origin izin listesi mevcut ara katmanda; değişiklik
   yapan ikisi çift gönderimli CSRF'ten geçer. Yeni istisna yok.
   - `GET /api/researches/{rid}/queue` → `{"rows": [...], "counts": {"open", "by_kind", "by_reason", "look_again",
     "decided": {kod: n}}, "order": "fused_rank"}`. Satır: `source_version_id` (kararın sürümü), `head`,
     `work_id`, başlık / yıl / DOI, sürüm etiketi ve yayın türü, `reason_code`, `kind`, `question` (`part`,
     `definition`), `place`, `arm` (`keyword` | `chain`), `stale`, `decision_id`.
   - `GET /api/researches/{rid}/queue/{source_version_id}` → satır + ayrıntı: iki koşunun parça başına etiketi,
     alıntısı, doğrulaması, sayfası, pasajı ve gerekçesi; gösterilen sayfalar; doğrulanmamış her alıntı için en yakın
     pasaj (yalnız gösterilen sayfalarda, `locate_anchor`; yoksa `null` ve "gösterilen sayfalarda yakın metin yok");
     soru parçası için ipucu cümleleri ve sayfaları (en çok 5, toplam sayı; yoksa "ipucu bulunamadı"); kimlik satırında
     PDF'in ilk sayfası ve eserin başlığı / DOI'si, dosyanın geldiği adres, sayfa sayısı.
   - `POST /api/researches/{rid}/queue/{source_version_id}/decision` gövde `{"decision": "include" |
     "criterion_not_met" | "not_sure" | "pdf_wrong" | "pdf_confirmed", "note": str ≤ 1000 | null,
     "row_token": str}` → güncel satır ya da `null` (satır kuyruktan çıktı) ve seçim. `legacy` ya da üye olmayan
     kayıt → 422.
   - **`row_token`** (Sol'un bulgusu: tek karar kimliği yetmiyor). Satır sunulurken hesaplanır, cevapta sunucu
     yeniden hesaplar, tutmazsa 409. İçeriği: araştırmanın güncel revizyonu, ölçüt özeti, eserin bütün sürümlerinin
     güncel tam metin kararlarının kimlikleri (sıralı), baş kaydın seçim sürümü, kimlik satırında okunan sürümün güncel
     dosya kimliği. Böylece arada gelen revizyon, okuma koşusunun yazdığı karar, kaynak listesinden seçim değişikliği ya
     da dosya değişikliği cevabı düşürür.
   - `POST /api/researches/{rid}/queue/{source_version_id}/undo` gövde `{"row_token"}` → 409, güncel karar o insan
     kararı değilse ya da jeton tutmazsa.
   - `research_view.counts`'a `queue` ve `look_again`. Maliyet: `facts` bir kez. Dilim 13d'nin ölçtüğü 3.000 eserlik
     görünüme eklenen süre son iletide yazılır.

## Global constraints

- **Yalnız `sw`.** `legacy` araştırmada uç noktalar 422 döner. `legacy` görünümü byte byte aynı kalır.
- **Keşif, getirme, okuma ve yanıt sonuçları değişmez.** İnsan kararı olmayan bir araştırmada hiçbir adımın girdisi,
  çıktısı ya da bütçesi değişmez. Davranış değişiklikleri yalnız insan kararlı işe dokunur: özet okuma planı, gönderim
  anındaki iki denetim ve (beşinci cevap kabul edilirse) onaylı PDF'in kimlik muafiyeti.
- **Model sözleşmesi ve yöntem paketi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır. Yeni neden kodu yok. Dört insan kodu
  dilim 02'den beri tabloda. Tek şema değişikliği migration `0051` (karar 3). Başlamadan kontrol: son migration
  `0050`, son karar D95.
- **Kullanıcı üstündür.** Kod ve model insan kararını ezmez (`HumanDecisionStands`). Seçimi kullanıcının verdiği
  (`origin = 'user'`) işin satırı kuyrukta yer almaz: kişi kararını kaynak listesinden vermiş. Sayısı `counts`'ta
  ayrıca yazılır.
- **Okumak adım açmaz** (Ders C). Kuyruk uç noktaları ve görünüm `store.step` çağırmaz, `pending` adım bırakmaz,
  hiçbir şey yazmaz.
- **Tek işlem, içinde `await` yok.** Karar, seçim, geçmiş ve olay (`stage_decision_recorded`) aynı kısa işlemde
  yazılır (`transaction` iç içe kullanımda dıştakine katılır). İşçi aynı anda okuma koşusu yürütüyor olabilir. Okuma
  koşusu, gönderim anındaki yeni denetimle (karar 3), insan kararlı işi atlar. İyimser kilit `row_token` ile (karar 7).
- **Konuya özgü hiçbir şey yok.** Soru, ipucu ve sıra ölçütün parçalarından ve saklı sıralardan gelir. Parça adı ya da
  sözcük koda girmez. Testlerde fikstürler SYNTHETIC ve en az iki alandan, ağ yok.
- Ayrıntıda hesaplanan her şey (ipucu cümlesi, en yakın pasaj) sayfa metninden okunur ve sonucu değiştirmez.
  Yalnız gösterir.

## Task 1: kuyruk görünümü (`workflow/queue.py`)

- `queue_rows(store, rid) -> {"rows", "counts"}`: `DecisionStore.facts` bir kez; her iş için `work_outcome`. Satır:
  sonucun kodu `human_queue`'ya gidiyor ya da `versions_disagree`; baş kaydın seçimi `origin = 'user'` değil. Ayrı
  tür olarak eskimiş insan kararları (`look_again`). Her satır tek bir anlık görüntüden türetilir (tek okuma
  işlemi) ve `row_token`'ını taşır.
- `kind`: `include_quote_unverified` → `confirm_quote`; `fulltext_runs_disagree` → `choose_run`;
  `versions_disagree` → `choose_version`; `pdf_identity_unconfirmed` → `confirm_pdf`; `part_without_evidence` →
  `confirm_absent` (bir parça iki koşuda da `absent`), yoksa `find_part`; `fulltext_runs_agree_unresolved` →
  `find_part`.
- `question`: ölçütün parça sırasında, iki koşunun `present` + doğrulanmış alıntıda anlaşmadığı ilk parça. `confirm_quote`'da
  doğrulanmamış alıntılı ilk parça; `confirm_pdf`'te parça yok.
- Sıra karar 5'teki gibi: birleşik sıra, eşitlikte baş kimliği.
- `row_detail(store, rid, svid)`: karar 7'deki alanlar. İpucu cümleleri dilim 11'in `compile_phrases` desenleriyle,
  yalnız soru parçasının ifadeleriyle bulunur. Parçasız ifadeler hiçbir parçaya yazılmaz. En yakın pasaj
  `contracts.locate_anchor` ile ve yalnız o koşuya gösterilen sayfalarda aranır.
- `verified_records(store, rid)`: karar 6.

## Task 2: karar ve geri alma

- Migration `0051_human_queue.sql`: `stage_decisions.selection_head TEXT`, `stage_decisions.selection_version
  INTEGER`; beşinci cevap kabul edilirse `source_assets.identity_confirmed_at TEXT`. Eski satırlar NULL kalır.
- `queue.decide(store, rid, svid, decision, note, row_token)`: jetonu yeniden hesaplar (tutmazsa 409), sonra tek
  işlemde insan kodu → seçim (`include` / `criterion_not_met`) → `selection_head` / `selection_version` → geçmiş →
  olay. `record`'a insan kodu yazarken bu iki sütunu dolduran bir yol eklenir; kod kararları için NULL kalır.
- `queue.undo(store, rid, svid, row_token)`: `undo_human` ve karar 3'teki seçim bırakma kuralı. Yeni
  `store.release_user_selection(rid, head, expected_version)` yalnız seçim o sürümdeyse yazar, sonra
  `derive_selection`.
- `pdf_confirmed` (karar 3 kabul edilirse): `flow._user_supplied_pdf` onaylı dosyayı muaf sayar; kimlik kodu
  `not_read_yet` ile (not `pdf_confirmed:<asset_id>`) kapanır; geri alma karar 3'teki gibi.
- `abstract_stage.read_plan`'in eser satırına tam metin aşamasındaki insan kararı da gelir. Keşif ve zincir özet
  okuması aynı işlevi çağırıyor, ikisi de sınanır.
- Uçuştaki koşu: okuma koşusunun `jobs()` / `call()` yolu ve özet aşamasının parti gönderimi, göndermeden hemen önce
  insan kararını yeniden okur (karar 3). Okuma özetine `human_decided` sayısı eklenir.

## Task 3: API

Karar 7'deki dört uç nokta ve `research_view.counts`. Pydantic gövdeleri `SelectionChange` kalıbında
(`note` ≤ 1000). `api.ts`'e tipler eklenir (ekran yok, dilim 17). `origin` tipi `code_rule`'u zaten biliyorsa dokunulmaz.

## Task 4: testler (önce başarısız test)

`tests/test_queue.py` (saf ve depo), `tests/test_queue_api.py` (`create_app` ile). Adıyla:

- `test_each_human_queue_code_is_one_row_per_work_and_no_other_code_is`
- `test_a_work_whose_selection_the_user_set_is_not_in_the_queue`
- `test_rows_are_ordered_by_fused_rank_with_chained_works_after_keyword_works`
- `test_the_row_question_names_the_first_part_the_runs_did_not_settle`
- `test_part_without_evidence_splits_into_confirm_absent_and_find_part`
- `test_the_closest_passage_is_searched_only_on_the_pages_that_run_was_shown`
- `test_cue_sentences_come_with_their_pages_or_the_row_says_none_were_found`
- `test_reading_the_queue_opens_no_step_and_writes_nothing`
- `test_a_human_include_reaches_selections_as_the_users_and_a_later_reading_run_does_not_touch_it`
- `test_a_human_decision_keeps_the_work_out_of_the_abstract_read_the_chain_read_the_fetch_plan_and_the_reading_plan`
- `test_not_sure_and_pdf_wrong_leave_the_work_pending_and_do_not_return_to_the_queue`
- `test_undo_brings_back_the_code_decision_and_the_row_and_releases_the_selection_only_if_unchanged_since`
- `test_after_a_scope_revision_code_rows_leave_and_a_human_decision_is_listed_as_look_again_and_still_counts`
- `test_answering_a_look_again_row_again_writes_a_fresh_decision`
- `test_a_row_token_is_rejected_after_a_scope_revision_a_new_code_decision_a_selection_change_or_a_new_pdf`
- `test_a_versions_disagree_row_is_decided_on_the_named_version_and_resolves_the_work`
- `test_a_decision_on_a_non_head_version_sets_the_heads_selection_and_undo_releases_it`
- `test_undo_leaves_a_selection_the_user_changed_since_even_to_the_same_state`
- `test_a_work_decided_while_a_reading_run_is_in_flight_gets_no_model_call`
- `test_a_record_decided_while_a_discovery_run_is_in_flight_is_left_out_of_the_next_abstract_batch`
- `test_queue_endpoints_refuse_legacy_and_mutations_need_the_csrf_header`
- `test_pdf_confirmed_lets_the_next_reading_run_read_the_work_and_can_be_undone_before_it_does` (karar 3 kabul
  edilirse)
- `test_verified_records_lists_only_human_include_and_criterion_not_met`
- `test_research_view_counts_the_queue`
- `tests/determinism_stages.py`'ye `queue` aşaması: karışık karar kümesi, iki hash tohumu, aynı satırlar aynı sırada.

## Task 5: kabul (K8) ve kapanış

- Karar, geri alma, revizyon ve eşzamanlılık yolları bu kabulde değil, Task 4'ün adıyla sayılan testlerinde sınanır
  (Sol'un bulgusu: saklı kütüphanelerin yeniden oynatması yalnız sınıflandırmayı sınar).
- **Yeniden oynatma, modelsiz (zorunlu).** `.local/sw-slice16-acceptance-<tarih>/`. `queue_rows`, dilim 15 kabulünün
  11 kütüphanesinde salt okunur bağlantıyla çalıştırılır. Satır sayısı ve neden dağılımı bu planın ölçümüyle birebir
  aynı olmalı (`counts.json`: kuantum `quick` 21 / 8, `standard` 40 / 15 / 30, `detailed` 100 / 90; paket 4 / 1 / 3 /
  3). Fark dilimi düşürür, çünkü görünüm aynı kararları okuyor.
- **Canlı koşu, bir tane.** Kuantum `quick`, `gpt-5.6-luna` · medium, D94 / D95 kabulünün düzeni (kendi sunucusu, boş
  veri dizini, 8765 değil, gömme `off`, onay `as_proposed`). Beklenti ilk istekten önce `protocol.md`'ye yazılır.
  Karşılaştırılan önceki koşu dilim 15'in `q1-quick-q12`'si: doğrulanmış eser havuzda / planda / okunan 22 / 11 / 7,
  dahil 14, kuyruk 8. K8: havuz, plan, okunan her biri en çok 2 eksik. Dilim bu yollara dokunmadığı için daha büyük
  düşüşün sebebi ancak model değişkenliği olabilir. O zaman dilim geçer, sebep ayrı iş olarak yazılır; tartışmalı
  durumda koşu iki kez yapılır, iyisi alınır. Kuyruk, o kütüphanede `human_queue`'ya giden işlerle birebir aynı olmalı.
- **Canlı kütüphanede karar turu.** Koşu bittikten sonra API'yle: bir satıra `include`, birine `criterion_not_met`,
  birine `not_sure`; birini geri al; varsa bir kimlik satırına `pdf_confirmed`. Sonra aynı kapsamda yeni bir okuma
  koşusu başlatılır. Kararlı eserler için model çağrısı 0, onaylı PDF'li eser için 2. Seçim, geçmiş ve sayılar
  `result.md`'ye yazılır.
- D96 `docs/decisions.md`'nin en üstüne (Status / Date / Context / Decision / Limits). SW11'in durum satırı güncellenir.
  Karar 1'in üç ayrı işi (a, b, c) ve SW6.6 `sw-status.md`'ye ayrı satır ya da not olarak yazılır.
- Tam pytest (bilinen tek başarısızlık aynı); `npm run build && npm run lint` (yalnız `api.ts` değişti);
  `git diff --check`; satır 16 → `uygulandı, inceleme bekliyor`; tek commit; push.

## Bu dilimde yok

- Kuyruk ekranı, PDF'i sayfada açmak, süzgeçler (dilim 17).
- Kuyruğu küçültecek üç düzeltme: ölçütte konu parçası, alıntı doğrulamasının satır numaraları, kimlik denetimi
  (karar 1, a–c; ayrı işler).
- "Bir parça iki koşuda da `absent` → `criterion_not_met`" kuralı (doğrulanmış eser kaybediyor).
- SW6.6 `probable_version` soruları, SW5.4 (ulaşılamaz), kapı–model çelişkisi (dilim 23).
- PDF bekleyenler listesi ve kullanıcının eklediği PDF, `human_pdf_wrong` işin yeniden açılması (dilim 18, SW11.9).
- Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S (dilim 20); prob seti ve sözcük kuralı (dilim 19).
- Onaylı PDF'ten sonra okuma koşusunu kendiliğinden başlatmak; getirmenin keşifle üst üste binmesi (17a).
- Mevcut `PATCH /selections`'ın aşama kararı yazması. Kaynak listesinden verilen karar bugünkü gibi yalnız seçimdir.
  Dilim 20'nin ezme sayısı iki kaynağı da okumalı.

## Ölçülmedi

- Satır başına dakika; ipucu cümlelerinin ve en yakın pasajın kişiye gerçekten yardım edip etmediği (SW11 Limits).
- "Gerçek soru / belli cevap" ayrımı tek okuyucunun yargısı (bu plan oturumu). Pasajlara ve alıntılara bakıldı, PDF'in
  tamamına değil. Bir kişiyle karşılaştırılmadı.
- Türe göre sıranın kazancı (karar 5'te bırakılan seçenek) yalnız kuantumda, 37 doğrulanmış satırla ölçüldü. Paket kuyruğu en çok 4 satır. Paketin 6
  model etiketli eserinden hiçbiri hiçbir koşuda okunmadı, yani paket kuyruğu hiçbir etiketle karşılaştırılamadı.
- İki konu, tek model (Luna medium). Ölçüt her araştırmada yeniden önerildiği için koşular arası karşılaştırma farklı
  ölçütleri karıştırıyor.
- Karar 1'in üç ayrı işinin kuyruğu ne kadar küçülteceği yalnız bu örnekten tahmin edildi: konu parçası olmayan iki
  koşu (8 ve 15 satır), alıntıda 18'de 16, kimlikte 8'de 8.
- `research_view`'a eklenen sayımın süresi.
