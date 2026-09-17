# Yanıt girdisinde PDF sayfalarına yer açmak: tasarım notu

**Tarih:** 17 Eylül 2026. **Durum:** Kabul edildi (17 Eylül 2026): sahip §6'daki altı soruda da ilk seçeneği seçti. §5'teki beklentiler bu hâliyle donduruldu. Alt adım 1–4 yapıldı; sonuç §8'de. Önceden yazılan geri alma koşulu biçimsel olarak tetiklendi; sahip kuralı tutup önce yanıt geçerliliğini düzeltmeyi seçti. Düzeltme ve yeniden karşılaştırma §9'da (D56).

**Kısaca:** P5 kapanış ölçümünde (D55) yanıtlar, PDF metni elde olduğu hâlde tek bir PDF sayfası kullanmadı. S1'de 52 kaynak dahil edilmişti, 6'sının PDF metni vardı ve 6'sı da yanıt modeline verildi, ama hepsi yalnız özetleriyle verildi: 20 dayanağın 20'si özetti. Sebep bir sayıdır, model değil: yanıt girdisi 48 pasajlıktır ve kod önce her dahil kaynağın özetini koyar. 48 ya da daha fazla kaynak dahil edilince bütün yer özetlerle dolar, PDF sayfasına sıra gelmez. Bu not, yer dağıtımını değiştirmeyi önerir. Aynı sorun P4'te (D20, D34) görülmüş, bir deneme yapılıp geri alınmıştı (§2).

## 1. Kodda bugün olan

17 Eylül 2026'da `main` (60b8504) üzerinden okundu.

| Parça | Davranış |
|---|---|
| `domain/rules.py` | Pasaj sınırı `quick` 16, `standard` 48, `detailed` 80. |
| `workflow/flow.py::_retrieve`, 1. döngü | Dahil kaynaklar `answer_source_order` sırasıyla (kullanıcı seçimi, sağlayıcı sayısı, BM25 ya da semantik sıra; D17, D27) dolaşılır. Her kaynaktan **bir** pasaj konur: özeti, yoksa en iyi eşleşen pasajı, yoksa ilk pasajı. Sınır dolunca döngü durur. |
| 2. döngü | Formülasyon sayfaları (`formulation_score` ≥ 3) için sınırın dörtte biri kadar yer, kaynak başına en çok 6 pasaj. Ancak 1. döngüden yer kaldıysa çalışır. |
| 3. döngü | Kalan yer, sözcük (FTS) ve varsa semantik sıralamanın RRF birleşimiyle doldurulur. |
| Tek ekli PDF istisnası (D19) | Tek kaynak, 48 pasaj, 12 sayfa ve 60.000 karakter içindeyse bütün sayfaları verilir. |
| Tablo doldurma (D38) | Başka yol: kaynak başına ayrı çağrı, kaynak başına 24 pasaja kadar. P5 ölçümünde S1 tablolarında değerlerin 17–22'si PDF sayfasından geldi. |

Yani sorun yalnız yanıt adımında: tablo aynı PDF'leri okuyabiliyor, yanıt okuyamıyor.

## 2. Şimdiye kadar görülenler

| Kaynak | Ne görüldü | Sınırı |
|---|---|---|
| D20 izlemesi (15 Eylül) | Kaynak başına bir formülasyon sayfası ayırınca 48 pasajın 46'sı özet, 2'si PDF sayfası oldu; iki sayfa da alıntılanmadı, alıntılanan eser sayısı 25'ten 18'e düştü. Değişiklik geri alındı. | Tek, stokastik karşılaştırma; iddia değil. O zaman dahil 84 kaynağın yalnız 4'ünde açık PDF vardı. |
| D34 (P4 kapanışı) | 51 kaynakla yanıt 2'nin dayanakları: 35 özet, 0 PDF sayfası. Seçim 25 kaynağa indirilince yanıt 3'ün dayanakları: 32 özet, 14 PDF sayfası. | Seçimi elle daraltmak işe yaradı, ama 0,40 dakikalık bir ajan düzeltmesiydi. |
| Pasaj seçimi tekrar oynatması (`.local/passage-selection-2026-09-16`) | 25 kaynaklı girdide çeşitlilik (MMR) varyantı PDF'li kaynak sayısını 7'den 9'a çıkardı. | Model çağrısı yok; alıntılanan pasajlar etiket değil. |
| D55 (P5 ölçümü) | S1: 52 dahil, 6 PDF'li; girdi 48 kaynağa birer pasaj, dayanakların 20'si de özet. S2: 52 dahil, yalnız 1 PDF'li, dayanakların hepsi özet. S1'de üç yanıttan ikisi geçersiz kaldı (`missing_citation_anchor`). | Claude'un incelemesi. S2'de sorunun asıl kaynağı PDF'in hiç olmaması. |

