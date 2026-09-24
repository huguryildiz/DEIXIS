# SW dilim 18 — PDF bekleyenler ve kullanıcının eklediği PDF

**Tarih:** 24 Eylül 2026. **Durum:** 18a uygulandı (D99; yayıncı PDF'iyle kabul yapılmadı, sahibin kararıyla commit edildi); 18b uygulandı (D100; bir yayıncı PDF'iyle canlı kabul yapıldı); `gpt-6-sol` · high'ın ikinci görüşü (`sol-plan.md`, "hazır değil", 11 bulgu) işlendi: dilim 18a ve 18b'ye bölündü; 18a uygulamaya hazır taslak, 18b'nin sözleşmesi kendi plan turunda kesinleşir. **Ana dosya:** [sw-status.md](sw-status.md).
**Karar:** yeni D numarası (dilim yazar; en yüksek D98). **Önkoşul:** 10 (D83), 12 (D85), 17a (D98). **Tür:** Kur.
**Kapsam:** SW10.4–5, SW11.9. **Plan:** Opus 5.5 · high. **Ölçüm:** `.local/sw-slice18-plan-2026-09-24/`
(`waiting.py`, `waiting.json`; salt okunur, model ve ağ yok).

**Goal:** Bir `sw` araştırmasında açık kopyası bulunamayan işler bugün `no_fulltext` koduyla `unresolved` kalıyor ve
hiçbir yerde listelenmiyor: kod tablosunda `next_step = waiting_for_pdf` yazıyor, onu okuyan kod yok. Bu dilim üç şeyi
kurar: (1) okuma sırasına göre dizili bir "PDF'inizi bekliyor" listesi, bağlantıları Ayarlar'daki kurum vekil adresiyle
tarayıcıda açılır; (2) kullanıcının bıraktığı dosya DOI ya da başlıkla işine eşlenir, kullanıcı onaylayınca eklenir;
(3) eklenen iş okuma sırasının başına geçer ve yanıtı SW11.9'un üç biçiminden biriyle gelir. Sol'ün önerisiyle iki
parça: **18a** liste, vekil bağlantısı ve onaylı eşleme; **18b** eklemenin kodu, ertelenmiş okuma isteği, kişi
kararının sahipliği ve sürüm sonuçları. Otomatik toplu indirme,
otomatik web eklemesi ve kullanıcının onaylamadığı ekleme yok (D4, D49).

## Elimizdeki sayılar

15 saklı `sw` kütüphanesi (dilim 15, 16 ve 17a kabulleri; 11'i kuantum `q1`, 4'ü kablosuz algılayıcı ağları `q2`),
`waiting.py`:

| | kuantum quick (4 + 1) | kuantum standard (4) | kuantum detailed (2) | q2 quick (1 + 3) |
|---|---|---|---|---|
| Getirme planı | 92–100 | 112–125 | 325 / 312 | 100 / 92–100 |
| PDF bekleyen iş (`no_fulltext`, metin yok) | 56–67 / 0 | 58–77 | 173 / 32 | 92 / 2–4 |
| Bunların planın ilk 20'sindeki | 10–14 | 8–11 | 11 / 10 | 19 / 0 |
| IEEE (`10.1109`) payı | %76–84 | %60–69 | %68 / %59 | %73 / 0 |
| DOI'siz | 0–2 | 4–6 | 15 / 9 | 3 / 2–4 |
| Açılış sayfası bağlantısı olan | hepsi | hepsi | hepsi | hepsi |

"+ 1" ve "+ 3": dilim 15'in eski sorgu kipleriyle yapılmış karşılaştırma koşuları (`q12`, `r12`); standard ve
detailed sütunlarında da birer `r12` var (detailed'da 32'lik olan). Güncel yol `luna` kütüphaneleri.

