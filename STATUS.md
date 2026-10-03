# DEIXIS durumu

Projenin genel durumu için tek kaynak bu dosya. Notion'daki "Plan durumu" sayfası bunun kopyası; ikisi her push'ta birlikte güncellenir. Ayrıntılı sayılar `docs/decisions.md` içindeki D kayıtlarında. ✅ bitti · 🟡 sürüyor · ❌ yapılmadı ya da ölçülmedi · ⏸ bekliyor.

**Son güncelleme:** 3 Ekim 2026 · P7 G1 B5 (D196): G1 koşullu kabul, P7 çıkışı karşılanmadı (G1-F1, P7-F2, P7-F3 kaldı); H9 rapor koşusu IV. bölümde durdu (D171 sonuç), düzeltme partisi RF (D198) sürüyor

## Şu an çalışanlar

Kural (sahip, 3 Ekim): yazan ve inceleyen her zaman farklı şirketin modeli. Sol (gpt-6.1-sol) yazarsa Claude inceler, Claude yazarsa Sol inceler. Sahip onayı gereken kararlar Sol medium ile ortak verilir.

- ✅ **P7 G1 B5** (D196): G1 kabul kaydı yazıldı (`docs/product/p7-acceptance-record.md`). İç, sürümlü arama sözleşmesi koşullu kabul edildi: 2.686 uyum testi geçti, on bağlayıcı ve on bir uç nokta; tam pytest 12.377 geçti, 0 başarısız. README ve api-and-data artık "kaynak, kod tabanında incelenmiş adaptörle eklenir; paket sürümü kaynak ekleyemez" diyor. P7 çıkışı karşılanmadı. P10'dan önce üç parti kaldı: G1-F1 (lookup ve atıf zincirini sözleşmeye bağlama), P7-F2 (PubMed alt isteklerini bütçede sayma), P7-F3 (anahtarlı OpenAI gömme testi). Kararlar Claude ve Sol medium ortak; metni Claude yazdı, Sol high 3 turda inceledi, son tur “hazır”. Kod değişmedi.
- ✅ **P7 G1 B4** (D194): arama gönderimi artık facade üzerinden (istekler ve yanıtlar aynı); dört adlandırılmış değişiklik: kota ile geçici hız sınırı ayrı duraklama nedeni, S2 toplu yanıtları konuma göre değil kimliğe göre bağlanıyor, kayıtlı yüklerde anahtar yok, kimliği kullanılamayan kayıt atılıp sayılıyor; kayıtlı sayfa sürümü değiştiyse devam reddediliyor (göç 0067). Sol yazdı, plan Sol medium 3 turda, kod Claude 2 turda hazır; 12.235 test geçti. Lookup yetenek bağlama ve RetryPolicy yürütümü takvimsiz; G1 kabulü B5'te.
- ✅ **H9 1. dondurma** (D171): K01–K12 Claude + Sol medium ile sahip adına kararlaştırıldı; konu elektrikli araç şarj zamanlaması, model Luna medium, anahtarsız kaynaklar. Ayrı oturum açılmış bir Codex dizini yok; canlı `codex-home` dar istisnayla kullanılacak. H8 bağımlılığı açık istisnayla geçildi (matris çifti H9 ile aynı anda koşmaz). Model çağrısı yapılmadı. Sol high incelemesi 8 turda “hazır” demedi; 8765 yolu sadeleştirildi (başlangıç denetimi + koordinatör kuralı), son turun 3 orta bulgusu düzeltildi ve Sol medium doğrulamasında “hazır”; 1. kapı geçti.
- ✅ **H9 2. dondurma** (D171 ek A, `7a34e3e`): hazırlık 21 dk'da tek denemede bitti; 7 eserlik tablo rapora hazır (3 otomatik, 4 kuyruk geçişinden; 5 satırda yalnız özet okunabildi, çünkü ürün seçimi yalnız özet taşıyan yayımlanmış sürüme koyuyor). Ürün Türkçe soruda İngilizce anahtar terim istedi; terimler Claude + Sol medium kararıyla verildi. 5 R9 çifti seçildi. Sol high 3 turda “hazır” dedi.
- ✅ **H9 ölçüldü, rapor tamamlanmadı** (D171 sonuç): 7 eserlik yeni korpusta tek rapor koşusu (Luna medium) IV. bölümde durdu; model onarım çıktısında paket hash'ini yanlış kopyaladı ve atıf çapalarını hedefsiz bıraktı. Yalnız R1 (0/1 tamamlandı), R7 (178 s, 7 çağrı) ve P19 kayıtlı; R2-R11 ölçülemedi, okur çalışmadı. Sonuç: `docs/product/p9r-report-results.md`.
- ✅ **P7 G1 B3b** (D193): sorgu yazımı ve kuralları her bağlayıcının registry bildirimine taşındı; yazım ve kural kodunda sağlayıcı dalı kalmadı (eski `compile_queries` stratejisinin OpenAlex/SerpApi seçimleri derleyici politikası olarak duruyor), yeni bir kaynak yalnız registry kaydıyla sorgu alabiliyor. Değişiklikten önce dondurulan 39.586 çağrının çıktısı bayt bayt aynı; yalnız bildirilmemiş uç noktalar için 97 girdi artık reddediliyor (adlandırılmış değişiklik). Sol yazdı, plan Sol medium 3 turda, kod Claude 2 turda hazır; 11.686 test geçti. Gönderim hâlâ registry üzerinden; sırada B4.
- ✅ **P7 G1 B3a** (D179): facade seçenek türünü, izinli değerleri ve yeniden deneme sayısını göndermeden denetliyor; 566 doğrudan/facade eşitlik vakası, 181 gönderim biçimi ve 88 yeniden deneme/zaman aşımı uyum testi (yeni takım 925 test); Sol yazdı, plan Sol medium 3 turda, kod Claude 1 turda hazır; 11.180 test geçti. Gönderim hâlâ registry üzerinden; B3b (sorgu yazımı) ayrı parti, sonra B4.
- ✅ **P7 G1 B2** (D178): sağlayıcı uyum test takımı (641 test, 566 sentetik vaka); anahtar sonradan silinirse istek sayılmıyor ve arama tablosu bozulmuyor; PubMed kota türü, bozuk 200 yanıtı, boş sayfa imleci, başlıkta anahtar ve geçersiz bekleme düzeltildi; Sol yazdı, Claude 2 turda hazır; 9.992 test geçti. Seçenek türü denetimi B3a'ya, kimliksiz kayıt kabulü B4'e kaldı.
- ✅ **P7 G1 B1** (D177): iç bağlayıcı sözleşmesi (`contract.py`), facade ve 111 sentetik uyumluluk vakası; çalışma akışı değişmedi; Sol yazdı, Claude 2 turda hazır dedi; 9.231 test geçti. Bulunan iki kusur (PubMed EFetch `error_kind` kaybı, S2/IEEE yanlış kökte çöküş) B2'ye yazıldı.
- ✅ **P9 RR-B** (D170): kodu Sol yazdı, Claude inceledi; Claude'un düzeltmelerini Sol 10 turda inceledi, son iki tur "hazır". RR-A'nın iki API testi artık derlenmiş web varken de geçiyor. Matris beş koşuda temiz bir çift vermedi (biri tam geçti; diğerleri yük, başka batch'in portları, K02b). Boş makinede iki koşu gerekli.
- ✅ **P8 B1** (D181): inceleme sözleşmesi, anlık görüntü, tablolar, bayatlama kuralı; Sol yazdı, Claude 2 turda hazır dedi; 8.839 test geçti.
- ✅ **P7 G6–G8, G11, G12** (D173): kota ile hız sınırı ayrıldı, kotası biten sağlayıcıya koşu boyunca istek gitmiyor (devam ve yeniden denemede sıfırlanır); Sol yazdı, Claude 3 turda hazır.
- ✅ **P8 B8a** (D185): aday incelemesi; adayın güncel sürümü, bitmiş son ön çalışma taramasıyla birlikte başka bir modele incelettirilebiliyor. İnceleme, taramayı yapan modelin gördüğü metnin saklanmış kopyasını okuyor; sürüm, tarama ya da sahip durumu değişince eskimiş olarak işaretleniyor. Kabul yalnız kararı kaydediyor, adayı düzenlemiyor (tasarımdaki "önceden doldurulmuş düzenleyici" yerine, Sol medium ile ortak karar). Sol yazdı, plan Sol medium 3 turda, kod Claude 5 turda hazır; sentetik veri ve betikli model. Gerçek modelle aday okuması ve P8 kapanış kaydı B8b'de.
- ✅ **P8 B4** (D184): inceleme ilk kez gerçek modelle çalıştı (Claude Sonnet 5.5, orta efor; vakaları Claude Opus 5.5 yazdı, model seçimi Sol medium ile ortak). Dondurulmuş 8 sentetik vakada, tek koşu: 9 yerleştirilmiş hatanın 9'u bulundu, 15 temiz iddianın hiçbirine bulgu düşmedi (yanlış bulgu oranı: payda 0, ölçülmedi); 6 davranış vakasının 5'i geçti, RB02 (sahip notuyla uydurma hata isteği) bağlantı hatası yüzünden ölçülmedi. 11/20 gönderim, Codex'te Luna çağrısı yok. Gerçek rapor üzerinde ölçüm değil.
- ✅ **P8 B3** (D183): inceleme ekranları; inceleme, cevabın ya da raporun kendi sayfasında istenir, okunur ve karara bağlanır; kabul edilen bulgu rapora yalnızca düzenleyicinin kontrollü kaydıyla geçer; Sol yazdı, Claude 4 turda hazır dedi; 9.350 test geçti. Gerçek modelle inceleme B4'te.
- ✅ **P8 B2** (D182): inceleme koşusu ve rotaları; önizleme, başlatma, gruplu çalıştırma, bulgu kararları, kabul edilen bulgunun mevcut düzenleyiciyle uygulanması (kanıt değiştiyse 409); Sol yazdı, Claude 2 turda hazır; 8.963 test geçti. Gerçek modelle inceleme B4'te.
- ✅ **Yeniden işleme R1** (D190, göç 0066): bir metin çıkarımının kendi kimliği var; kurtarma denemesi eskisinin yanına yeni bir kayıt olarak yazılır, hangisinin geçerli olacağına test edilmiş tek bir kural karar verir; eski pasajlar ve atıflar değişmez. Henüz düğme ya da rota yok (R2a). Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır; 9.614 test geçti.
- ✅ **Yeniden işleme R2a** (D191): bir kişi, başarısız ya da yarım kalmış bir metin çıkarımını uç nokta ya da CLI ile bir kez yeniden deneyebiliyor; dosyanın hash'i kontrol edilmiş özel bir kopyası, dosya başına kilit altında okunuyor; deneme sürerken o kaynağı tutan araştırmanın koşusu bekliyor. Kendiliğinden yeniden deneme yok; düğme R4'te, dosya onarım makbuzu R2b'de. Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır; 9.781 test geçti.
- ✅ **Yeniden işleme R2b** (D192): bozuk bir PDF'i yeniden yükleyen, indiren ya da içe aktaran her yol artık tek bir onarım fonksiyonundan geçiyor; bozuk baytlar silinmeden ayrı bir dosyada saklanıyor, bir onarım makbuzu yazılıyor ve o dosyayı okuyabilecek bir koşu sürerken onarım reddediliyor. Kayıtlı metin değişmiyor; kişi R2a'daki yeniden denemeyle metni kurtarıyor. Eşleştirme artık dosya yazmıyor. Saklanan baytlar R3'e kadar yedeğe girmiyor. Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır; 10.528 test geçti.
- ✅ **Yeniden işleme R2c** (D195): çöken bir süreçten `running` kalmış metin denemesi ya da dosya onarımı artık o dosyanın kilidini alan ilk iş (açılış, worker'ın her turu, aynı dosyanın sonraki denemesi ya da yüklemesi) tarafından `process_ended` olarak kapatılıyor; metin kendiliğinden yeniden denenmiyor, onarım hiçbir zaman "başarılı" sayılmıyor, yalnız dosyanın o anki hâli kaydediliyor. Denklem (Marker) ve arXiv okuyucuları da aynı kilidi alıyor; dosya meşgulse hiçbir şey yazmıyor, koşuyu durdurmuyor. Gerçek alt süreç öldürme, gerçek `SQLITE_FULL`, ayrıştırıcı sınırları ve enjekte `ENOSPC` testleri var. Sol yazdı, plan Sol medium 4 turda, kod Claude 2 turda hazır.
- ✅ **Küçük kalanlar** (D175): dışa aktarma hatasının Türkçesi, slice 31 test eksikleri.
- ✅ **Onarılan dosyanın yeniden işlenmesi, tasarım** (D176); kodu R1–R5 partilerinde.
- ✅ **P7 G10 canlı deneme** (3 Ekim 02:48): IEEE, Scopus, CORE, SerpApi birer arama, hepsi HTTP 200.
- ✅ **P7 G1 eklenti sözleşmesi tasarımı** (D174) ve **H9 dondurma taslağı** main'de.

## Sıradaki

1. RR-B matris çifti boş makinede (iki temiz koşu üst üste) → P9'un modelsiz kısmı kapanır
2. P7 kapanışı: G1-F1, P7-F2, P7-F3 (D196)
3. RF (D198): IV. bölüm onarım ve hash kopyalama hataları kodda düzeltilir; sonra H9b kısa yeniden ölçüm (Luna)
4. P8 B5–B8, sırayla
5. Yeniden işleme R3–R5; H10

Hedef: P10'dan önceki her şey. Kaba tahmin 1–1,5 hafta; en büyük belirsizlik H9.

## Aşamalar

| Aşama | İçerik | Durum |
|---|---|---|
| P0–P2 | Plan, sözleşmeler, yerel temel, model bağlantısı | ✅ |
| P3 | Arama ve kaynak işleme | ✅ tek arama akışı (D119) |
| P4–P5 | İlk web dilimi, kütüphane, kanıt tablosu | ✅ |
| P6 | Sentez ve rapor | ✅ beş dilim kapandı; gerçek model ölçümleri P9'a borç |
| P7 | Bağlantı kapsamı | 🟡 D172, D173 kapandı; G10 canlı erişim gösterildi; G1 koşullu kabul (D196, yalnız arama); çıkış karşılanmadı, G1-F1, P7-F2, P7-F3 kaldı; canlı hata/kota biçimleri ölçülmedi |
| P8 | Başka modelle inceleme, yayın takibi | 🟡 tasarım D180 + bölüm 15; ✅ B1 (D181), B2 (D182), B3 (D183), B4 (D184, sentetik vakalar, tek koşu), B8a (D185, aday incelemesi); sırada B5–B7 ve B8b |
| P9 | Web sağlamlaştırma | 🟡 H0–H8, RR-A, H6 düzeltmeleri bitti; RR-B kodu main'de (D170), matris çifti boş makinede bekliyor; H9 ölçüldü (D171): rapor tamamlanmadı, yalnız R1/R7/P19; H10 yok |
| P10 | macOS / Windows paketi | ❌ |

## Ölçülmemiş borçlar

- ❌ Gerçek modelle hiç rapor tamamlanmadı (P16, üç deneme: D124, D126, D128)
- ❌ Fikir zinciri gerçek korpusta ölçülmedi; keşif 99 işten 1'ini dahil etti (D141)
- ❌ Özgünlük araması K6 ölçümü (D154)
- ❌ Dilim 4 gerçek model raporla ölçüm (D157)
- 🟡 Bölüm IV alıntı çapası: hedefli onarım var, gerçek modelde ölçülmedi (D129)
- 🟡 Paralel yükte ara sıra düşen iki test; tek başına geçiyor
- ❌ `TODO.md`'de slice 13 ve 31'den devreden maddeler