İki ayrı darboğaz var ve bu not yalnız birincisini çözer:
1. **Yer dağıtımı:** PDF metni olduğu hâlde verilmiyor (S1).
2. **PDF edinme:** Kapalı erişimli IEEE/Springer eserlerinde metin hiç yok (S2'de dahil bilinen 5 eserin 0'ı, 52 dahil kaynağın 1'i). Bunun için bugün kullanıcı yüklemesi, D49 eşleştirme ve Zotero var; bu not ona dokunmaz.

## 3. Öneri

**Kaynak başına kota:** Sıralama bugünkü gibi kalır. PDF metni olan bir kaynak özetiyle birlikte en iyi 2 sayfasını alır (3 pasaj). Yalnız özeti olan kaynak 1 pasaj alır. Kaynaklar sırayla eklenir, bütçe dolunca durulur. Böylece S1'deki 6 PDF'li kaynak 18 pasaj, kalan 30 yer 30 özet olurdu: 52 kaynağın 36'sı yanıta girer, 16'sı girmez (bugün 48 girip 4'ü girmiyor).

- **Sayfa seçimi:** Kaynağın kendi pasajları arasında bugünkü FTS + semantik RRF sıralaması, formülasyon skoru eşitlikte öne alır. Yeni model çağrısı yok.
- **Girmeyen kaynaklar:** Yanıtın `inputs_given` alanı zaten hangi kaynakların verildiğini tutuyor. Sınırlama metni, kaynak adıyla değil sayıyla "N dahil kaynak bu yanıta girmedi" der. D55'te görülen kısa kimlik sızıntısı (`srv_S0000002`) ayrı bir hata olarak düzeltilir (§7, alt adım 1).
- **Kural koşulu:** Kota yalnız metni olan kaynak sayısı + PDF'li kaynak başına 2 sayfa bütçeyi aştığında devreye girer (uygulamada netleşti: S1'de metni olan tam 48 kaynak vardı, "bütçeyi aşınca" koşulu hiç tetiklenmiyordu); az kaynaklı yanıtın bugünkü davranışı (özetler + formülasyon + sıralı pasajlar) aynen kalır. Bu, D34'teki 25 kaynaklı iyi sonucu bozmamak içindir.

**Neden D20 denemesinden farklı:** O denemede her kaynağa bir sayfa ayrıldı ama kaynakların çoğunda PDF yoktu, yani sayfa alan 2 kaynak oldu. Burada kota PDF'li kaynakların hepsine birden 2 sayfa verir ve bunun bedelini listenin sonundaki özetler öder. Bunun alıntılanan eser sayısını düşürmesi beklenir; ölçülecek olan budur (§5).

## 4. Seçenekler

| | Ne değişir | Artı | Eksi |
|---|---|---|---|
| **A. Kaynak başına kota (öneri)** | Yukarıdaki kural | PDF'li her kaynak sayfayla girer; model çağrısı ve girdi boyu aynı | Sondaki kaynaklar yanıta hiç girmez |
| B. Sabit bölme | 48'in yarısı özet, yarısı sıralı PDF sayfası | Basit | Bir kaynak 6 sayfa alıp ötekiler hiç almayabilir; sıralama PDF'siz kaynakları keser |
| C. Bütçeyi büyütmek | `standard` 48 → 80 | Hiçbir kaynak düşmez | Girdi ~%70 uzar; D11/D12'deki kimlik kopyalama hataları uzun girdide çıkmıştı; S1'deki iki geçersiz yanıt 48 pasajdaydı |
| D. Önce model okuması (PaperQA2 benzeri) | Her kaynağın sayfaları küçük bir model adımıyla özetlenir, yanıt özetleri okur | Derinlik en yüksek | Kaynak başına ek çağrı; alıntı zinciri iki adıma bölünür, D12 bağları yeniden tasarlanır |

## 5. Ölçüm planı

Kurallar D55'teki gibi: kopya kütüphane, commit'lenmiş kod, `gpt-5.6-luna` medium, beklentiler önce yazılır.

1. **Çevrimdışı tekrar oynatma (model yok):** D55'in S1 ve S2 araştırmaları, kopya üzerinde, bugünkü kural ve A kuralıyla. Sayılır: verilen PDF sayfası, PDF'li kaynak, verilen kaynak, verilen bilinen eser.
2. **Canlı karşılaştırma:** S1'de her kural için 2 yanıt. S2'de PDF neredeyse olmadığı için yalnız "davranış değişmedi" denetimi, 1 yanıt.
3. **İnceleme:** D55 sayfalarıyla: iddia desteği, yanlış atıf, dayanak türü, alıntılanan bilinen eser, geçerlilik.

**Önceden yazılan beklentiler (donduruldu, 17 Eylül 2026):**
- S1 çevrimdışı: A kuralında verilen PDF sayfası ≥ 12 (6 kaynak × 2). **Yanlış sayılır:** < 6.
- S1 canlı: PDF sayfasına dayanan en az bir iddia her yanıtta. **Yanlış sayılır:** iki yanıtta da 0.
- Yanlış atıf 0–1 kalır. **Yanlış sayılır:** ≥ 3.
- Alıntılanan bilinen eser 6'dan en çok 2 düşer (sondaki kaynaklar düştüğü için). **Yanlış sayılır:** 3 ve altı.
- Geçerli yanıt oranı düşmez (D55'te S1 1/3).

## 6. Sahibe sorulanlar

Her soruda önerim ilk seçenek. **Sahibin yanıtı (17 Eylül 2026): altısında da a.**

1. **Kural.** a. Kaynak başına kota (A). b. Sabit bölme (B). c. Bütçeyi büyütmek (C). d. Önce model okuması (D).
2. **PDF'li kaynağa kaç sayfa.** a. 2 (özetle 3 pasaj). b. 1. c. 3.
3. **Kota ne zaman devreye girsin.** a. Yalnız dahil kaynak sayısı pasaj bütçesini aşınca. b. Her zaman.
4. **Özet kalsın mı.** a. PDF'li kaynakta da özet verilir (kimlik ve genel bulgu için). b. PDF'li kaynakta özet yerine üçüncü sayfa.
5. **Yanıta girmeyen kaynaklar.** a. Sınırlama metninde sayı; kaynak listesinde bugünkü "incelendi" sayacı yeterli. b. Kaynak satırında "bu yanıta girmedi" etiketi de eklenir.
6. **Ölçüm.** a. Çevrimdışı tekrar oynatma + S1'de kural başına 2 canlı yanıt, Claude inceler. b. Yalnız çevrimdışı. c. Canlı yanıt sayısı kural başına 3.

## 7. Alt adımlar

1. **Kısa kimlik sızıntısı:** Yanıt sınırlama metnindeki D12 bağları kaynak adına ya da sayıya çevrilir; test önce kırmızı.
2. **Beklentilerin dondurulması:** §5, sahibin yanıtlarıyla, commit.
3. **Kural:** `_retrieve` içinde kota; mevcut testler (D17, D19, D20, D27) korunur, yeni testler önce kırmızı.
4. **Çevrimdışı tekrar oynatma ve canlı karşılaştırma:** §5.
5. **Karar kaydı:** D-girdisi (Evidence, Limits); sonuç beklentiyi karşılamazsa değişiklik geri alınır ve bu da yazılır.

## 8. Sonuç (17 Eylül 2026)

Kod: `59759e2` (kısa kimlikler yanıt metninde kaynak başlığına çevrilir), `5826784` ve `f2ce474` (kota). Uygulamada koşul netleşti: kota, metni olan kaynak sayısı + PDF'li kaynak başına 2 sayfa pasaj sınırını aşınca devreye girer (S1'de metni olan tam 48 kaynak vardı). Backend: 520 geçti, 1 kaldı (bu makinede zaten kalan bellek sınırı testi). Çıktılar `.local/answer-pdf-pages-2026-09-17/`.

**Çevrimdışı tekrar oynatma (model yok, semantik sıralama kapalı, D55 kopyası):**

| | Eski kural | Yeni kural |
|---|---|---|
| S1 girdideki PDF sayfası | 1 | 12 |
| S1 PDF'li kaynak / verilen kaynak | 1 / 48 | 6 / 36 |
| S1 verilen bilinen eser (PDF sayfasıyla) | 6 (0) | 6 (5) |
| S2 | 47 pasaj, 5 PDF sayfası, 42 kaynak | aynı (kota tetiklenmedi) |

Beklenti (≥ 12 PDF sayfası) karşılandı.

**Canlı (`gpt-5.6-luna` medium, aynı kopya):** Yeni kuralla S1'de 2, S2'de 1 yanıt. Eski kural kolu olarak D55'teki aynı seçimli 3 S1 yanıtı kullanıldı (plan kural başına 2 yeni yanıt diyordu; sapma).

| | Eski kural (D55) | Yeni kural |
|---|---|---|
| S1 geçerli yanıt | 1 / 3 | 0 / 2 |
| S1 model denemeleri (onarımlar dahil) | 6 | 4 |
| Denemelerde PDF sayfasına giden atıf | 0 | 9, 7, 7, 6 |
| Denemelerde PDF sayfasına dayanan iddia | 0 | 8, 6, 5, 5 |
| S1 son denemedeki sorunlar | — | `duplicate_citation_anchor` 3; `missing_citation_anchor` 1 |
| S2 geçerli yanıt (girdi değişmedi) | 2 / 2 | 0 / 1 (`unknown_passage_id`, `missing_citation_anchor`) |

**Okuma:**
- Model yeni kuralla PDF sayfalarını kullanıyor: dört denemenin her birinde 5–8 iddia bir PDF sayfasına dayanıyor; eski kuralla altı denemede hiç yok.
- Ama hiçbir yeni yanıt geçerli olmadı, bu yüzden iddialar incelenemedi. Önceden yazılan "her yanıtta en az bir PDF dayanaklı iddia" ve "geçerli yanıt oranı düşmez" beklentileri geçerli yanıt üzerinden tanımlıydı ve karşılanmadı.
- Geçersizliğin kurala bağlı olduğu gösterilemiyor: girdisi hiç değişmeyen S2 yanıtı da bu kez geçersiz kaldı (D55'te 2/2 geçerliydi), S1 eski kuralla da 3'te 2 geçersizdi. Sorunların hepsi alıntı biçimi: bir pasajı alıntısız göstermek, aynı pasaj için iki alıntı, fazladan sıfırlı kısa kimlik.
- Örneklem çok küçük: kural başına 2–3 yanıt.

**Sahibe soru:** §7.5 sonuç beklentiyi karşılamazsa kuralın geri alınmasını söylüyordu. Öneri: kural kalır; yanıt geçerliliği ayrı bir iş olarak ele alınır (ör. aynı iddia ve pasaj için ikinci alıntıyı kabul etmek, D43'te hücreler için yapıldığı gibi; alıntısız atfı tek onarım yerine yalnız o atfı düşürerek çözmek), ardından bu karşılaştırma yeniden koşulur.

## 9. Geçerlilik düzeltmesinden sonra yeniden karşılaştırma (17 Eylül 2026)

**Ne değişti:** Tek onarımdan sonra hâlâ geçersiz kalan yanıt taslağında yalnız sorunlu atıflar atılır: aynı iddia ve pasaj için tekrarlanan alıntıdan bulunabilen ilki kalır, iddianın göstermediği pasaja alıntı atılır, alıntısı bulunamayan atıf iddianın alıntılı başka atfı varsa atılır. Hiçbir şey eklenmez, iddia silinmez; sonuç yeniden doğrulanır, her atılan uyarı olarak saklanır. Fazladan sıfırlı kısa kimlik doğru kimlik olarak okunur (`c28669a`). Saklı 9 yanıtın son denemesinde çevrimdışı: geçerli 3 → 8.

**Canlı** (aynı D55 kopyası, `gpt-5.6-luna` medium; kotasız kol aynı kodda kota koşulu kapatılarak):

| | S1 kotalı | S1 kotasız | S2 (kota tetiklenmez) |
|---|---|---|---|
| Geçerli yanıt | 3 / 3 | 3 / 3 | 2 / 2 |
| Kurtarma gereken yanıt | 1 | 2 | 2 |
| Atılan atıf | 1 (+2 tekrar alıntı) | 6 (+3 tekrar ya da fazladan alıntı) | 1 (+2 tekrar alıntı) |
| PDF sayfasına giden atıf | 3, 6, 9 | 0, 0, 0 | 0, 0 |

**İnceleme (Claude):** Kotalı koldaki 18 PDF sayfası atfının hiçbiri yanlış ya da ilgisiz değil; 12'si alıntı ve iddianın öteki dayanaklarıyla destekleniyor, 6'sında iddia alıntıların gösterdiğinden fazlasını söylüyor (biri akıllı şebeke çerçevesini başka bir makalenin sayfasına bağlıyor).

**Okuma:** §5'teki beklentiler karşılandı: kotalı her S1 yanıtında PDF dayanaklı iddia var, geçerli yanıt oranı düşmedi. Örneklem kol başına 3 yanıt; oran ölçülmüş değil. Çıktılar `.local/answer-salvage-2026-09-17/`.