- `text_unreadable` ve `human_pdf_wrong` hiçbir kütüphanede yok; liste bugün tamamen `no_fulltext`.
- Liste boyu konuya ve sorguya bağlı: güncel yolda 56–173, eski kiplerde 0–4.
- **Eşleme (vekil ölçü):** her kütüphanede kullanımdaki her PDF'in başı yeniden çıkarıldı ve `match_pdf_to_source`'a
  planın bütün işleri (her sürümüyle) aday verildi. 633 dosyada: DOI ile doğru 165, başlıkla doğru 383, eşleşme yok 83
  (%13), **yanlış 2** (ikisi de `detailed`: dosyanın ilk sayfası planın başka bir işinin DOI'sini anıyor ve DOI döngüsü
  onu önce buluyor). Bunlar indirilmiş açık kopyalar, çoğu ön baskı; kullanıcının bırakacağı yayıncı dosyası değil.
- Sayfa sayısı p50 10–15,5, p95 14–56, en çok 173.
- Okuma çağrısı (model, duvar süresi) p50 11–17 sn, p95 17–31 sn; bir iş iki çağrı.

## Dilim 18a — liste, vekil, onaylı eşleme

1. **Liste işin geçerli tam metin kararından kurulur** (Sol 1). Geçerli karar `next_step = waiting_for_pdf` olan bir
   koda sahipse (`no_fulltext`, `text_unreadable`, `human_pdf_wrong`; `reason_codes.py`'den türetilir, sabit liste
   yok) ve hiçbir sürümde metin yoksa iş listededir. Kişinin `human_pdf_wrong` kararı da listede tutar; kişinin başka
   bir kararı listeden çıkarır. Plana hiç girmemiş (`not_reached`) iş listede değil. Sıra son `fulltext_plan`'ın
   sırası (D83: grup, saklı anahtar sözcük ya da zincir sırası, baş kimlik); plan yoksa liste boş.
2. **Satır ve bağlantılar** (Sol 2). Başlık, yıl, yayın yeri, DOI, neden (sade metin), sıra numarası; DOI ve açılış
   sayfası bağlantısı yeni sekmede (`rel="noopener noreferrer"`), vekil varsa vekilden. Satırdaki "PDF bul" bugünkü
   eylem, olduğu gibi: DOI'si ve sürümü doğrulanan kopyayı kendisi ekleyebilir, sürümü belirsiz aday ve web sonucu
   kişinin onayını bekler (D4). Yalnız kişinin tıklamasıyla koşar; toplu "hepsini aç" yok.
