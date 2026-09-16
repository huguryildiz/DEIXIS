# P5 dilim 5 — Bilinen kaynak kümesiyle ölçüm: arama, PDF, pasaj, tablo hücresi ve yanıt: tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Kabul edildi (17 Eylül 2026): sahip §8'deki yedi soruda da ilk seçeneği seçti. Alt adım 1 sahibin girdisini bekliyor (§10). Kod yazılmadı, model ya da sağlayıcı çağrısı yapılmadı.

**Kısaca:** P5'in son dilimi yeni bir özellik değil, bir ölçümdür. Soru şu: DEIXIS gerçek bir soruda, gerçek modelle, kullanıcının bildiği kaynaklardan kaçını bulur, kaçının PDF'ini alır, modele doğru pasajı verir, tablo hücresine doğru değeri yazar ve yanıttaki iddiayı gerçekten destekleyen pasaja bağlar? Bu beş aşama ayrı ölçülür ve tek bir "doğruluk" sayısında birleştirilmez (plan §9 "P5 PDF edinme önerisi", §10). Bugüne kadarki bütün içerik denetimleri Claude'un okumasıdır, bir insanın değil. Ayrıca D43'ten sonra arama (D44), PDF çıkarımı (D47), PDF toplama (D49), denklem okuma (D52) ve OCR (D51) değişti; bunların hiçbiri gerçek modelle uçtan uca yeniden ölçülmedi.

## 1. Şu ana kadar ölçülenler

17 Eylül 2026'da koddan, karar kaydından ve depoya girmeyen `.local/` raporlarından okundu. Canlı kütüphane sayıları salt okunur bir SQLite bağlantısıyla alındı.

| Ölçüm | Ne bulundu | Sınırı |
|---|---|---|
| P4 kapanışı (D34, 15 Eylül) | Kurt 2017 sorusu, 18 bilinen eser: 9'u bulundu ve dahil edildi, 6'sı alıntılandı. Yanıt 3: 15 iddia, 13 destekli, 2 kısmen; yanlış atıf yok. | Tek soru, tek çalışma, Claude'un incelemesi. D44 öncesi arama. |
| İzole Luna değerlendirmesi (`.local/kurt-deixis-eval-2026-09-16`) | 128 tekil kayıt, 89 dahil; bilinen doğrudan 4 eserden 3'ü bulundu, 2'si alıntılandı. 48 pasajlık girdi özetlerle doldu, PDF sayfası girmedi. | Bilinen küme katmanları "geçici", insan etiketi değil. |
| Tablo denemesi (D43, 16 Eylül) | 23 hücre adımının 19'u geçerli; 152 geçerli model hücresi. Rastgele 12 hücrede 10 doğru, 2 kısmen, 0 yanlış (iki denemede de). | Claude'un okuması; 24 hücre kalite farkı gösteremez. Sütunlar modelin önerisi. |
| Pasaj seçimi tekrar oynatması (`.local/passage-selection-2026-09-16`) | Çeşitlilik varyantı PDF'li kaynak sayısını 7'den 9'a çıkardı. | Alıntılanan pasajlar etiket değil; model çağrısı yok. |
| D44 (sorgu derleme) | Yalnız sentetik testler. | Canlı geri çağırma ölçülmedi. |
| D52 (Marker) | 50 denklemde 48 doğru, 1 küçük hata, 1 yanlış; metin katmanı denetimi 29 denklemde 2 gerçek hatayı yakaladı. | Yanıt ve hücrede denklem aktarımı ölçülmedi. |

**Ölçüm aracı:** `scripts/p4_eval/measure.py` bir yanıt için bağlantı denetimi, Crossref kimlik denetimi, bilinen küme kapsamı (katmanlı), yeniden açma karşılaştırması ve insanın işaretlediği bir inceleme sayfası (`review.md` → `score`) üretir. Tablo hücreleri, PDF edinme yolu ve verilen pasajlar için karşılığı yok; tablo denemesinin betikleri (`drive.py`, `sample.py`) yalnız `.local/` altında.

**Canlı kütüphane (salt okunur):** 23 araştırma, 17'si çöpte değil. 26 yanıt (18 yapısal olarak geçerli, 8 doğrulanmamış taslak). 2 kanıt tablosu; 14 geçerli model hücresi, 4 doğrulanmamış öneri; bir doldurma çalışması iptal edilmiş. Kullanılan 83 PDF: 82 `succeeded`, 1 `partial`; 20'sinde Marker denklem okuması var (486 pasaj). OCR pasajı yok. Kurt araştırması (`res_IXBsnzhYZsKByEdTpSJo`) duruyor.

