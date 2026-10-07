# DEIXIS durumu

**Son güncelleme:** 7 Ekim 2026.

## Şu an

D242 Dilim 1–3 (7 Eki): dilim 1–2 main’de (`cf15bdd`, Sol; Claude iki turda inceledi); dilim 3 çalışma ağacında tamamlandı, ayrı kod incelemesi bekliyor. Eski sw answer alternasyonu/kotası ve boş rescue çıktısı kaldırıldı; attached/D119 ortak retrieval ve D238 passage dağıtımı korundu. Test eşlemesi `.local/docs/product/legacy-removal-test-map.md` dilim 3 bölümünde: sekiz test frozen-list’e taşındı, beş eski test silindi, iki test güncel davranışla değiştirildi. Tam pytest: 14.025 geçti, 2 atlandı; bilinen 15 P9 teardown hatası ve 18 sandbox socket/ps/pkill hatası, yeni düşüş yok. Lint geçti (16 mevcut uyarı), `git diff --check` geçti. Commit, canlı veri erişimi ve servis restartı yok. D239’daki `off` geri dönüşü kaldırıldı; geri dönüş `git revert`. Ardından D241’in kurt/uwsn etkisi canlı ölçülecek.

**P9 kapandı, P10’a hazır** ([D218](docs/decisions.md#d218--p9-exit)). Son matris çifti `0af3216` üzerinde iki kez geçti: pytest 14.265 toplandı, 0 başarısız, 23 atlandı; süreç 45/45; tarayıcı 212/212. Bu, tek macOS arm64 makinede sentetik kayıt ve betikli model kanıtıdır; kapasite satırları paralel yük altında koştu. H9e ilk kabul edilen gerçek model raporunu tamamladı; kalite koşullarının çoğu aralık dışında. D217 ölçüm kümesini kapattı, bütün borçları kapatmadı.

Kural (sahip, 3 Ekim): yazan ve inceleyen farklı şirketin modeli; Sol yazarsa Claude, Claude yazarsa Sol inceler. Sahip adına kararlar Sol medium ile ortak verilir.

## Sıradaki

0. Küçük partili arama (7 Eki, Sol + Claude): donmuş birleşik liste ve partili inceleme (D237), saklı politikayla cevap girdisi dağıtımı (D238) uygulandı; yeni koşularda varsayılan `on`, eski koşular saklı politikalarıyla, yeni aramada `off` geri dönüşü (D239). Gate2 maliyet medyanları geçti, hedef kimliği kapısı geçmedi; D239 ölçüm sonrası kapı revizyonudur. Açık işler: Hakim atıf seçimi, UWSN 09 recall, cevap derinliği ödünü, bütçe sonunda öncelik bölümünün ortasında kalma; P@20 etiketleri sahipte. 1–2 haftalık kullanımda kaynak kaybı/işlem sorunu görülürse `off` (D242 ile geçersiz; geri dönüş `git revert`). Kanıt: `.local/benchmark/2026-10-07-small-batch-gate2/SUMMARY.md`. 7 Eki sonrası: model etiketli isabet (Sol + Claude kör, insan etiketi yok) uzlaşı P@20 eski→yeni dbr 0,65→1,00, kurt 0,00→0,25, uwsn 0,00→0,05, irs 0,55→0,90 (`.local/benchmark/2026-10-07-precision/SUMMARY.md`); cevap derinliği darboğaz değil, iki aşamalı cevap ertelendi; kurt/uwsn sıfır include nedeni hedeflerin tam metne ulaşamaması (sağlayıcı 429, açık tam metin yok) ve koşudan koşuya değişen criterion rolleri (D241 ile düzeltildi, kayıtlı veride tutarlı; canlı ölçüm bekliyor); bekleyen PDF listesi küçük parti run'larında da çalışıyor (D240); Playwright 217/218 (candidate.spec.ts:590 kararsız).
1. P10: macOS paketi. Rapor kalitesi çalışması (kanıt kesilmesi, çok parçalı iddialar) isteğe bağlı ve sahip kararıyla.

## Tamamlanan fazlar

Her faz için ne yapıldığı ve neyin ölçülmediği. Ayrıntı [karar kaydında](docs/decisions.md).

- **P0 Plan ve denetim:** Uygulama planı yazıldı, Fable incelemesinden geçti, bulgular yanıtlandı. (D1)
- **P1 Yöntem ve sözleşme:** Model adımlarına giden yöntem paketi (`methods/deixis-research/`) ve adım girdi/çıktı şemaları (`contracts/`) kuruldu.
- **P2 Yerel temel:** FastAPI arka uç, worker, SQLite ve Codex bağlantısı çalışıyor; model, DEIXIS'e ait ayrı bir Codex dizininde açık model adıyla çağrılıyor. (D2, D3)
- **P3 Arama ve kaynak işleme:** Akademik arama, PDF bulma ve sürüm kontrolü, pasaj sıralaması kuruldu. Uzun SW dilim serisinden sonra tek arama akışı `sw` oldu, eski akış kaldırıldı; aramanın bilimsel başarı ölçümleri geçmedi. (D119, D114)
- **P4 İlk web dilimi:** Sorudan kaynaklı cevaba, vurgulanabilir atıfa ve araştırmayı yeniden açmaya kadar web arayüzü çalışıyor; dar bir gerçek kaynak ölçümüyle kapandı. (D34)
- **P5 Kütüphane ve kanıt tablosu:** Kaynak sürümleri, kanıt tablosu hücre geçmişi, çöp kutusu ve OCR eklendi; iki soruluk gerçek model ölçümüyle kapandı, genelleme değil. (D55)
- **P6 Sentez ve rapor:** Beş dilim uygulandı: kaynak bağlı rapor, gelişim çizgileri (lineage), aday fikir ve kill-search, rapor düzenleme, LaTeX. Kod tamam; gerçek modelde yararlılık ölçümleri P9'a taşındı ve çoğu hâlâ açık. (D142, D154, D157)
- **P7 Bağlantı kapsamı:** Bütün akademik sağlayıcılar tek bir iç bağlayıcı sözleşmesinden geçiyor; istekler sayılıyor ve bütçeleniyor, kota ile hız sınırı ayrı. Canlı hata ve kota biçimleri ölçülmedi. (D201)
- **P8 İnceleme ve takip:** Cevap, rapor ve aday fikirler başka bir modele incelettirilebiliyor; araştırmalar yeni yayınlar için zamanlanmış takipte tutulabiliyor. Sentetik vakalarda yerleştirilen hataların hepsi bulundu; gerçek raporda inceleme kalitesi ölçülmedi. (D189)
- **P9 Web sağlamlaştırma:** Kurulum, çökme ve kurtarma, disk dolu, yedek/geri yükleme, erişilebilirlik ve kapasite sınandı; tam test matrisi iki kez üst üste geçti. Gerçek modelle ilk kez bir rapor baştan sona tamamlandı, ama kalitesi hedeflerin altında. (D218, D202)

## Açık işler

Bütün eksikler burada; ayrı TODO dosyası yok. Parantezdeki D numaraları [karar kaydına](docs/decisions.md) gider.

### Ölçülmedi (gerçek model veya gerçek kullanım gerekiyor)

- Rapor kalitesi: H9e'de R1a, R2, R4b, R5, R7 süre, R8, R11 aralık dışında. R2'de 4 yanlış atıf, 18 kısmi destek; iki model okudu, insan bakmadı. Gözlenen nedenler: bölüm girdisi tablo hücrelerinin çoğunu kesiyor (H9b B'de 117 hücre), çok parçalı iddialarda çapa alıntısı çoğu zaman tek parçayı taşıyor, özet ve sonuç gövdede olmayan ayrıntı ekliyor. Tek konu, tek koşu. (D202, D218)
- Denklem, çift ve inceleme: R6'da denklem birimi yok, R9'un yedi çifti ölçülemedi, R10 hiç ölçülmedi. (D202, D218)
- Rapor düzenleme E06–E18: 18 işlemden 5'i ölçüldü; kabul, kaldırma, geri yükleme, dışa aktarım, yedek/geri yükleme sınanmadı. (D215, D217)
- Soy zinciri L9 (R12–R15): hiçbir korpusta ölçülmedi; yeniden hazırlanmayacak. (D216, D217)
- Kill-search K6/S2: S2 paydası sıfır, en yakın işler hiç bulunmadı; sorgu biçiminin suçlu olduğu gösterilmedi. (D212)
- Çöküş kurtarma H10: gerçek Codex ile hiç koşulmadı; tekrar çağrı ve fatura bilinmiyor. (D218)
- Günlük kullanım: sahibin yedi günlük kullanım günlüğü yok; H7 bulguları test ve kod okumasından. (D165)
- Planted prior-art ölçümü: yayımlanmış bir makalenin fikrini aday diye ver, kill-search onu bulup `closed` diyor mu bak. Bu koşulana kadar "Novelty Checker'dan iyi" yalnız tasarım iddiası.

### Ortam ve platform

- İkinci kullanıcı kurulumu (temiz hesap, başka makine, proxy) ölçülmedi. (D161, D168)
- Erişilebilirlik: VoiceOver ve diğer ekran okuyucular, okuma sırası, yüzde 400 yakınlaştırma ölçülmedi. (D167)
- Kapasite: sessiz makinede tekrar, gerçek PDF karışımı, canlı model gecikmesi, yük altında eş zamanlılık yok; H8 K02c N=100 eksik. (D166, D170)
- Hata sınırları: elektrik kesintisi, kernel panic, APFS disk dolu ölçülmedi; OCR/JATS çocuk süreç sınırları sürüyor. (D159, D162, D164)
- Platform: eski macOS, Intel, Linux, Windows desteklenmiyor; başka makineye geri yükleme ölçülmedi. P10'da ele alınacak.

### Kod düzeltmeleri

- K03 sürücüsü: kuyruk geçişi prompt boyutunda düşüyor; bayt bütçesi eklenmedi. Paketleme engeli sayılmadı. (D216, D217)
- Yeniden çıkarım R5: T10 arka plan okuyucuyu (D52) yürütmüyor (T10 matris satırı yok); aday/soy güncellik görünümü (`recovery_view.py`, `TextRecovery.tsx`). Türkçe Zotero notları (D222) ve PDF önbelleği (D223) kapandı; geri yükleme sırasında açık PDF görüntüleyici eski belgeyi göstermeyi sürdürür, kapatıp açınca yenisi gelir. (D208)
- İlk cevap taslağı atıf çapası kurallarını hep bozuyor (9/9); onarım turu düzeltiyor ama cevap başına 46–134 s ekliyor. Nedeni bulunmadı.
- `detailed` süre: tam metin alma ve okuma tek başına 20 dakika hedefini aşıyor (23 Eylül ölçümü).
- Test borcu: dilim 31'den kalan uçtan uca iddialar tam karşılanmadı; aralıklı paralel test hataları; CI yok. (D119, D175)

### Canlı deneme bulguları (4–5 Eki, sualtı DBR/VBF sorusu)

Tek soru, GPT-5.6 Luna, Standard derinlik, üniversite VPN'i açık (`res_qqOHHl3hGsZWrihkkwBW`). Sahip sırası: önce sayaçlar.

- Sayaçlar ve etiketler: tam metin satırı çalışırken "135 downloaded" diyor, gerçek 26 (`Transcript.tsx` `detail()` 'pdf' her başarılı adımı topluyor); okuma koşusu "Downloaded 54 open-access PDFs" diyor (52 model okuması + 2 kod adımı); tam metin okuma ve Marker denklem okuması da "Downloading open-access PDFs" başlığıyla görünüyor (`Transcript.tsx:71`); "provider requests 15/8" bütçeyi aşmış görünüyor.
- Arama onay ekranı karışık; sadeleştirilmiş mockup onaylandı (claude.ai/artifact/VR863qYoKQoapvVnrUw6n8). Model "sensor networks"ü tek başına Setting bloğuna koydu, eşleşme 535'ten 18.369'a çıktı, ekran uyarmadı; uygulama "bu terim olmadan" sayısını kendi hesaplamalı.
- Tam metin karar ekranı karışık: makale başına tek soru olmalı; listedeki başlık kaynak çekmecesini açmalı (.impeccable.md §3 kuralı, uygulanmamış). Sources'taki "Undecided 1323" çoğunlukla "okunmadı" demek, etiket yanıltıcı.
- Ölçüt önerisi sorudaki karşılaştırmayı her makaleye şart yaptı; tek protokol anlatan VBF/ADBR makaleleri takıldı, 24 kararı sahip verdi. Başlıkta survey/review geçen 90 iş elendi, 60'ı yönlendirme derlemesi.
- Tam metin sınırı (~112) yüzünden 689 adaydan 579'u hiç denenmedi, 57'sinin başlığı DBR/VBF ailesinden. Cevap sıralamanın tepesinden kuruluyor ve ekran bunu söylemiyor.
- Cevap koşusu her dahil PDF için Marker'ı bekliyor (PDF başına saniyelerden ~5 dakikaya); kapatma düğmesi yok, Remove okuma sürerken kilitli (`Connections.tsx:242`). Öneri: "PDF metniyle şimdi cevapla" düğmesi.
- MDPI, SAGE ve ScienceDirect PDF'leri 403 (ULAKBİM çıkışı, tarayıcı kimliğiyle de); VPN'siz karşılaştırma yapılmadı.
- Cevap (GPT-6 Sol, 17 iddia, 12 pasaj, 25 kaynak): Luna incelemesinde 16 destekli, 1 kısmi; insan bakmadı. Asıl soruya sayısal cevap yok: "aynı koşullarda DBR–VBF karşılaştırması pasajlarda yok" diyor. Doğrudan karşılaştıran Lee & Seah 2007 (OCEANS) PDF'iyle dahildi ama cevap ondan yalnız PDR ve enerji tanımlarını aldı, sonuçlarını almadı (seçilen pasajlara sonuçlar girmemiş olabilir; bakılmadı). 17 iddianın 15'i "It has been reported that…" kalıbıyla başlıyor: `methods/deixis-research/references/source-grounded-answer.md` yalnız phrasebank çerçevelerine izin veriyor ve kaynak aktarımı için örnek olarak tam bu kalıbı veriyor; tekrar sınırı yok. Sahip cevabın bölümlü rapor (Abstract, Introduction, Bulgular…) olarak çıkmasını bekliyordu; rapor ayrı akış ve kanıt tablosu gerektiriyor (Evidence sekmesi), ekran bunu söylemiyor. Sahip tablo akışını da karışık buldu (sütun öner → ekle → satır doldur → boş hücre → Write report); öneri: Answer ekranında tek "Bölümlü rapor yaz" yolu, sütunları ve doldurmayı kendisi yapsın, kullanıcıya yalnız sütun listesini bir kez onaylatsın. Aynı ekranda 26 dahil kaynağın yalnız 16'sı modele verildi, 11'i atıf aldı (48 pasaj sınırı).
- Elicit karşılaştırması (5 Eki, aynı soru, "Draft report", GPT-6 Sol low): ~40 s, onay ekranı yok; "16 kaynak bul → 19 kaynakta doğrudan simülasyon kanıtını karşılaştır → rapor yaz". Rapor (Özet / Neden değişiyor / Yorum, 6 atıf, takip soruları) asıl soruya sayısal cevap verdi: DBR, VBF'den %33,6 daha enerji verimli ve %19,8 daha iyi PDR (Maulana 2019), Hakim 2018 da aynı yönde; özetten çalıştığını açıkça söylüyor. **Bu iki doğrudan karşılaştırma DEIXIS'te de vardı** ("Analysis of VBF and DBR Performance… Aquasim at NS-3" 2019 ve "Energy Consumption Analysis of DBR and VBF Protocols… Aqua-Sim" 2018): ikisi de özet aşamasında aday oldu, tam metin sınırına takılıp hiç denenmedi, cevaba girmedi. Ders: cevap aday özetlerini de kullanabilmeli; sıralama iki aileyi birlikte anan doğrudan karşılaştırmaları öne almalı.
- Elicit'in 6 atfı DEIXIS'te: 5'i bulundu, 1'i bulunamadı (Memon 2018, "Performance Comparison of Routing Protocols for Underwater Sensor Networks"). Bulunan 5'ten yalnız Xie 2010 cevaba girdi; Maulana 2019 ve Hakim 2018 aday kalıp denenmedi, Yan 2008 (DBR) ve Nicolaou 2007 (HH-VBF) açık tam metin bulamadı. Arama geri çağırımı yeterli; kayıp cevap politikasında.
- Hangi sorgu buldu (sağlayıcı yüklerinden): Maulana 2019'u yalnız sorunun kelimelerinden kurulan geniş sorgu buldu; modelin `"underwater acoustic" AND …` sorgusu getirmedi (makale "underwater wireless sensor network" diyor). Hakim 2018'i iki sorgu da buldu; genişletme ve atıf zinciri ikisini de getirmedi. Geniş sorgu gürültülü ama kapatılmamalı; modelin tek tam ifadesi fazla dar.
- Derleme kaynakçası ölçümü (5 Eki, OpenAlex, model yok): kenara konan en ilgili 8 yönlendirme derlemesinin hiçbiri Maulana 2019, Hakim 2018 ya da Memon 2018'e atıf vermiyor (3'ünün OpenAlex'te kaynakçası boş). Anahtar makaleler az atıf almış (8, 7, 0) bölgesel konferans/dergi işleri. Derlemeleri atıf zinciri tohumu yapmak bu soruda kazandırmazdı. Buna karşılık Maulana, Hakim'e atıf veriyor: iki sorgunun da bulduğu Hakim'den ileri atıf zinciri Maulana'ya ulaşırdı; zincir yalnız sıralamanın ilk 15'inden başladığı için denemedi.
- Ölçüm dersi: adımlar hatasız bitti, alıntılar bulundu, ikinci model 16/17 "destekli" dedi, yine de cevap soruyu cevaplamadı. Bugünkü ölçütler cevabın dürüstlüğünü ölçüyor, işe yararlığını ölçmüyor.

**İlerleme (5 Eki):** (1) kıyas testi `scripts/benchmark/check.py` (2b6e0d7); eski koşuda geçmiyor. (2) özet adayları cevaba giriyor (D225): yeniden koşulan cevapta Maulana 2019 sayılarıyla atıf aldı, Hakim 2018 girmedi, kapı (a) hâlâ geçmiyor. Sahip adım 3'e geçilmesini seçti. (3) karşılaştırma sorusunda task terimlerini birlikte anan kayıtlar sıralamada yükseliyor (D226): çevrimdışı Maulana 105 → 51, Hakim 233 → 73; ilk 50 hedefi tutmadı, yeni keşif koşusu yapılmadı. Adım 4 bitti (sahip "uygun şekilde ilerle" dedi; kararlar Sol ile): onay ekranı yalnız terim şişirme uyarısında (D227), karşılaştırma ölçütü tek alternatifi kabul ediyor (D228), tam metin kararında makale başına tek soru, cevap 3–5 kısa paragraf + otomatik çalışma tablosu + yöntem kutusu, 11 bölümlü rapor Evidence'ta "Makale taslağı" (D230), "PDF metniyle şimdi cevapla" düğmesi. Uçtan uca canlı kıyas koşusu (9f5583b, ~26 dk, ~140 model çağrısı): 6 makalenin 6'sı bulundu (Memon 2018 sıra 46, D231 gerçek koşuda da tuttu), ama kapı (a) yine geçmedi: Maulana 2019 sayılarıyla atıf aldı (c1, c3), Hakim 2018 (sıra 24, özet adayı, tam metin yok) modele verilmedi; Memon tam metni doğrulandığı hâlde 24 kaynaklık cevap girdisine girmedi. Onay ekranı çıkmadı, 16 satır karar kuyruğunda kaldı, tablo 27 satır × 8 sütun otomatik doldu. (4) Memon 2018'i hiçbir sorgu bulmuyordu, çünkü protokolleri yalnız "DBR" ve "VBF" diye anıyor. İkinci tur artık birinci turun özetlerinin tanımladığı kısaltmaları kodun geniş ortam terimiyle arıyor (D231): bugünkü koşunun kopyasında `underwater AND (DBR OR VBF)` 6 makalenin 6'sını buldu, önce 5/6'ydı. Gerçek bir keşif koşusunda denenmedi.

**6 Eki, D233:** Kelime önerisi artık yalnız bilgi: `warn` modunda hiçbir terim silinmiyor, öneri başarısız olsa da kart açılmıyor; eksik öneri geçersiz. Zaman çizelgesi ham "1.340 kaynak" yerine huni gösteriyor (aramayla gelen kayıt · zincirle eklenen · benzersiz çalışma → okunan özet → aday → dahil). Kod sorgusunu daraltma (varyant D) son koşunun kayıtlarında 1.336 → 1.131 verdi, 6/6 ve 28/28 dahil korundu, ama OpenAlex sınırlarını (5 operatör, 2 zorunlu parça) aştığı için ertelendi; 1.336'nın 590'ı atıf zincirinden. Canlı koşu yok.

**Sahip kararı (5 Eki), sırayla:** (1) bu soru + Elicit'in 6 makalesi kıyas testi olsun; geçme: Maulana 2019 ve Hakim 2018 cevaba girer, cevap DBR–VBF yönünü sayıyla söyler; (2) tam metni olmayan adaylar özetiyle cevaba girsin, iddiada "yalnız özet" yazsın; (3) iki aileyi birlikte anan doğrudan karşılaştırmalar sıralamada öne çıksın; (4) 2–3 testi geçince akışı sadeleştir: onay ve karar ekranları yalnız uyarıda, kanıt tablosu beklemeden Özet/Bulgular/Yorum raporu, Marker cevabı bekletmesin; (5) kalan ekranlarda sayaç ve etiket düzeltmesi; (6) sahibin vereceği 2–3 soru daha kıyas testine. Baştan yazım ve katı rapor formatı şimdilik yok. Plan: `.local/docs/product/elicit-convergence-plan.md` (yerel, git dışında).

### Ertelenmiş fikirler (sahip kararı bekler)

- Örnek sorular: soru kutusunun altında yalnız kutuyu dolduran 2–3 tıklanabilir örnek.
- Kütüphaneden süreklilik: "bu kaynak X araştırmasına dahil edilmişti" gibi veritabanından hesaplanan ipuçları. Sohbet tarzı gizli "bellek" planlanmıyor.
- PDF indirme teşhisi: HTML veya 403 dönen en fazla 20 açık erişim vakasını düz Chromium ile aç, nedeni sınıflandır (`citation_pdf_url`, JavaScript, çerez duvarı, bot engeli). Bot engelini aşmak planlanmıyor.
- Sorgu örtüşme uyarısı: iki sorgunun terimleri büyük ölçüde örtüşüyorsa uyarı (onarım değil).
- Tanıtım sayfası (landing page): tıklanabilir demo, yöntem, sınırlar, kurulum ve atıf blokları. Mockup `.local/docs/site/landing-mockup.html` (4 Eki). Örnek kayıtlar sentetik; BibTeX'te yazar adı yer tutucu. "Download" butonu imzalı macOS paketi (Apple Developer hesabı + notarization) çıkana kadar kaynaktan kurulumu gösteriyor. P10 sonrası yayın (GitHub Pages); yayından önce içerik kesinleşince bir `/impeccable` inceleme ve cila turu.
- Kill-search: aday kartındaki iddia öğelerini RRF'de ayrı sinyal olarak kullanmak; Semantic Scholar snippet search'ü dördüncü yol olarak eklemek; `answer_review`'u geliştirirken kullanılmayan bir modelle değerlendirmek.