3. **Kurum vekil adresi** (Sol 3), `app_settings`'te. İki biçim: `{url}` içeren şablon (hedef adres bütünüyle
   yüzde-kodlanıp yerine konur) ve önek (`…/login?url=`; hedef adres ham eklenir, EZproxy böyle bekler). Önek biçiminde
   hedefte `&` ya da `#` varsa bağlantı bozulabilir; bu durumda hedef kodlanmış eklenir ve iki biçim örnek adreslerle
   sınanır (`?a=1&b=2`, `#fragment`, DOI'de `<>;`). Yalnız `https`; kullanıcı adı / parola içeren adres reddedilir. Boşsa
   bağlantılar doğrudan açılır. Sidebar'daki "Kurum erişimi" (Scopus IP denetimi) ayrı kalır. **Ölçülmedi:** vekil
   girişi, sahibin kurum hesabı olmadan denenemez.
4. **Eşleme işi önerir, sürümü kişi seçer** (Sol 4). `sw`'de aday kümesi: son plandaki işler + listedekiler + planın
   ardından kişinin dahil ettiği işler, her sürümüyle. Dosyanın başı birden çok aday işin DOI'sini anıyorsa DOI tek
   başına karar vermez; başlık tek işi gösteriyorsa o önerilir, göstermiyorsa eşleşme yok (yalnız yükleme önerisi;
   `check` ve `legacy` değişmez). Yanıt: önerilen iş, işin sürümleri (etiket, yıl, tür; eşlemenin gösterdiği sürüm
   işaretli), dosyanın sayfa sayısı, metin katmanı var mı, dayanak. Onay ekranında sürüm seçimi zorunlu; eşleşme yoksa
   kişi listeden iş seçer. Ölçülen iki yanlışın bu kuralla kapandığı uygulamadan sonra `waiting.py` ile yeniden
   ölçülür (bugün yalnız beklenti).
5. **Eşlemeden onaya dosya bağı** (Sol 10). Eşleme yanıtı dosyanın `sha256`'sını, önerilen işi, araştırmanın kapsam
   revizyonunu ve işin sürüm listesinin özetini taşır. Onay isteği bunları geri gönderir; dosya değişmişse, kapsam
   revize edilmişse, seçilen sürüm artık araştırmanın üyesi değilse ya da o sürümde kullanımda bir PDF varsa onay
   reddedilir ve kişiye nedeni söylenir. 18a'da onay bugünkü ekleme yolunu kullanır (`origin = user_upload`); kod ve
   okuma 18b'de.
6. **Nerede** (Sol 9). `sw` araştırmada insan kuyruğu sekmesinin (D97) yanında "PDF bekliyor" görünümü, sayısıyla;
   dosya bırakma orada. `PdfReadiness`'in bugünkü akışı yalnız dahil edilen satırları seçenek yapıyor ve eşleşen
   sürümü işin başına çeviriyor; `sw`'de bırakma yeni görünümün sürüm onaylı akışına bağlanır, `legacy`'de değişmez.

## Dilim 18b — ekleme sonrası

**Plan turu:** 24 Eylül 2026, Opus 5.5 · high; ikinci görüş `gpt-6-sol` · high iki tur: ilki "hazır değil", 9 bulgu;
ikincisi yine "hazır değil", 8 yeni bulgu; üçüncüsü "hazır değil", 6 bulgu; dördüncüsü 2 bulgu; beşincisi "düzeltmeyle hazır", 1 kısmi bulgu (`.local/sw-slice18b-plan-2026-09-24/`
`sol-plan.md` … `sol-plan-5.md`); hepsi aşağıda işlendi. İkinci turun dersi: okuma isteğini saklı karardan ve eski planlardan türetmek
her bitiş yolunda ayrı bir kural istiyordu, bu yüzden istek kendi tablosuna taşındı. **Önkoşul:** 18a commit'i (D99). Bugünkü durum (koddan
okundu; bu tur için ölçüm yapılmadı): 18a'nın onayı dosyayı ekliyor, olay yazıyor, başka hiçbir şey yazmıyor. İşin
saklı kararı eski `no_fulltext` olarak kalıyor, iş listeden düşüyor ve başka hiçbir ekranda görünmüyor; okuma planı
başka bir sürümünde taze model kararı olan işi hiç almıyor; okuma koşusunu yalnız getirme ya da keşif bitişi kuyruğa
koyuyor.