## 2. Ne ölçülür

Her satır kendi paydasıyla raporlanır; biri iyileşince diğeri iyileşmiş sayılmaz.

| # | Aşama | Sayı | Etiket nereden |
|---|---|---|---|
| M1 | Arama | Bilinen eserlerden kaç tanesi en az bir sağlayıcı sonucunda (katman başına) | Sahibin bilinen kümesi (önceden dondurulur) |
| M2 | Tarama | Bilinen ve bulunan eserlerden kaçı modelce dahil önerildi; dahil edilenlerin kaçı konuyla ilgili | Bilinen küme + ilgililik işareti |
| M3 | PDF edinme | Dahil edilen bilinen eserlerden kaçında PDF metni var, hangi yolla (açık bağlantı, ikinci kopya, kullanıcı, Zotero) | Kayıtlı adımlar; etiket gerekmez |
| M4 | Pasaj verme | Etiketçinin "soruyu cevaplayan pasaj" dediği sayfalardan kaçı yanıt girdisine girdi | Önceden işaretlenmiş sayfa listesi |
| M5 | Tablo hücresi | Doğru / kısmen / yanlış; `not_found_in_inspected_scope` ve `unknown` için "gerçekten yok muydu" | Hücre inceleme sayfası |
| M6 | Yanıt iddiası | Destekler / kısmen / desteklemez (yanlış atıf); okuma düzeyi doğru mu | Mevcut `review.md` |
| M7 | Denklem ve sayı | Denklem ya da sayı içeren iddia ve hücrelerde PDF sayfasıyla karakter karakter uyuşma | Sayfa karşılaştırması |
| M8 | İşletim | Geçerli adım oranı, onarım, çağrı, süre, token | Kayıtlı çalışmalar |

## 3. Kurallar

