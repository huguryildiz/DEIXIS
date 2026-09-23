# SW dilim 14a — Tam metin sırası

**Tarih:** 23 Eylül 2026. **Durum:** plan; aşağıdaki altı karar önerildiği gibi sahip tarafından onaylandı (23 Eylül 2026). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** D94 (dilim yazar). **Önkoşul:** 14 (kapandı, `9b57756`, D93).
**Tür:** Kur. **Uygulayan:** Opus · medium öneriyorum (satırda Opus · high yazıyor; karar 2 onaylanırsa iş iki sabit ve
testleri). **İnceleme:** toplu öneriyorum (satırda tam, Fable). **Plan:** Opus · high, 23 Eylül 2026 (prompt Fable ·
high diyordu; bu oturum Opus'ta koştu). **Yeniden oynatma:**
`.local/sw-slice14a-order-replay-2026-09-23/` (`protocol.md`, `result.md`, `replay.py`, `abstract_cut.py`).

**Goal:** Üçüncü D88 ölçümünde özet aşamasını geçen 13 / 17 / 21 doğrulanmış kuantum eserinden yalnız 1 / 7 / 17'si
tam metinde okundu. Satır 14a bunu sıranın kusuru saydı: tam metin planı inceleme sırasının başını alıyor, doğrulanmış
eserler sınırın gerisinde kalıyor. Bu dilim önce sırayı modelsiz yeniden oynattı. Sonuç: sıra kusurlu değil, sınır dar.
Dilim sıra kuralını değiştirmez, yalnız `quick`'in iki tam metin sınırını iki katına çıkarır (karar 2).

## Elimizdeki sayılar

Hepsi yeniden oynatmadan, on bir kütüphaneden: kuantumda üçüncü ölçüm (m3) ve dilim 14'ün iki kabul koşusu (a14, a14b)
× üç efor, pakette iki kabul koşusu (`detailed`). Oynatma m3'te saklanan getirme planını üç eforda da birebir verdi.

1. **Sinyaller doğrulanmış eserleri öne koyuyor.** Kuantumda BM25, bloklar ve çizge doğrulanmış aday eserleri
   havuzun %3–26'sına, öbür adayları %12–77'sine koyuyor (ortanca). Bugünkü sıra, grupların içinde rastgele sıranın
   yaklaşık iki katını buluyor: planda `quick` 16 / 8,2, `standard` 28 / 14,0, `detailed` 60 / 40,9 (üç koşunun
   toplamı). On bir kütüphanenin hiçbirinde TF-IDF koşmadı (kullanıcı tohumu yok) ve gömme kapalıydı.
2. **Özet aşamasının kararı sıraya zaten ulaşıyor**, grup düzeyinde: kullanıcının dahil ettikleri → `candidate` →
   `unresolved` + `fulltext_fetch` (D83). Promptun ilk adayı ("dahil edilenler önce, sonra sıra") bugünkü planın aynısı.
3. **Plana aday olan eser, planın aldığından çok fazla.** `quick`'te 40 yere 234–348, `standard`'da 100 yere 520–816,
   `detailed`'da 300 yere 676–797 eser. Adayların çoğunu model okumadı: başlığında iki blok da geçen eser kod kuralıyla
   (`blocks_in_title`) aday oluyor, m3 `quick`'te 246 adayın 215'i. 31 eserlik listeye göre modelin tuttukları
   (2/29, 6/73, 13/229) ile `blocks_in_title` (12/215, 12/308, 10/260) birbirinden belirgin biçimde ayrışmıyor.
4. **Hiçbir sıra adayı bugünkünü tutarlı biçimde geçmedi.** Planın alacağı doğrulanmış eser, üç kuantum koşusunun
   toplamı (sınırlar bugünkü gibi):

   | sıra | `quick` | `standard` | `detailed` | paket (iki koşu) |
   |---|---:|---:|---:|---:|
   | A bugün | **16** | **28** | **60** | 0, 0 |
   | B dahil edilenler önce (= A) | 16 | 28 | 60 | 0, 0 |
   | C modelin tuttuğu → kararsız → yalnız kod | 17 | 23 | 50 | 0, 0 |
   | D modelin tuttuğu önce, gerisi bugünkü gibi | 17 | 25 | 55 | 0, 0 |
   | E grubun içinde yalnız BM25 | 15 | 24 | 57 | 0, 0 |
   | F modelin tuttukları TF-IDF ve çizgenin tohumu (sonradan) | 16 | 29 | 61 | 0, 0 |
   | A, sınır iki katı (sonradan) | **28** | **45** | 65 | 0, 0 |
   | plana aday doğrulanmış eser (tavan) | 44 | 59 | 66 | 1, 1 |

   A–E sayılar görülmeden önce `protocol.md`'ye yazıldı. F, G, H ve sınırın iki katı sonradan denendi ve kural
   olarak önerilmiyor. Koşu başına sayılar `result.md`'de.
5. **Paket sorusu bu soruyu yanıtlayamıyor.** Havuzdaki 4 ve 3 bulunabilir eserden ikişeri özet aşamasında okunmadı
   (`abstract_not_read`, modelin kuyruğunda 357.–1.133.). Biri model tarafından kapsam dışı sayıldı. Aday kalan tek
   eser 2.342 ve 2.638 aday arasında 1.216. ve 1.663. sırada. Hiçbir sıra ve sınırın iki katı ona varmıyor. Pakette
   `blocks_in_title` 1.978 ve 2.092 eseri model okumadan aday yapıyor; blok sinyali de o tek eseri geriye itiyor.
6. **Özet aşamasında ikinci bir kesim var.** Modelin okuma sınırı da aynı sıranın başını alıyor (40 / 100 / 300). m3'te
   6 / 12 / 13 doğrulanmış başlık hiç okunmadı. Sınır iki katına çıksaydı bunlardan en çok 2 / 3 / 6'sı okunurdu
   (`abstract_cut.json`); model onları tutar mıydı, bilinmiyor.
7. **Süre** (m3, `quick`): getirme 0,5 dk (40 iş), tam metin okuma 1,2 dk (22 çağrı), toplam 7,5 dk; hedef 10 dk.
   `standard` 17,9 dk (hedef 15), `detailed` 39,7 dk (hedef 20).

## Sahibin onayladığı kararlar (23 Eylül 2026)

1. **Sıra kuralı değişmez.** Önerim: D79'un sırası ve D83'ün grupları olduğu gibi kalsın. Gerekçe: beş sabit adaydan
   ve sonradan denenen üç sıradan hiçbiri üç kuantum koşusunda A'yı tutarlı biçimde geçmedi. C, D ve E
   `standard` ve `detailed`'da 3 ile 10 eser kaybettiriyor. Paket sorusu hiçbirini ayırt edemiyor. Tek konuda +1
   bulan bir kuralı ürüne koymak konuya göre ayar olur.
2. **`quick`'in iki tam metin sınırı iki katına çıkar:** `FULLTEXT_WORK_LIMIT["quick"]` 40 → 80,
   `FULLTEXT_READ_LIMIT["quick"]` 20 → 40. Önerim bu. Gerekçe: yeniden oynatmada `quick` planı üç koşunun toplamında
   16 → 28 doğrulanmış eser alıyor, sıra kuralına dokunmadan. Süre tahmini (ölçülmedi): getirme +0,5 dk, okuma +1,2
   dk, `quick` ~9,2 dk, hedefin altında. Okuma iki katı çağrı ister (`quick` 40 → 80 çağrılık okuma bütçesi).
   Getirme sınırı okuma sınırının iki katı kalıyor, çünkü getirilen eserlerin yarısından azında PDF çıkıyor (m3
   `detailed`: 300'de 139). Seçenek: hiç kod değiştirmeden 14a'yı "ölçüldü, sıra değişmedi" diye kapatmak.
3. **`standard` ve `detailed` sınırları değişmez.** Önerim bu. `standard` zaten hedefin üstünde (17,9 / 15 dk).
   İki kat sınır tahminen ~6 dk ekler (getirme 2,8 + okuma 3,1 dk). `detailed`'da plan aday doğrulanmış eserlerin
   19–21 / 22'sini zaten alıyor. `standard`'da sınırın iki katı 28 → 45 getiriyor. Süreyi kabul ederseniz bu da
   açılabilir, ama hedefle çelişir.
4. **Özet aşamasının okuma sınırı bu dilimde değişmez.** Önerim ayrı bir iş olarak yazılması. Kazancı küçük
   (en çok 2 / 3 / 6 başlık) ve modelin kararı bilinmiyor. Sınır model çağrısı ekler: `quick` 4 → 8 çağrı.
5. **`blocks_in_title` kısa yolu bu dilimde değişmez.** Bu kural aday kümesini şişiriyor (pakette 2.000'e yakın
   eser), ama bu sıranın değil özet aşamasının tasarımının konusu (SW9, D81). Önerim bulgu olarak TODO'ya yazılması.
6. **Gömme ve tohumlu TF-IDF ölçülmedi.** İkisi de bu kütüphanelerde koşmadı. Gömmeyi yeniden oynatmak bir gömme
   sağlayıcısına istek ister ve anahtarsız seçenek yok. Önerim bu dilime almamak; sahip isterse ayrı ölçüm.

## Global constraints

- **Sıra kuralı, gruplar ve eleme değişmez** (karar 1). `fulltext.fetch_plan`, `adjudication.read_plan`,
  `ranking.py` ve özet aşaması byte byte aynı kalır.
- **Yalnız `quick`** (karar 2, 3). `standard` ve `detailed`'ın dört sabiti aynı kalır.
- **Model yok, yöntem paketi değişmez**, `skill_package_hash` aynı kalır.
- **Donmuş bütçeye saygı.** Kuyruğa girmiş ya da duraklatılmış bir koşu bütçesini kuyruğa girdiği andan alır
  (`fetch_budget`, `read_budget`). Yeni sınır yalnız bundan sonra kuyruğa giren koşulara uygulanır.
- Canlı kütüphane ve 8765 açılmaz, testlerde ağ yoktur. Canlı çalışan yalnız Task 3'ün kabulüdür.

## Task 1: iki sabit

- `domain/rules.py`: `FULLTEXT_WORK_LIMIT = {"quick": 80, "standard": 100, "detailed": 300}` ve
  `FULLTEXT_READ_LIMIT = {"quick": 40, "standard": 50, "detailed": 150}`. Yorumlarına tarih, D94 ve yeniden oynatmanın
  klasörü yazılır: "sıra değil sınır; `quick` 16 → 28 planda, üç koşu, tek konu; süre ölçülmedi".
- Protokol gövdesi (`fulltext_fetch.work_limit`, `fulltext_adjudication.read_limit`) sabitleri zaten okuyor; yeni
  `quick` revizyonları yeni sayıları yazar, eskiler değişmez.
- Arayüz metinlerinde bu iki sayı yazıyorsa (`i18n.ts`, `labels.ts`) aranır ve düzeltilir. Yazmıyorsa web'e dokunulmaz.

## Task 2: testler

- `tests/test_fulltext_plan.py::test_the_budget_of_a_retrieval_run_calls_no_model_and_sends_no_search`: beklenen
  liste `[80, 100, 300]`.
- Yeni, `tests/test_adjudication.py`: `read_budget("quick") == {"max_model_calls": 80, "max_provider_requests": 0,
  "max_fulltext_reads": 40}` ve `FULLTEXT_READ_LIMIT` için `[40, 50, 150]`.
- Yeni, `tests/test_fulltext_flow.py`: kuyruğa 40'lık bütçeyle girmiş bir `quick` getirme koşusu sürdürülünce 40'ta
  kalır (donmuş bütçe).
- `tests/test_protocol_record.py` sabitleri isimle okuyor; değişiklik gerekmez, geçtiği görülür.
- Sayı sabit kodlanmış başka test varsa (`grep -rn "40\b" tests/ | grep -i fulltext`) güncellenir; sıra testlerinin
  hiçbiri değişmez.

## Task 3: canlı kabul ve kapanış

- Düzen üçüncü ölçümün kampanyası (`.local/sw-measure-2026-09-24/campaign.py`): kendi sunucusu ve boş veri dizini,
  `DEIXIS_SEARCH_WORKFLOW=sw`, `DEIXIS_FULLTEXT_FETCH=auto`, `DEIXIS_FULLTEXT_ADJUDICATION=auto`,
  `DEIXIS_SEARCH_QUERY=model`, gömme `off`, onay `as_proposed`. Model `gpt-5.6-luna` · medium. Klasör
  `.local/sw-slice14a-acceptance-<tarih>/`. Beklenti ilk istekten önce `protocol.md`'ye yazılır.
- Koşular: kuantum `quick` (tam koşu, yanıt dahil) ve paket `quick` (tam koşu).
- **Kabul (K8):**
  1. **Süre**, dilimin kendi etkisi: kuantum `quick` baştan sona ≤ 10,0 dk. 10,0 ile 11,0 arasındaysa koşu bir kez
     daha yapılır, iyisi alınır. Hâlâ 10'un üstündeyse ve fazlası getirme ya da okuma aşamasındaysa dilim düşer:
     sabitler 40 / 20'ye döner ve sayılar satıra yazılır. Fazlası keşiften geliyorsa dilim geçer, sebep ayrı iş olur.
  2. **Okunan doğrulanmış eser:** kuantum `quick`, üçüncü ölçümün `quick`'iyle kıyaslanır (okunan 1, atıf alan 1).
     K8'e göre en çok 2 eksik kabul edilir. Taban 1 olduğu için bu koşul gevşek; asıl bilgi aşağıdaki sayıdır.
  3. **Paket `quick`:** süre ≤ 10,0 dk, aynı kural. Daha önce tam koşulmuş bir paket `quick`'i yok; okunan sayısı
     yalnız yazılır.
- **Yazılan, kabul koşulu olmayan sayılar:** yeni kütüphanede planın 1–40. ve 41–80. yerlerindeki doğrulanmış eser
  (`replay.py`'nin A sırası, bu klasörden kopyalanır); getirme ve okuma aşamalarının süresi m3'ün 0,5 ve 1,2 dk'sıyla
  yan yana; PDF bulunan iş sayısı.
- D94, `docs/decisions.md`'nin en üstüne yazılır (Status / Date / Context / Decision / Limits). Karar: sıra kuralı
  yeniden oynatmayla sınandı ve değişmedi; `quick`'in iki tam metin sınırı iki katına çıktı. Limits: tek konuda
  ölçüldü (paket sorusu adayları ayırt edemedi); 31 eserlik liste eksik bir ölçü; süre tek koşuyla ölçüldü;
  `standard` ve `detailed` bilerek değişmedi; özet aşamasının okuma sınırı ve `blocks_in_title` açık kaldı.
- Tam pytest; `git diff --check`; satır 14a → `uygulandı, inceleme bekliyor`; tek commit; push.

## Bu dilimde yok

- Sıra kuralında her değişiklik (karar 1): model kararına göre katman, BM25 tek başına, modelin tuttuklarını tohum
  yapmak.
- `standard` ve `detailed` sınırları (karar 3).
- Özet aşamasının okuma sınırı (karar 4) ve `blocks_in_title` kısa yolu (karar 5).
- Gömme sinyali ve tohumlu TF-IDF (karar 6).
- Atıf zinciri: dilim 15. Europe PMC: sahibin kararı, 14a'dan sonra.
- Dilim 14'ün açık bıraktığı iki iş (tek bloklu kod sorgusu, arXiv 406). Yeniden oynatma sıraya dokunduklarını
  göstermedi, bakmadı da.

## Ölçülmedi

- Sınırın iki katının süreye etkisi; tahmin m3'ün aşama sürelerinden (Task 3 ölçer).
- Planın 41.–80. yerlerindeki eserlerde PDF bulunma oranı. Yeniden oynatma yalnız plana giren eseri sayar.
- Gömme ve tohumlu TF-IDF'in sıraya etkisi.
- Doğru eser ölçüsü iki listeden geliyor: 18 Eylül havuzundan 31 kuantum eseri ve 4 paket eseri. Yeni aramaların
  bulduğu ama listede olmayan ilgili eserler sayılmadı; "isabet oranları" bu listeye göredir.
- Paket sorusunun `quick` ve `standard` kütüphanesi yok. Üçüncü bir alan, yöntem ağırlıklı olmayan bir soru ve modelin
  özet etiketlerinin koşudan koşuya değişmesi ölçülmedi. m3 `quick`'in neden en kötü koşu olduğu (A = 1; öbür iki
  koşuda 8 ve 7) incelenmedi.
