# SW dilim 18 — PDF bekleyenler ve kullanıcının eklediği PDF

**Tarih:** 24 Eylül 2026. **Durum:** plan; `gpt-6-sol` · high'ın ikinci görüşü (`sol-plan.md`, "hazır değil", 11 bulgu) işlendi: dilim 18a ve 18b'ye bölündü; 18a uygulamaya hazır taslak, 18b'nin sözleşmesi kendi plan turunda kesinleşir. **Ana dosya:** [sw-status.md](sw-status.md).
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

## Dilim 18b — ekleme sonrası (sözleşme kendi plan turunda kesinleşir)

Sol'ün 5–8. bulguları burada; 18a kapanmadan uygulanmaz.

- **Kod** (Sol 5). Onaylanan dosya için `not_read_yet` ya da `text_unreadable` yalnız `fulltext.should_write` izin
  veriyorsa yazılır; taze bir okuma kararı ezilmez. Kişinin `human_pdf_wrong` dediği işe yeni dosya eklenince eski
  karar sessizce kalkmaz: kişiye yeni dosya gösterilir, o kararı geri alıp yeniden okutma yolu sunulur.
- **Okuma isteği** (Sol 6). SW11.9'un "başa geçer"i çalışan D85 planını değiştirmez. `create_run` aynı araştırmada
  kuyrukta olan dahil etkin koşu varken ikinci koşuyu reddediyor (`store.py` `create_run`); bu yüzden onay, aynı işlemde
  kalıcı bir okuma isteği yazar. Etkin koşu yoksa okuma hemen açılır; varsa o koşu bitince açılır ve henüz donmamış
  okuma planının başına konur. Anahtar araştırmayı, kapsam ve ölçüt revizyonunu ve dosyayı içerir; keşif sürerken
  gelen istek keşfin bitişinde yeniden değerlendirilir, çift okuma açılmaz.
- **Yanıt durumu** (Sol 7). "Okuma bekliyor" ile "model okuyor" ayrı durumlar; ikincisi çağrı gerçekten başlayınca.
  `text_unreadable` "alıntı ve sayfayla kodla kapandı" sayılmaz. Katı-ipucu kapısı kurulmadığı için SW11.9 "kısmen
  uygulandı" kalır.
- **Sürüm** (Sol 8). Taze eski model kodu işi `read_plan` dışında bırakıyor ve `_adjudication_plan` sürümü
  `answer_version` (D48) ile seçiyor. Yeni dosyanın hangi kararı yeniden açtığı, hangi sürümün okunduğu ve iki sürüm
  ters sonuç verdiğinde ne gösterileceği tek kararda yazılır; bu karar olmadan 18b'nin sürüm kısmı uygulanmaz.

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

## Ölçülmedi

Vekil akışının kendisi (sahibin kurum girişi gerekiyor). Kişinin bırakacağı yayıncı dosyalarında eşlemenin doğruluğu (633 gözlem açık kopyalardan):
ölçü indirilmiş açık kopyalarla, ağırlıkla ön baskılarla yapıldı; yayıncı PDF'inin ilk sayfası DOI'yi daha sık taşır,
kaynakça ise daha önce başlayabilir. Liste boyunun kuantum ve `q2` dışında ne olduğu. Bir kişinin gerçekte kaç dosya
bıraktığı ve okumanın öne geçmesinin kişinin bekleme süresini ne kadar kısalttığı.