- **Canlı kütüphaneye yazılmaz.** Ölçüm canlı kütüphanenin bir kopyasında, ayrı `DEIXIS_DATA_DIR` ve ayrı portta yapılır (D43'teki 8799 düzeni).
- **Model açıkça seçilir.** Bütün gerçek model adımları `gpt-5.6-luna` ile, her rol ayrı ayrı yazılarak çalışır; başka modele geçilmez.
- **Beklenti önce yazılır.** Çalıştırmadan önce her M için beklenen aralık ve "şunu görürsem varsayım yanlış" koşulu bir dosyaya yazılır ve commit'lenir (§6). Sonuç sonradan yorumlanıp beklentiye uydurulmaz.
- **Etiket ile sonuç ayrılır.** Bilinen küme ve cevap sayfaları çalıştırmadan önce dondurulur. Sonuca bakıp etiket değiştirilirse bu ayrıca yazılır.
- **İnsan ve ajan etiketi ayrı raporlanır.** Claude'un okuması "insan denetimi" diye geçmez; ikisi aynı hücreye bakmışsa uyuşma oranı raporlanır.
- **Ayar değişikliği ölçüm değildir.** Bu dilimde kod ya da yöntem paketi değişirse, değişiklikten önceki ve sonraki çalışma ayrı raporlanır ve ayar yapılan soru "tutulmuş" soru sayılmaz.
- **Sonuç kalite iddiası değildir.** İki soru ve tek model genelleme göstermez; rapor bunu söyler.

## 4. Senaryolar

### S1. Kurt 2017 sorusu, baştan

Kopyada yeni bir araştırma: aynı soru, Luna, akademik arama. Arama ve tarama (M1, M2), PDF toplama (M3), gerekirse sahibin yüklemeleri ayrı sayılır. Seçim sahibin bilinen kümesine göre değil, modelin önerisi ve sahibin tek geçişlik düzeltmesiyle yapılır; düzeltme süresi yazılır. Sonra yanıt (M4, M6, M7) ve sabit sütunlu tablo doldurma (M5, M7).

### S2. Tutulmuş ikinci soru

Sahibin literatürünü bildiği ikinci bir soru, kendi bilinen kümesi ve cevap sayfalarıyla. Bu soruda hiçbir ayar yapılmaz; S1'de bir şey değiştirilirse S2 değişiklikten sonra bir kez çalıştırılır.

### S3. Tekrar

Yanıt ve tablo doldurma, aynı girdilerle bir kez daha çalıştırılır. İki çalışma arasındaki fark, bir ayarın etkisi sayılmadan önce bilinmesi gereken gürültüdür.

### S4. `not_reported` kararına yeniden bakış

Dilim 1 kararı 5, bütün sayfalar verilse bile modelin `not_reported` yazmasını yasaklıyor ve "ölçümden sonra yeniden bakılır" diyor. M5'te `not_found_in_inspected_scope` hücrelerinin kaçında değer yayında gerçekten yoktu, sayılır. Karar bu sayıyla ayrıca verilir; bu dilimde kural değişmez.

## 5. Araç

- `scripts/p4_eval/measure.py` genişletilir ya da yanına `scripts/p5_eval/` gelir: bilinen küme ve cevap sayfası dosyası (katmanlı), tablo hücresi inceleme sayfası (hücre, değer, alıntı, sayfa bağlantısı, doğru/kısmen/yanlış/"yayında gerçekten yok" işaretleri), PDF edinme yolu tablosu, verilen pasajların cevap sayfalarıyla kesişimi ve `compare` ile çalışmaları yan yana koyma.
- Araç modelsiz testlerle gelir (sentetik görünüm JSON'u). Çalışma çıktıları ve etiketler `.local/p5-measure-<tarih>/` altında kalır, depoya girmez; sonuç özeti karar kaydına yazılır.

## 6. Önceden yazılacak beklentiler (taslak)

Sayılar §8 yanıtlarından sonra kesinleşir. Mevcut ölçümlere dayanan ilk tahmin:

- M1: Kurt kümesinde 18 eserden 9–12'si bulunur. **Varsayım yanlış sayılır:** 9'un altı (D44 geri çağırmayı düşürmüş olabilir).
- M3: dahil edilen bilinen eserlerin yarısından azı kullanıcı yüklemesi olmadan PDF metni alır (IEEE eserleri açık değil).
- M5: sahibin etiketlediği değer hücrelerinde yanlış oranı %10'un altında. **Yanlış sayılır:** %20'nin üstü.
- M6: yanlış atıf 0–1; kısmen destekli iddia 1–3.
- M8: hücre adımlarının en az 19/23'ü geçerli (D43 tekrarı).

## 7. Varsayımlar

- Kopya, ölçüm başladığı gün canlı kütüphaneden alınır; sahibin kurumsal erişimle eklediği PDF'ler kopyada vardır. Arama ve tarama yeni araştırmada baştan yapıldığı için M1–M3 bundan etkilenmez; M3 kullanıcı yüklemelerini ayrı sayar.
- Marker kuruluysa kopyadaki okumalar kullanılır; kopyada yeni Marker okuması başlatılmaz (saatler sürer).
- Anlamsal arama canlıdaki ayarla (Gemini) çalışır ve rapora yazılır.

## 8. Sahibe sorulanlar

Her soruda önerim ilk seçenek. **Sahibin yanıtı (17 Eylül 2026): yedisinde de a.**

1. **Hangi sorular.**
   - a. Kurt 2017 (mevcut 18 bilinen eser, katmanlar gözden geçirilir) + sahibin seçeceği tutulmuş ikinci bir soru ve onun 10–20 bilinen eseri. (öneri)
   - b. Yalnız Kurt 2017.
   - c. Üç ya da daha fazla soru.
2. **Kim etiketler.**
   - a. Sahip küçük bir örneği etiketler (soru başına 20 hücre + 10 iddia + bilinen kümenin cevap sayfaları, toplam ~1–1,5 saat); Claude kalanını etiketler; ikisi ayrı ve örtüşen kısımdaki uyuşma raporlanır. (öneri)
   - b. Hepsini Claude etiketler (D34'teki gibi), rapor "ajan denetimi" der.
   - c. Hepsini sahip etiketler.
3. **Tablo sütunları.**
   - a. Soru başına 5–6 sabit sütun, sahiple önceden yazılır, çalıştırmalar arasında değişmez; en az biri sayı+birim, biri denklem ya da formülasyon. (öneri)
   - b. Modelin önerdiği sütunlar (D43 gibi).
   - c. D43'teki 8 sütun, yalnız Kurt için.
4. **PDF edinme.**
   - a. Önce yalnız DEIXIS yollarıyla (açık bağlantı, ikinci kopya) ölçülür; sonra sahibin kurumsal PDF'leri eklenir ve ayrı sayılır. (öneri)
   - b. Kopyadaki mevcut PDF'lerle başlanır; M3 ölçülmez.
   - c. PDF eklenmez; yalnız açık erişimle ölçülür.
5. **Tekrar sayısı.**
   - a. Arama bir kez; yanıt ve tablo doldurma iki kez. (öneri)
   - b. Her şey bir kez.
   - c. Yanıt ve doldurma üçer kez.
6. **Model.**
   - a. Bütün roller `gpt-5.6-luna` medium; inceleyici model (D14) açık ve o da Luna. (öneri)
   - b. Aynısı, inceleyici kapalı.
   - c. Luna'ya ek olarak aynı girdilerle bir Claude çalışması (karşılaştırma).
7. **Araç nereye.**
   - a. `scripts/p4_eval/measure.py` genişletilir (tek ölçüm aracı), modelsiz testleriyle depoya girer; çıktılar `.local/`. (öneri)
   - b. Ayrı `scripts/p5_eval/`.
   - c. Tek seferlik `.local/` betikleri (D43 gibi), depoya araç girmez.

## 9. Alt adımlar

1. **Etiketlerin dondurulması.** Bilinen küme(ler), cevap sayfaları, sabit sütunlar ve §6 beklentileri yazılır ve commit'lenir (etiket dosyası kitap künyesi içerdiği için yalnız DOI ve sayfa numarasıyla; PDF'ler depoya girmez).
2. **Ölçüm aracı.** §5; modelsiz testler önce kırmızı görülür.
3. **Kopya ve çalışmalar.** S1, S2, S3; her çalışmanın kimlikleri ve beceri paketi özeti kaydedilir.
4. **Etiketleme.** Sahibin örneği ve Claude'un kalanı; uyuşma.
5. **Rapor ve karar.** Karar kaydına D-girdisi (Evidence ve Limits); plan §10'a sonuç satırları; S4 için ayrı öneri.
6. **Kapanış.** Ölçümün gösterdiği ilk iki sorun için ayrı tasarım notu önerisi; bu dilimde düzeltme yapılmaz.

## 10. Alt adım 1 için sahipten beklenenler

1. **İkinci soru** ve onun 10–20 bilinen eseri (DOI; yoksa tam başlık), katmanlarıyla (ör. doğrudan ilgili / komşu bağlam).
2. **Kurt bilinen kümesi — donduruldu (17 Eylül 2026).** Sahibin verdiği makale PDF'inden (`kurt2017packet.pdf`) kuruldu: [`scripts/p4_eval/sets/kurt2017/known-sources.txt`](../../scripts/p4_eval/sets/kurt2017/known-sources.txt). Hedef makale + [12]–[28] arası 17 eser; katmanlar makalenin 1. sayfadaki kendi gruplamasıdır (karasal 9, sualtı 4, yeraltı 1, beden alan ağı 3). 15'inin DOI'si Crossref'te tam başlıkla bulundu; [12] ve [20]'nin DOI'si yok, başlıkla eşlenir. D34 "hedef + 18 eser" diyordu; makalenin paket boyutu listesi 17 eserdir, fark kayıtta yok. [25]'in iki DOI'si aynı esere gider (`infocom.2008.54`, `infocom.2007.54`); `measure.py` şimdilik tek DOI eşlediği için araç adımında takma ad desteği eklenir.
3. **Sabit sütunlar** (soru başına 5–6). Kurt için taslak:
   - Optimize edilen amaç (enerji verimliliği, ömür, verim, gecikme)
   - Kanal ve hata modeli (BER/PER ifadesi, kodlama)
   - Optimum paket boyutu (sayı + birim, hangi koşulda)
   - Amaç fonksiyonu ya da enerji modeli denklemi (formülasyon)
   - Ağ ve uygulama bağlamı (WSN, akıllı şebeke, sualtı, beden alan ağı)
   - Değerlendirme yöntemi (analitik, benzetim, test ortamı)
4. **Cevap sayfaları**: her bilinen eser için soruyu cevaplayan sayfa numaraları. Sahibin etiketleyeceği örneğin parçasıdır (§8 soru 2); PDF'i kopyada olan eserler için Claude önce aday sayfa listesi çıkarır, sahip onaylar ya da düzeltir.