1. **Onayla birlikte kod, dosyaya bağlı** (Sol 5; Sol'ün plan bulguları 1–2). Onay işlemi, dosyayı eklediği aynı
   işlemde, kişinin seçtiği sürüme bir tam metin kodu yazar: metin varsa `not_read_yet`, yoksa `text_unreadable`. Karar
   notu dosyayı adlar (`person_pdf:<asset_id>`) ve karar o dosyanındır: aynı kod da olsa dosya değişince yeni satır
   yazılır (`record`'un "aynı karar bir kez" kuralı bu notlu yazımda nota da bakar). Kişinin kararı hiç ezilmez. Kişi
   dışındaki bir karar (kod ya da model) yazımdan önce verilmişse o sürümün önceki dosyası ya da dosyasızlığı
   içindir ve üzerine yazılır; `should_write`'ın "taze okuma kararı ezilmez" kuralı bu dosyadan sonra verilen
   kararları korur. Metni olmayan dosyanın işi listede `text_unreadable` nedeniyle kalır.
2. **Dosya değiştirme yok, kaldırmaya yönlendirme de yok** (plan bulgusu 5; ikinci tur 1). 18a'nın `pdf_in_use`
   reddi aynen kalır. D50'nin "yanlış dosyayı kaldır" eylemi ve D45'in değiştirmesi kütüphane geneli çalışır ve aynı
   sürümü kullanan öbür araştırmaları da etkiler; 18b ikisini de değiştirmez, çağırmaz, önermez. Sonuç: bekleme nedeni
   sürümün kendi dosyası olan (`text_unreadable`, ya da o dosya için `human_pdf_wrong`) ve başka sürümü olmayan iş
   18b'de yeni dosya alamaz; panel bunu söyler. Bu bilerek bırakılan bir sınırdır, D kaydına yazılır.
3. **Kişinin `human_pdf_wrong`'u geri alınmaz, yalnız o sürüm için konuşur** (Sol 5; plan bulgusu 1; üçüncü tur 2).
   Kişi yanlış dediği sürümün değil, işin başka bir sürümüne dosya ekleyebilir. Yanıtı silinmez, `undo_human`
   çağrılmaz; böylece yanlış dosyaya dayanan eski model kararı (örneğin bir `include`) geri gelmez. `work_outcome`'da
   bir tek istisna: `human_pdf_wrong` "bu sürümün dosyası yanlış" demektir ve işin başka bir sürümünde kişi dosyası
   isteği varsa işin sonucu olmaz; sonuç o isteğin sürümünden gelir (karar 8), okunana kadar `not_read_yet`, yani
   `unresolved` ve yanıtta yok. Aynı istisna okuma kapılarında da geçerlidir (dördüncü tur 1): `group_of`, okuma
   planı ve okuma yürütücüsü, işin başka sürümündeki kişi kararı `human_pdf_wrong` ise ve bu sürümde kişi dosyası
   isteği varsa işi atlamaz; öbür kişi kararlarında atlamayı sürdürür. Onay paneli önceki yanıtı adıyla yazar
   ("X sürümünün dosyasını yanlış demiştiniz; bu dosya Y sürümüne eklenir ve model onu okur; X hakkındaki yanıtınız
   durur"). Kişinin başka bir kararı (dahil, ölçütü karşılamıyor, emin değilim) varsa dosya eklenir, kod ve istek
   yazılmaz, okuma açılmaz; panel "kararınız duruyor" der.
4. **Okuma isteği kendi tablosunda** (Sol 6; plan bulguları 2–4, 8; ikinci tur 3–7). Migration `0052`:
   `person_pdf_requests` (araştırma, sürüm, asset, kapsam revizyonu, ölçüt özeti, durum, koşu, zamanlar). Durumlar:
   `waiting` → `planned` (bir okuma planı dondurulurken, planla aynı işlemde, koşu kimliğiyle) → `read` (o dosyanın
   okuma kararı yazılınca, aynı işlemde; hangi koşu yazarsa yazsın, olağan grup sırasıyla okuyan bir koşu da: okuma
   aşaması bir sürüme karar yazdığında o sürümün kullanımdaki asset'inin `read` olmayan isteği aynı işlemde `read`
   olur, ama yalnız kararın dayandığı plan isteğin asset'ini, sayfa özetini, kapsam revizyonunu ve ölçüt özetini
   taşıyorsa; biri tutmazsa istek değişmez, dördüncü tur 2) ya da `unread` (planlandığı koşu karar yazmadan bitti: model yanıt veremedi,
   D18; koşu iptal edildi, başarısız oldu ya da dosya kullanımdan çıktı). Kapsam revizyonu ya da ölçüt özeti değişince
   (aynı kapsamda protokol yeniden dondurulabilir) eski satırlar `stale` sayılır, yazılmaz. İstek onayla (ve karar 10'da kaynak satırı yüklemesiyle) aynı işlemde yazılır; yalnız
   iş okumaya uygunsa (`group_of` karar 3'ün istisnasıyla boş değil; istisna yazılacak istek varsa diye sınanır ve istek aynı işlemde
   yazılır, beşinci tur; dondurulmuş ölçüt var, okuma ayarı `auto`), değilse dosya eklenir,
   istek yazılmaz, görünüm nedenini söyler.
5. **Kuyruğu tek yardımcı açar.** `ResearchFlow.queue_person_reading(research_id)`: `waiting` istek yoksa ya da
   araştırmada etkin (`queued`, `running`, `pause_requested`) **veya duraklatılmış** koşu varsa hiçbir şey yapmaz.
   Duraklatılmış koşu varken görünüm yeni koşu sunmaz; o koşuyu sürdürme ya da iptal etme eylemini gösterir (üçüncü
   tur 5). Yoksa anahtarı `fulltext_adjudication:person:<kapsam>:<ölçüt>:<waiting asset kimliklerinin özeti>`
   olan okuma koşusunu açar (ilk denemede `attempt` 0). Bu anahtarla koşu zaten varsa ve bitmişse (plan dondurulmadan başarısız ya da iptal
   olduysa) o istekler `unread` yapılır, yeni koşu açılmaz. Çağıranlar: onay işleminin sonu; worker, `execute` hangi
   yoldan dönerse dönsün; worker açılışı (bekleyen isteği olan her `sw` araştırma); API'nin koşu duraklatma ve iptal
   uçları (yürütülmeden `paused` / `cancelled` olan koşu worker'dan geçmez). Kişi bir okuma koşusunu iptal ettiyse o
   koşunun `planned` istekleri `unread` olur, yeniden açılmaz; `waiting` olanlar (plan dondurulmamıştı) de `unread`
   olur. D98'in keşif bitişi okuma koşusu (`after:<run_id>` anahtarı aynen) `waiting` istekleri planına alır ve
   `planned` yapar; bu yüzden bitişte ikinci koşu açılmaz.
6. **Plan dosyaya ve çıkarıma bağlı** (plan bulgusu 6; ikinci tur 2). Dondurulan `adjudication_plan` her iş için
   okunacak sürümü, asset kimliğini ve o asset'in sayfa metinlerinin özetini yazar. Çağrıdan önce ve karar yazımından
   önce aynı asset kullanımda mı ve sayfa özeti aynı mı denetlenir; değilse o iş bu koşuda karara bağlanmaz,
   `not_reached` sayılır, isteği `unread` olur. Donmuş plana sonradan iş eklenmez. **Yeniden deneme kişinin:** `unread`
   isteğin satırında "Yeniden oku" düğmesi isteği yeniden `waiting` yapar, yardımcıyı çağırır, tablodaki `attempt` sayısını bir artırır ve anahtar `…:<özet>:<attempt>` olur, bu yüzden aynı dosya için yeni koşu
   gerçekten açılır (üçüncü tur 1); arayüz yalnız açılan koşuyu gösterir. Otomatik plan `unread` istekleri başa almaz; onlar
   bugünkü grup sırasında kalır.
7. **Okuma sırasının başı** (SW11.9). `read_plan`'da `waiting` isteği olan işler bütün gruplardan önce gelir,
   aralarında onay sırasıyla (asset `created_at`, sonra kimlik). Sınır aynıdır (40 / 50 / 150) ve onlar da sayılır.
8. **Kişinin dosyası öne geçer** (Sol 8; plan bulgusu 7; ikinci tur 8; SW11.9'un sürüm cümlesi). Okunan sürüm kişinin dosyasını
   taşıyan sürümdür; başka bir sürümdeki taze model kararı onu plandan dışlamaz (`_fresh_model` başka işlerde aynen
   kalır). Kimlik denetimi kullanıcı yüklemesinde bugünkü gibi atlanır (D85). Sonuç:
   - **Okunana kadar** iş önceki sonucunu korur ve yanıt, o sonucun dayandığı sürümü okur: `answer_version` kişinin
     henüz okunmamış dosyasını taşıyan sürümü atlar; araştırma görünümünün toplu seçicisi
     `answer_versions` aynı kuralı kullanır ve ikisinin aynı sürümü verdiği sınanır. Böylece ölçüte göre okunmamış metin yanıta girmez.
   - **Okunduktan sonra** kişinin dosyasının kararı işin sonucudur: `work_outcome`'da taze model kararları içinde
     `read` isteğinin dosyasına ait olan öne geçer ve `answer_version` o sürümü okur. Kişinin kendi kararı yine her
     şeyin önündedir (karar 3'ün `human_pdf_wrong` istisnası dışında). Üstünlük yalnız o dosya hâlâ kullanımdaysa ve
     sayfa özeti okunan hâliyle aynıysa geçerlidir; bu her okumada yeniden denetlenir (üçüncü tur 3). Dosya başka bir
     araştırmadan kütüphane genelinde kaldırılırsa üstünlük düşer ve bugünkü kural geri gelir; o araştırmanın yanıt
     revizyonunun değişmemesi D50'nin bugünkü sınırıdır, 18b onu değiştirmez ve D kaydına yazılır. Başka sürümün
     farklı sonucu silinmez, kendi sürüm etiketiyle "öteki sürüm şöyle okundu" diye gösterilir; bu iş için
     `versions_disagree` kuyruk satırı açılmaz. Önceki alıntılar kendi sürüm etiketini taşır.
   - Kişi dosyası olmayan işlerde `work_outcome` ve `answer_version` aynen kalır.
9. **Yanıt durumu, saklı kanıttan** (Sol 7; plan bulgusu 9). "PDF bekliyor" görünümünün altında "Eklediğiniz
   dosyalar" bölümü: güncel kapsamda kişi dosyası olan işler, durumları saklı karardan ve adımlardan: *okuma
   bekliyor* (etkin koşu varsa "o koşu bitince"), *model okuyor* (bu işin `model:fulltext_adjudication` adımı
   `running`), *dahil edildi* (doğrulanmış alıntılar ve sayfaları), *ölçütü karşılamıyor* (metin: "gösterilen
   pasajlarda ölçütün parçaları bulunamadı"; alıntı gösterilmez, çünkü `criterion_absent` doğrulanmış olumlu alıntı
   taşımaz), *kararınızı bekliyor* (insan kuyruğu sekmesine bağlantı), *okunamadı* (`unread`, karar 6, "Yeniden oku"),
   *model kapalı* (okuma ayarı `off`, dondurulmuş ölçüt ya da model yok; koşu açılmaz), *kararınız duruyor*. Metinsiz
   dosya bu bölümde değil, listede `text_unreadable` nedeniyle görünür. Katı-ipucu kod kapısı kurulmadığı için
   "kodla kapandı" biçimi yok; SW11.9 "kısmen uygulandı" kalır.
10. **Aynı yol kaynak satırında** (ikinci tur 7). `sw` araştırmada kaynak satırındaki yükleme (`/sources/{svid}/uploads`)
    karar 1, 3 ve 4'ün aynı yardımcısını çağırır, karar 4'ün uygunluk denetimiyle: kişinin dışladığı ya da okumaya
    uygun olmayan işe kod ve istek yazılmaz. `legacy`'de hiçbir şey değişmez.

## Global constraints

- **Yalnız `sw`.** `legacy`'nin eşleme, ekleme ve okuma yolu değişmez; `/uploads/match` `legacy`'de bugünkü adaylarla
  bugünkü yanıtı verir.
- **Otomatik ekleme yok.** Eşleme önerir; dosya kişinin onayıyla, kişinin seçtiği sürüme eklenir. "PDF bul" bugünkü
  kuralıyla (D4). Uygulama vekil üzerinden hiçbir istek atmaz; toplu indirme yok.
- **Model sözleşmesi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır. Yeni neden kodu yok. 18a'da
  migration beklenmiyor (son `0051`; vekil adresi `app_settings`'te).
- **Tek SQLite bağlantısı**, kısa eşzamanlı işlemler.
- **Konuya özgü hiçbir şey yok.** Liste kod tablosundan ve saklı plan sırasından türer; yayıncı adı yazılmaz.

## Task taslağı (18a)

1. **Liste.** `fulltext.waiting(works, plan)` saf fonksiyonu → sıralı işler ve nedenleri; `views.py`'de sayı ve
   satırlar. Testler: üç kod, kişinin `human_pdf_wrong`'u listede, kişinin başka kararı dışarıda, eskimiş kod, metni
   olan sürüm, `not_reached`, sıra, plan yok.
2. **Vekil.** Ayar okuma / yazma, doğrulama, bağlantı kurma saf fonksiyonu; `Settings.tsx` alanı. Testler: iki biçim,
   `&` / `#` / DOI özel karakterleri, reddedilen adresler.
3. **Eşleme.** `sw` aday kümesi, sürümlü yanıt, çok-DOI kuralı, dosya bağı. Testler: DOI, başlık, yok, çok-DOI
   çakışması, `legacy` aynı; onayın dosya / kapsam / üyelik / kullanımda PDF nedeniyle reddi.
4. **Arayüz.** `.impeccable.md` önce. "PDF bekliyor" görünümü, satır, bağlantılar, bırakma, sürüm seçimli onay.
   Playwright: yeni K senaryosu (bekleyen iş → dosya bırak → sürüm seç → onayla → iş listeden düşer). Ekran
   görüntüsüyle kendim doğrularım.
5. **Kabul.** Kendi portunda, kendi veri dizininde bir `sw` koşusu; sahibin elindeki gerçek bir yayıncı PDF'i
   bırakılır, eşleme ve onay ölçülür; `waiting.py` çok-DOI kuralından sonra yeniden koşar. Vekil ölçülmez.
6. **Kapanış.** D kaydı, SW10 durum satırı (madde 4–5 kısmen), SW11 durum satırında madde 9 "18b'de", sw-status 18a
   satırı ve yeni 18b satırı.

## Bu dilimde yok (18a)

- Eklemenin kodu, okuma isteği, okumanın önü, sürüm önceliği ve yanıtın üç biçimi (18b).
- Katı-ipucu kod kapısı (SW10.2, SW1.5) ve alıntılı kod kapanışı.
- arXiv başlık araması, Europe PMC, LaTeX / Marker okuma (SW10.3, 10.6–7).
- Vekil üzerinden otomatik indirme ya da oturum çerezi saklama.

## Task taslağı (18b)

1. **Kod.** Onay yardımcısı (karar 1–3, 10): notlu kod, dosya değişince yeni satır, `human_pdf_wrong`'un yalnız kendi
   sürümü için konuşması. Testler: metinli / metinsiz dosya, önceki kod ve model kararı üzerine yazılır,
   dosyadan sonraki okuma kararı ezilmez, kişinin başka kararı durur, `human_pdf_wrong` silinmez ve yanlış dosyanın eski
   `include`'u geri gelmez, `pdf_in_use` aynı, `legacy` aynı.
2. **Okuma isteği.** Migration `0052`, istek durumları ve `queue_person_reading` ile çağıranları (karar 4–6).
   Testler: etkin ya da duraklatılmış koşu varken bekler; bitişte açılır (tamam / hata / iptal / duraklama yolları
   ayrı ayrı, API'nin yürütülmeden duraklattığı ve iptal ettiği kuyruk koşusu dahil); kapsam revizyonu eski isteği
   açmaz; kişinin iptali `unread` yapar ve yeniden açmaz; D98 keşif bitişi ikinci koşu açmaz; plan dondurulmadan
   başarısız olan koşu isteği `unread` yapar; model karar yazamazsa döngü yok ve "Yeniden oku" aynı dosya için yeni koşu açar; `unread`
   dosyayı olağan sırayla okuyan koşu isteği `read` yapar; ilk 40
   `unread` iken sonraki 10 `waiting` istek önce okunur; çökme (onaydan sonra süreç ölür, açılışta koşu açılır); ayar
   `off` ve uygun olmayan iş istek yazmaz.
3. **Plan ve sonuç.** `read_plan` önü, planda asset kimliği ve sayfa özeti, çağrı ve yazım öncesi denetim, `work_outcome` ve
   `answer_version`'ın kişi dosyası kuralı (karar 5, 7, 8). Testler: sıra, sınır, başka sürümde taze model kararı,
   dosya duraklatılmış koşuda kaldırılır ya da yeniden
   çıkarılırsa karar yazılmaz, `answer_version` ile `answer_versions` aynı sürümü verir, okunmadan önce yanıt eski sürümü okur, okunduktan sonra
   kişi dosyasının kararı sonuçtur ve öteki sürüm görünür, dosya kaldırılınca üstünlük düşer, kişi dosyası olmayan işte hiçbir şey değişmez.
4. **Arayüz.** "Eklediğiniz dosyalar" bölümü, onay panelinin yeni metinleri (önceki `human_pdf_wrong` yanıtı,
   "kararınız duruyor", tek sürümlü işte "yeni dosya alamaz"), duraklatılmış koşuda sürdür / iptal et.
   Playwright: yeni L senaryosu (K'nin sonundan: dosya onaylandı → okuma bekliyor → betikli model okur → dahil
   edildi) ve bir failure betiği (model okuyamaz → okunamadı → Yeniden oku). Ekran görüntüsüyle masaüstü ve telefon
   genişliğinde kendim doğrularım.
5. **Kabul.** 18a'nın kabul kütüphanesinde (`data-q1-quick`), sahibin yayıncı PDF'i onaylandıktan sonra okuma canlı
   bir modelle koşar (model sahibin; `gpt-5.6-luna` kotası yoksa `deepseek-flash`): onaydan okumanın başlamasına ve
   sonuca kadar geçen süre ile sonucun kendisi yazılır.
6. **Kapanış.** Yeni D numarası (D48'in kişi dosyası istisnasını adıyla yazar), SW11 durum satırı (madde 9: öne
   geçme, yanıt durumları, sürüm üstünlüğü; kod kapısı yok), sw-status 18b satırı.

## Bu dilimde yok (18b)

- Katı-ipucu kod kapısı ve "kodla kapandı" yanıtı (SW10.2, SW1.5; dilim 23).
- Dosya değiştirme ya da kaldırma; D45 ve D50'nin kütüphane genelindeki eylemleri ve öbür araştırmalara etkileri
  aynen kalır. Kendi dosyası yüzünden bekleyen tek sürümlü iş 18b'de yeni dosya alamaz.
- Donmuş okuma planına sonradan iş eklemek; çalışan okuma koşusunu kesmek.
- Kişi dosyası olmayan işlerde sürüm değişince yeniden okuma (`_fresh_model` kuralı aynı kalır).

## Ölçülmedi

Vekil akışının kendisi (sahibin kurum girişi gerekiyor). Kişinin bırakacağı yayıncı dosyalarında eşlemenin doğruluğu (633 gözlem açık kopyalardan):
ölçü indirilmiş açık kopyalarla, ağırlıkla ön baskılarla yapıldı; yayıncı PDF'inin ilk sayfası DOI'yi daha sık taşır,
kaynakça ise daha önce başlayabilir. Liste boyunun kuantum ve `q2` dışında ne olduğu. Bir kişinin gerçekte kaç dosya
bıraktığı ve okumanın öne geçmesinin kişinin bekleme süresini ne kadar kısalttığı. 18b'de: onaydan sonucun
gelişine kadar geçen süre ve kişinin yayıncı dosyasının okuma sonucu (kabulde bir iş; genelleme değil).
