# SW dilim 17 — İnsan kuyruğu (arayüz)

**Tarih:** 24 Eylül 2026. **Durum:** yedi karar Claude ile `gpt-5.6-sol` · medium arasında ortak karara bağlandı (sahibin isteği, 24 Eylül 2026); 24 Eylül 2026'da uygulandı (D97), toplu inceleme bekliyor. **Prompt:** [sw-slice17-prompt.md](sw-slice17-prompt.md). **Ana dosya:** [sw-status.md](sw-status.md).
**Karar:** D97 (dilim yazar). **Önkoşul:** 16 (kapandı, D96, `311d3ca`). **Tür:** Kur. **Uygulayan:** Opus · medium
(satırdaki gibi). **İnceleme:** toplu (`gpt-5.6-sol` · high). **Plan:** Opus 5.5 · high, 24 Eylül 2026 (kural Fable ·
high diyor; bu oturum Opus'ta koştu). **Ölçüm:** `.local/sw-slice17-plan-2026-09-24/` (`shape.py`, `shape.json`).
**İkinci görüş:** `gpt-5.6-sol` · medium, salt okunur (`sol-medium.md`). Sol birinci karara katıldı, ikinciye itiraz
etti, beşini değişiklikle kabul etti; sekiz bulgusunun hepsi aşağıya işlendi. İtiraz ettiği karar 2 sahibe açık seçenek
olarak bırakıldı. Onay turunda (`sol-approval.md`) Sol karar 1, 3, 4, 5, 7'yi onayladı, 2, 6 ve fikstür planını
değişiklikle onayladı; karar 2'de öneri (a)'yı seçti. Claude dört değişikliği de kabul etti; tek fark `choose_version`
fikstüründe (aşağıda "Ortak kararlar").

**Goal:** SW11.6'nın ekranını kurar. Dilim 16'dan beri kuyruk arka uçta var: dört uç nokta, satır başına tek soru,
alıntı, sayfa, ipucu cümleleri, en yakın pasaj, geri alınabilir insan kararı. Ama ekranda hiçbir şey yok;
`research_view.counts.queue` yalnız bir sayı. Bu dilimden sonra kişi bir `sw` araştırmasında kuyruğu görür. Bir satır
seçer, sorusunu ve iki koşunun ne dediğini okur, PDF'i o sayfada açar ve beş cevaptan birini verir. Cevabını geri
alabilir. Keşif, getirme, okuma ve yanıt değişmez. Model sözleşmesi değişmez.

## Elimizdeki sayılar

Ölçüm saklı 13 kütüphanede, salt okunur, ağsız ve modelsiz yapıldı. Bunlar dilim 15 kabulünün 11 kütüphanesi ve dilim
16'nın iki canlı koşusu. `queue_rows` ve her satır için `row_detail` çağrıldı (`shape.py`).

1. **Kuyrukta 346 satır var.** Kuantum `quick` 8–21, `standard` 15–40, `detailed` 90–100; paket 1–4. Dilim 16'nın iki
   canlı kütüphanesi 15 ve 16 satır tutuyor; karar turundan önce 17 ve 18'di.
2. **Türlere göre dağılım** (satırın `kind` alanı): `find_part` 155, `confirm_absent` 98, `choose_run` 51,
   `confirm_quote` 25, `confirm_pdf` 17. `look_again` 0, `choose_version` 0. Satırların üçte ikisinden fazlası
   "parça bul / yokluğu onayla" türünde. Bunun sebebi ölçüte giren konu parçası (dilim 16 ölçümü, ayrı iş a).
3. **Bir satırın boyutu.** Başlık ortanca 75, en çok 138 karakter. Soru parçasının adı en çok 43, tanımı ortanca 162,
   en çok 252 karakter. Koşu başına 3–4 parça var. Bir satırın en uzun alıntısı ortanca 186, en çok 600 karakter;
   gerekçe en çok 255. Bir koşuya en çok 12 sayfa gösterilmiş. İki koşunun parça parça yan yana okunması 1050 px'te
   sığar, 390 px'te sığmaz.
4. **İpucu cümlesi çoğu satırda yok.** 346 satırın 243'ünde soru parçasının ifadeleri metinde hiç geçmiyor
   (`find_part` 155'te 110, `confirm_absent` 98'de 82). Ekran bu durumda "ipucu bulunamadı" demeli. Boş bir kutu, kişiye
   bir şey bulunmuş izlenimi verir.
5. **Doğrulanamayan alıntı 47 satırda var; en yakın pasaj bunların 40'ında bulundu.** Kalan 7'de
   `closest_note` "gösterilen sayfalarda yakın metin yok" diyor.
6. **Kimlik satırlarında (17) model okuması yok.** `runs` boş; ayrıntı yalnız PDF'in ilk sayfasını, eserin başlığını
   ve DOI'sini taşıyor.
7. **PDF her satırda var.** 346 satırın hepsinin sürümünde silinmemiş bir dosya duruyor. Her alıntının saklı bir pasajı
   var (`quote_passage_id` boş olan alıntı 0). "Satır seçilince PDF o sayfada açılır" için veri eksik değil, ama API
   bugün pasaj kimliğini ve dosya kimliğini döndürmüyor. Dönen yalnız pasaj metni, kimlik satırında da dosya (karar 6).
8. **Ayrıntının süresi.** `row_detail` ortanca 0,10 sn, %90'ı 0,31 sn, en çok 1,96 sn. 0,5 sn'yi aşan 9 satırın 7'si
   kuantum `detailed`'da. Liste 0,13–0,42 sn. Ayrıntı paneli bir yükleme durumu göstermeli; sıradaki satırı önceden
   çekmek bekleyişi saklar (Task 2).
9. **Sürüm etiketi.** Satırların 230'u `submittedVersion`, 101'i `publishedVersion`, 15'i `acceptedVersion`. Kuyruk
   çoğunlukla ön baskı okuyor; satırda sürüm etiketi `.ref-pill` ile görünmeli (§4.5).

## Sahibin vereceği kararlar

1. **Kuyruğun yeri: araştırma sekmelerinde ayrı bir sekme.** Öneri: yalnız `sw` araştırmasında görünen
   "Kararınızı bekleyenler" sekmesi. Kaynaklar'dan sonra, Kanıt'tan önce gelir; sayı hapı `counts.queue +
   counts.look_again`. Kuyruk boşken sekme kalır ve "Kuyrukta satır yok" der. Gerekçe: kuyruk kendi işi olan bir
   yüzey. Kaynaklar listesinin bir süzgeci olsaydı, satır başına soru ve iki koşunun yan yana okunması o listenin
   satır düzenine sığmazdı. Seçenekler:
   - (b) Kaynaklar sekmesinde bir süzgeç ve satırın altında açılan ayrıntı. Daha az yeni yüzey getirir, ama liste 3.000
     eser taşıyor ve kuyruk ondan kaybolur.
   - (c) Yanıt sekmesinde bir kart. Yanıt teslim edilen iştir (§1 ilkeler); süreç bir kat aşağıda durmalı.

   Giriş noktası ikinci bir yerde de var. Okuma koşusunun zaman çizelgesi turunda tek satır: "N eser kararınızı
   bekliyor · Aç". Yalnız sayı sıfır değilse görünür ve sekmeyi açar.
2. **Düzen: liste + ayrıntı; PDF, satırdan tek eylemle o sayfada açılır. Bu SW11.6'nın sözünden bilinçli bir
   sapmadır, sahip kabul ederse D97'ye yeni karar olarak yazılır.** SW11.6 "satır seçilince PDF o sayfada açılır"
   diyor. Öneri seçimi ve açmayı iki eyleme ayırıyor (Sol'un itirazı). Öneri:
   - 1050 px ve üstünde iki bölme. Solda ~360 px liste, sağda seçili satırın ayrıntısı.
   - Satır seçmek ayrıntıyı doldurur. "Sayfa N'i PDF'te aç" düğmesi (klavyede Enter) kaynak sayfasını
     (`PassageSheet`) `initialView='pdf'` ile o sayfanın pasajında açar. Kural 4.7'ye göre sayfa tam genişlikte açılır.
   - Satırın sayfası şu sırayla seçilir: soru parçasının alıntısının sayfası (önce 1. koşu, sonra 2.), en yakın
     pasajın sayfası, ilk ipucu cümlesinin sayfası, ilk gösterilen sayfa; kimlik satırında 1. sayfa.

   Gerekçe: SW11.6 "satır seçilince PDF o sayfada açılır" diyor. Tam genişlikte bir sayfa her seçimde açılırsa listeyi
   örter. Klavyeyle satır satır ilerlemek de bozulur: her ok tuşu bir PDF yükler. Ayrıntıda alıntı ve gerekçe zaten
   metin olarak duruyor, PDF bir tık uzakta. Seçenek (b), Sol'un tercihi: tıklamak ya da Enter satırı seçer ve sayfayı
   hemen açar; ok tuşları yalnız odağı taşır, seçmez. SW11.6'nın sözü aynen tutulur. Bedeli: tam genişlikteki sayfa
   ayrıntıyı ve cevap düğmelerini örter; kişi her satırda sayfayı kapatıp cevaba döner. Bu seçenekte cevap alt bilgisi
   kaynak sayfasının içine de konmalıdır, o da §3'teki "sayfa içinde sayfa açılmaz" kuralına yakın bir istisna ister. Seçenek (c): ayrıntının içine gömülü küçük bir PDF görünümü. Rule 4.7'deki "PDF'in
   kendi yüzeyi" düzenini ikiye böler, 390 px'te sığmaz.
3. **Vurgulama: yalnız arka ucun bulduğu çapa işaretlenir; doğrulanamayan alıntı ve en yakın pasaj işaretlenmez.**
   Öneri:
   - Doğrulanmış alıntı: arka uç sayfadaki eşleşmenin kendi metnini döndürür (`anchor_text`, karar 6). Sayfa bu
     metinle düz metin görünümünde açılır ve çapa işaretlenir. Modelin alıntısı `highlightText` olarak verilmez
     (Sol'un bulgusu: AGENTS.md kaynağın kendi, bitişik çapasını istiyor; `verify` bugün eşleşme metnini saklamıyor).
   - PDF görünümü sayfayı resim olarak çizer, metin işaretleyemez. "Sayfayı PDF'te aç" sayfayı işaretsiz açar; işaret
     yalnız "Düz metin" sekmesindedir. Ekran PDF'te işaret varmış gibi davranmaz.
   - Doğrulanamayan alıntı: modelin alıntısı ile en yakın pasaj ayrıntıda iki sütunda yan yana durur; üstlerinde
     "Modelin alıntısı metinde bulunamadı. En yakın metin yanında; eşleşme oranı 0,94" yazar. Sayfa açıldığında hiçbir
     metin işaretlenmez, şerit amber olur (§4.6'daki "işaretlenmedi, PDF'te denetleyin" kalıbı).
   - En yakın pasaj bulanık eşleşmeyle bulundu. Onu işaretlemek "bir aralığı tahmin etmek" olur ve AGENTS.md bunu
     yasaklıyor.
4. **Cevaplar: kind'a göre sıralı beş düğme, onay penceresi yok, geri alma bildirimde ve "Verdiğiniz kararlar"
   bölümünde.** Öneri:
   - Her satırda dört düğme: "Dahil et", "Ölçütü karşılamıyor", "Emin değilim", "PDF yanlış ya da eksik". Kimlik
     satırında (`confirm_pdf`) bunların önüne beşinci düğme gelir: "PDF doğru, model okusun". Birincil düğme bu olur.
   - Diğer türlerde birincil düğme yoktur; iki karar aynı ağırlıkta durur, çünkü ekran bir cevabı önermemeli.
   - Not alanı isteğe bağlı ve kapalı başlar ("Not ekle", ≤ 1000 karakter).
   - Cevaptan sonra satır listeden çıkar ve seçim sıradakine geçer. Bildirim ne olduğunu söyler ("Dahil edildi.
     Seçiminiz kaynaklarda kullanıcı seçimi olarak görünür.") ve 12 sn "Geri al" sunar.
   - Sonradan geri almak için sekmenin altında "Verdiğiniz kararlar (N)" açılır bölümü durur; her satırında "Geri al"
     vardır. Bu bölüm arka uçta küçük bir okuma gerektirir (karar 6). Liste eser başına tek satırdır: eserin sonucunu
     bugün veren taze insan kararı ya da PDF onayı. Eski soruyla verilmiş karar burada değil, kuyrukta `look_again`
     olarak durur.

   Gerekçe: SW11.7 kararı "kesin ve geri alınabilir" diyor. Onay penceresi 100 satırlık bir kuyrukta her cevabı iki
   tıka çıkarır; geri alma bu güvenceyi zaten veriyor. Tek tuşlu cevap kısayolu (1–5) önerilmiyor: yanlış tuş bir
   seçimi değiştirir ve bildirim kaçabilir. Satır başına süre ölçülmediği için kısayolun kazancı bilinmiyor
   (dilim 24).
5. **Süzgeçler ve üç sade durum.** Öneri:
   - Listenin üstünde soru türüne göre çipler, sayılarıyla: "Hepsi · Alıntıyı onayla · Koşulardan birini seç ·
     Sürümlerden birini seç · PDF'i onayla · Yokluğu onayla · Parçayı bul". Sayısı 0 olan çip gösterilmez.
   - İkincil bir "Neden" seçimi `reason_code`'a göre süzer. Seçenek metinleri kodu değil açıklamayı gösterir; kod
     yalnız ayrıntının "Neden kuyrukta" satırında, küçük harfle durur.
   - `look_again` satırları listenin sonunda "Eski soruyla verildi, yeniden bakın" başlığı altında toplanır. Satırda
     eski karar da görünür.
   - Durum kelimesi üç sade durumdan biridir (SW11.1): "Karar bekliyor" (kuyruktaki her satır), cevaptan sonra
     "Dahil", "Ölçütü karşılamıyor" ya da "Karar bekliyor" (`not_sure`, `pdf_wrong`). Neden kodu durum kelimesi olarak
     kullanılmaz.
   - Zincirle gelen eser satırda "atıf zincirinden" diye küçük bir etiket taşır; ayrıca süzgeci yoktur.
   - Sayılar: sekme hapı `counts.open + counts.look_again`; "siz karara bağladınız" sayısı `counts.decided` nesnesinin
     değerlerinin toplamıdır (nesne neden koduna göre sayar).
6. **Arka uca eklenecekler: üç okuma alanı ve bir liste; yeni tablo, yeni uç nokta ve model değişikliği yok.** Öneri:
   - `row_detail` parçalarına `passage_id` (alıntının pasajı) eklenir.
   - `closest` ve ipucu cümlelerine `passage_id` (o sayfanın pasajı) eklenir.
   - Ayrıntıya her satırda `asset_id` eklenir (bugün yalnız kimlik satırında var).
   - Doğrulanmış her alıntıya `anchor_text`: `locate_anchor`'ın o sayfada bulduğu kaynak metni (yalnız `exact` ve
     `normalized`; bulanık eşleşme hiçbir zaman çapa değildir). Sunarken hesaplanır, saklanmaz.
   - `choose_version` satırının ayrıntısına iki sürüm: her birinin sürüm etiketi, güncel kararı, koşuları ve
     alıntıları (bugün ayrıntı yalnız adı verilen sürümü taşıyor; Sol'un bulgusu). Ölçümde 0 satır, ama durum geçerli.
   - `GET …/queue` cevabına `decided` eklenir. Ham karar sorgusu değil: D96'nın yolu (`_scan` / `_classify` /
     `_state_of` / `_token`) eser başına sonucu insan kararından ya da PDF onayından gelen işleri seçer, eskimiş kararı
     dışarıda bırakır (o `look_again` satırıdır). Her satırda eser, sürüm, başlık, kod, tarih, not ve geri alma jetonu.
     Hiçbir şey yazılmaz, adım açılmaz (Ders C).
   - 409 cevabı nedenini taşır: `detail.reason` `row_changed` ya da `reading_started` (PDF onayının geri alınması,
     okuma başladıktan sonra). HTTP kodu ve jeton sözleşmesi değişmez.

   Gerekçe: satırdan PDF'e ve geri almaya giden yol bu alanlar olmadan ya sayfa numarasından pasaj aramaya ya da
   `view.sources` içinde sürüm eşleştirmeye kalır. Pasaj kimliği zaten saklı, eklemek yalnız okuma. `decided` dilim
   16'nın `undo_token` sözleşmesini kullanır; yeni bir geri alma yolu açmaz. Seçenek: `decided` olmadan kurmak. O
   zaman geri alma 12 saniyelik bildirimle sınırlı kalır; sonrası için kaynak sayfasında bir yol gerekir, o da ayrı bir
   yüzey işidir.
7. **Çakışma ve canlı güncelleme: kuyruk, ayrıntı ve araştırma görünümü birlikte yenilenir; seçim `work_id` ile
   korunur.** Öneri: jeton tutmazsa (revizyon değişti, bir okuma koşusu karar yazdı, seçim ya da baş kayıt değişti,
   kaynak çıkarıldı, dosya değişti) ekran üçünü birlikte yeniden çeker. Seçili satır `work_id` ile yeniden bulunur
   (sürüm değişmiş olabilir).
   Satır hâlâ kuyruktaysa `Notice tone="attention"` şunu der: "Bu satır gösterildikten sonra değişti; güncel hâli
   yüklendi. Cevabınız kaydedilmedi." Satır kuyruktan çıktıysa bildirim bunu söyler ve seçim sıradakine geçer.
   Koşu sürerken cevap vermek serbest: dilim 16 okuma koşusunun kararlı işi atlamasını sağlıyor. Koşu sürerken yeni
   satır gelebilir ya da gidebilir: kuyruk `research_view.last_event_id` her değiştiğinde aynı yoldan yenilenir.
   Yazılmakta olan not, seçili eser ve klavye odağı korunur. Seçili satır kuyruktan çıktıysa ayrıntı bunu söyler, not
   kaybolmaz. Geri almanın `reading_started` nedenli 409'u ayrı metin alır (Task 3); öteki nedenler aynı metni.

## Ortak kararlar (Claude + `gpt-5.6-sol` · medium, 24 Eylül 2026)

Yedi karar yukarıdaki önerilerle alındı, şu dört değişiklikle:

1. **Karar 2: seçenek (a).** Seçim ayrıntıyı doldurur, Enter ya da "Sayfa N'i PDF'te aç" düğmesi sayfayı açar. Bu
   SW11.6'nın "satır seçilince PDF açılır" sözünden bilinçli bir sapmadır ve D97'ye gerekçesiyle yazılır: her seçimde
   tam genişlikte açılan sayfa karar bağlamını örter, klavyeyle gezinmeyi bozar ve kaynak sayfasına kuyruğa özgü bir
   eylem bağlamı taşır. Sol ve Claude aynı gerekçeyle (a)'da birleşti.
2. **Karar 6, `decided`:** her satır tipli bir `answer` alanı taşır (`include`, `criterion_not_met`, `not_sure`,
   `pdf_wrong`, `pdf_confirmed`). PDF onayı ekranda `not_read_yet` kodundan ya da `pdf_confirmed:<asset>` notundan
   ayrıştırılmaz; iç not API sözleşmesine girmez.
3. **Karar 6, 409:** `detail.reason` çatışmanın doğduğu yerde tipli üretilir (`row_changed` jeton tutmazken,
   `reading_started` PDF onayının geri alınması okuma başladıktan sonra reddedilirken). İleti metninden çıkarılmaz.
   Yalnız kuyruk uç noktalarının 409 zarfı değişir; öteki uçlar aynı kalır.
4. **J vakası:** vaka başlamadan önce beklenen satır türlerinin (dört tür) kuyrukta olduğu API ile doğrulanır; yoksa
   vaka ekran hatası değil fikstür hatası olarak düşer. `choose_version` J'ye eklenmez. Sol iki yol önerdi (beşinci,
   iki sürümlü bir eser ya da görsel iddiayı kaldırmak); Claude ikincisini seçti, Sol'un kabul ettiği seçenek. Gerekçe:
   `versions_disagree` iki sürümün ayrı ayrı okunup zıt karar almasını ister; okuma koşusu eser başına tek sürüm okur,
   16 kütüphanede 0 satır var. Bunu fikstürde üretmek okuma planını zorlamak olur. `choose_version`'ın verisi arka uç
   testiyle sınanır (`test_a_choose_version_detail_carries_both_versions_and_their_decisions`), ekranı genel ayrıntı
   bileşenini kullanır ve görsel denetimi "ölçülmedi"ye yazılır.

## Global constraints

- **Yalnız `sw`.** Sekme, zaman çizelgesi satırı ve sayı `legacy` araştırmada yok. `legacy` görünümü ve uç noktaları
  değişmez.
- **Keşif, getirme, okuma, yanıt ve model sözleşmesi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır. Migration yok (son `0051`). Yeni neden
  kodu yok.
- **Arka uç değişikliği yalnız karar 6.** Dört okuma alanı, yazma yok, adım yok. `legacy`'nin 422'si ve CSRF kuralı
  aynen.
- **Ekran kayıtlı durumu gösterir.** Sayılar ve durumlar API'den gelir; cevap 200 dönmeden satır listeden çıkmaz (iyimser
  güncelleme yok). "Doğrulandı" kelimesi yalnız `quote_verified` doğruysa ve yalnız "alıntı sayfada bulundu" anlamında
  kullanılır. Ekran bir kararın doğru olduğunu söylemez.
- **`.impeccable.md` kuralları:** editoryal tokenlar, iki tema, 760 px kırılımı, 390 px'te kullanılabilir, klavye,
  görünür odak, `prefers-reduced-motion`, cümle düzeninde etiketler, lucide ikonları, yeni UI bağımlılığı yok, kart
  gölgesi yok, renkli kenar çubuğu yok. Kaynak başlığı kaynak sayfasını açar (§3 "a source's title opens the source
  sheet"). Serif içerik (başlık, alıntı, gerekçe), sans arayüz.
- **Çeviri.** Her metin `t()` ile, Türkçesi `i18n.ts`'te. Neden kodlarının açıklamaları `labels.ts`'te tek yerde.
- **Konuya özgü hiçbir şey yok.** Parça adları ve tanımları ölçütten gelir; ekran hiçbir parça adını bilmez.

## Task 1: arka uç okuma alanları (karar 6)

- `workflow/queue.py`: `_detail` her parçaya `passage_id` ekler. `_closest` sonucu ve `_cues` cümleleri sayfanın
  pasaj kimliğini taşır (`passages` tablosunda o sürümün o sayfadaki `pdf_page` pasajı). Ayrıntıya `asset_id` (sürümün
  güncel dosyası) eklenir.
- Doğrulanmış alıntıya `anchor_text` (karar 6): `locate_anchor(quote, page_text)`'in `exact` / `normalized`
  eşleşmesinin sayfadaki metni.
- `choose_version` ayrıntısı iki sürümü taşır (karar 6).
- `queue_rows` sonucuna `decided`: `_scan` ile aynı anlık görüntüden (`_snapshot`), eser başına, sonucu taze bir insan
  kararından ya da PDF onayından (`not_read_yet` + `pdf_confirmed:` notu) gelen işler; eskimiş olan girmez. Her
  satırda `work_id`, `source_version_id`, `head`, `title`, `reason_code`, `note`, `created_at`, `undo_token`
  (`_state_of` / `_token`) ve tipli `answer` (ortak karar 2). Yeniden eskiye.
- `app.py`: kuyruk uç noktalarının 409'u `{"detail": {"reason": "row_changed" | "reading_started", "message": …}}`.
- `api.ts` tipleri buna göre genişler.

## Task 2: kuyruk sekmesi (`apps/web/src/HumanQueue.tsx`, yeni)

- `ResearchView.tsx`: `sw` araştırmasında "Kararınızı bekleyenler" sekmesi ve sayı hapı. `initialTab` `queue`'yu
  tanır. Yeni rota yok.
- **Liste:** `role=listbox`, `aria-activedescendant`, ↑↓ ile gezinme, Enter satırın sayfasını açar. Satır: sıra
  numarası (`place`), serif başlık (listede iki satırda kesilir; tam hâli ayrıntının başında kesilmeden yazılı ve
  satırın erişilebilir adında),
  sürüm `.ref-pill`, soru türü etiketi, zincir etiketi. Seçili satır `--selected-surface`.
- **Ayrıntı** yukarıdan aşağı:
  - Soru, bir cümle olarak. Örnek: "Bu makalede 'X' parçası var mı?" Altında parçanın tanımı.
  - "Neden kuyrukta" satırı: açıklama ve küçük harfle neden kodu.
  - İki koşu yan yana. Parça başına etiket (var / yok / belirsiz), alıntı serif blok alıntı olarak, "sayfada bulundu"
    ya da "metinde bulunamadı" notu, sayfa bağlantısı, gerekçe.
  - İpucu cümleleri: sayfalarıyla, en çok 5, "toplam N". Yoksa "Bu parçanın ifadeleri metinde geçmiyor".
  - Doğrulanamayan alıntı için en yakın pasaj (karar 3).
  - Kimlik satırında PDF'in ilk sayfası ve eserin başlığı / DOI'si yan yana.
  - Cevap alt bilgisi, bölmenin altında sabit (§3 "persistent actions go in a footer"): düğmeler, not ve "anlamsal
    destek denetlenmedi" notu bir kez.
- Kuyruk `last_event_id` değişince ve her cevaptan sonra yenilenir (karar 7). Seçim `work_id` ile korunur.
- Ayrıntı yüklenirken `role=status` metni. Bir ayrıntı gelince sıradaki satırın ayrıntısı arka planda çekilir, tek
  satır önden. Önbellek, liste yeniden çekilince ya da cevaptan sonra boşalır.
- **760 px ve altı:** liste tam genişlik. Satır seçilince ayrıntı listenin yerine geçer, başında "Listeye dön" vardır.
  Parçalar iki sütun yerine koşu koşu alt alta dizilir. Cevap alt bilgisi yine sabittir, düğmeler tam genişlikte alt
  alta.
- **Boş kuyruk:** "Kuyrukta satır yok." Sayılar varsa altında: "N eseri siz karara bağladınız; M eserin seçimini
  kaynaklardan verdiniz." (`counts.decided`, `counts.user_selected`).
- **Verdiğiniz kararlar** açılır bölümü (karar 4, 6).
- Zaman çizelgesi: okuma koşusunun turuna "N eser kararınızı bekliyor · Aç" satırı (karar 1). `Transcript.tsx`'in
  aşama durumlarına dokunulmaz.

## Task 3: cevap ve geri alma

- Cevap `api.answerQueueRow`, geri alma `api.undoQueueDecision`. Cevap 200 dönünce liste ve `research_view` yeniden
  çekilir; sayı hapı, kaynak listesindeki seçim ve zaman çizelgesi satırı birlikte güncellenir.
- Bildirim metinleri, cevaba göre:
  - "Dahil edildi."
  - "Ölçütü karşılamıyor olarak kaydedildi."
  - "Karar bekliyor olarak bırakıldı; kuyruğa kendiliğinden dönmez."
  - "PDF yanlış olarak işaretlendi; eser PDF bekleyenlere geçti."
  - "PDF onaylandı; bir sonraki okuma koşusu bu eseri okur."

  Her bildirimde "Geri al" vardır. Okuma koşusu kendiliğinden başlamaz; bunu metin söyler.
- 409: karar 7. 422 ve ağ hatası: `role=alert` ile kırmızı not, satır yerinde kalır.
- Geri almanın 409'u (PDF onayından sonra okuma başladı) ayrı metin alır: "Okuma başladığı için bu onay geri
  alınamıyor; eser için karar verebilirsiniz."

## Task 4: testler

- **Arka uç** (`tests/test_queue.py`, `tests/test_queue_api.py`), önce düşen test:
  - `test_detail_parts_cues_and_closest_carry_the_passage_of_their_page`
  - `test_every_row_detail_names_the_current_file_of_its_version`
  - `test_decided_lists_current_human_decisions_and_pdf_confirmations_with_an_undo_token_and_writes_nothing`
  - `test_a_decided_entry_leaves_the_list_once_undone_or_superseded`
  - `test_a_verified_quote_carries_the_source_text_it_was_found_as_and_an_unverified_one_none`
  - `test_a_choose_version_detail_carries_both_versions_and_their_decisions`
  - `test_a_stale_human_decision_is_in_look_again_and_not_in_decided`
  - `test_a_409_names_whether_the_row_changed_or_reading_started`
  - `test_decided_rows_carry_a_typed_answer_and_no_internal_note`
- **Fikstür sunucusu** (`tests/acceptance/fixture_server.py`). Bugün getirme ve okuma sabit kapalı, iki eserin PDF'i var
  (Sol'un bulgusu). J için: getirme ve okuma ortam değişkeniyle açılır (A–I için varsayılan kapalı kalır). En az dört
  SYNTHETIC eser, iki alandan, her biri PDF'li; birinin PDF'inin ilk sayfası eserin başlığını taşımaz, kimlik denetimi
  onu `pdf_identity_unconfirmed` yapar. `[queue]` işaretli soruda betikli model okuma yanıtını eser ve koşuya göre
  verir: bir eserde iki koşu anlaşmaz (`choose_run`), birinde alıntı sayfada birkaç harf farkla durur
  (`confirm_quote`, yakın pasajlı), birinde bir parça iki koşuda da `unclear` (`find_part`, ipucusuz).
- **Tarayıcı kabulü** (`apps/web/e2e/human-queue.spec.ts`, yeni vaka J). Önkoşul: dört satır türü API'de var (ortak
  karar 4). Vaka şunları sınar:
  - Sekme ve sayı yalnız `sw`'de var.
  - Satır seçilince ayrıntı dolar; Enter sayfayı açar ve kaynak sayfası PDF görünümünde doğru sayfada, tam genişlikte
    açılır.
  - Düz metin görünümünde doğrulanmış alıntının çapası işaretli; doğrulanamayan alıntıda işaret yok ve şerit amber.
    PDF görünümünde doğru sayfa numarası.
  - "Dahil et" satırı listeden çıkarır; kaynaklar sekmesinde seçim "Dahil" ve kullanıcının; bildirimdeki "Geri al"
    satırı geri getirir.
  - "PDF doğru" satırı kaldırır, "Verdiğiniz kararlar"da görünür ve oradan geri alınır.
  - Sunucuda araya bir karar yazılınca (API ile) ekrandaki cevap 409 alır ve not görünür.
  - 390 px'te: sekme erişilebilir, liste → ayrıntı → listeye dön (odak satıra döner), sabit cevap alt bilgisi içeriği
    örtmüyor, tam başlık görünür.
  - Klavye: Tab ile listeye, ↑↓, Enter, cevap düğmeleri; cevaptan sonra odak sıradaki satırda.
  - Etkin koşu: sunucuda (API ile) bir karar yazılınca açık ekranın kuyruğu olay akışıyla yenilenir, yazılmakta olan
    not kaybolmaz.
- Mevcut A–I vakaları değişmeden geçer.

## Task 5: kabul ve kapanış

- **Görsel denetim, saklı canlı kütüphanede.** `.local/sw-slice16-acceptance-2026-09-24/data-q1-quick-luna-r2`'nin
  bir kopyası `.local/sw-slice17-acceptance-<tarih>/` altına alınır ve 8765 dışında bir portta ayrı `DEIXIS_DATA_DIR`
  ile servis edilir. Ürün veritabanına dokunulmaz, model çağrısı yapılmaz. 16 satırın her türünden en az biri açılır.
  1440 px ve 390 px, açık ve koyu temada ekran görüntüsü alınır, kanıt klasörüne konur.
- Denetim listesi, `result.md`'ye yazılır:
  - başlıklar ve alıntılar kesilmeden okunabiliyor mu;
  - ipucusuz satır "geçmiyor" diyor mu;
  - doğrulanamayan alıntıda işaret yok mu;
  - sayfa doğru mu (satırın sayfa kuralı, karar 2);
  - koyu temada amber metin 4,5:1'i tutuyor mu.
- Bu kopyada bir karar turu yapılır (bir `include`, bir `not_sure`, bir geri alma, bir `pdf_confirmed`): liste, sayı,
  kaynak seçimi ve "Verdiğiniz kararlar" API'nin söylediğiyle aynı olmalı.
- Tam pytest (bilinen tek düşen test aynı), `npm run build`, `npm run lint` (yeni uyarı yok), `npm run
  test:acceptance` (A–J), `git diff --check`, `skill_package_hash` aynı.
- D97 `docs/decisions.md`'nin en üstüne. Satır 17 → `uygulandı, inceleme bekliyor`; tek commit; push.

## Bu dilimde yok

- Kuyruğu küçültecek üç düzeltme (ölçütte konu parçası, alıntı doğrulamasının satır numaraları, kimlik denetimi) ve
  SW6.6 `probable_version` (dilim 16'nın ayrı işleri).
- PDF bekleyenler listesi ve kullanıcının eklediği PDF (dilim 18). `pdf_wrong` cevabından sonra eser bu listeye geçer;
  liste 18'de kurulur. Bu dilimin bildirimi yalnız bunu söyler.
- Onaylı PDF'ten sonra okuma koşusunu kendiliğinden başlatmak. Kişi yeni okumayı bugünkü yoldan başlatır.
- Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S (dilim 20). Rapora kuyruk bilgisi girmez.
- Tek tuşlu cevap kısayolları ve soru türüne göre sıra (dilim 24'te ölçülürse).
- `choose_version` için ayrı bir görsel düzen. Bugün 0 satır var. Ayrıntı iki sürümü taşır (karar 6) ve iki koşu yerine
  iki sürüm yan yana aynı bileşenle gösterilir.

## Ölçülmedi

- Satır başına dakika ve ekranın bu süreyi kısaltıp kısaltmadığı.
- İpucu cümlelerinin ve en yakın pasajın kişiye yardım edip etmediği.
- Kararın doğruluğu. Ekran bir kişinin kararını kaydeder; dilim 16'nın ölçümündeki "gerçek soru üçte bir" yargısı tek
  okuyucunundu.
- Bir kişiyle yapılmış kullanılabilirlik denemesi yok. Görsel denetim tek oturumun gözü.
- `choose_version` ekranının görsel denetimi: ne saklı kütüphanelerde ne fikstürde örnek var (ortak karar 4).
- Paket sorusunda en büyük kuyruk 4 satır. Büyük kuyruk davranışı (100 satır) yalnız kuantum `detailed`'da görülebilir.
