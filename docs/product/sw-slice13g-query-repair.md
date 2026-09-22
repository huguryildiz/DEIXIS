# SW dilim 13g — Arama sorgusunun onarımı, Scopus'un aramadan çıkması, `detailed` okuma sınırı

**Tarih:** 23 Eylül 2026. **Durum:** dosya hazır. **Ana dosya:** [sw-status.md](sw-status.md). **Kararlar:** D90
(sorgu kurma kuralları ve `detailed` okuma sınırı), D91 (Scopus aramadan çıkar, VPN'de son özet kaynağı). **Önkoşul:**
13f (uygulandı), sözcük deneyi (koşuldu, `.local/sw-vocabulary-experiment-2026-09-23/result.md`). **Tür:** Kur.
**Uygulayan:** Opus · high. **İnceleme:** tam (Fable); arama sorgusu neyin bulunacağını belirler, kanıtın en başıdır.
**Plan:** Opus, 23 Eylül 2026 (13f sohbeti).

**Uygulama notu (23 Eylül 2026):** Task 3 yazıldı, ilk canlı kabulü bozdu ve sahip kararıyla çıkarıldı; uygulanan Task 1, 2, 4 (D90, D91). Scopus `searchable=False` yerine yeni `sw_searchable=False` alanıyla çıktı, çünkü `searchable` legacy'yi de etkiliyordu. Ayrıntı [sw-status.md](sw-status.md) satır 13g.

**Goal:** Sözcük deneyi üç alanda (kuantum ağları, paket boyutu, yenidoğan sepsisi) bugünkü sorgu kurma kuralının
üç hatasını gösterdi ve modelin kendi yazdığı listenin koddan iyi olmadığını ölçtü (kuantumda 31 doğru eserin 9'u
karşı 18'i, paket konusunda 0 karşı 1). Bu dilim kodun listesini tutar ve üç hatayı düzeltir; Scopus'u aramadan
çıkarır; `detailed`'ın sorgu başına okuma sınırını 2.000'den 1.000'e indirir. Başarı canlı bir kabul ölçümüyle
sınanır: aynı üç soruda, bugünkü kurala göre en az o kadar doğru eser, daha odaklı sorgular.

## Deneyin gösterdiği (dilimin dayanağı)

1. **Görev bloğu tek terime iniyor.** `query_compiler._fit_blocks` OpenAlex'in beş operatör sınırına sığmak için
   sondaki bloktan (görev) başlayıp terim atıyor. Kısa kod listesinde görünmüyordu (2 ayar + 4 görev); uzun bir
   listede sorgu `(5 ayar terimi) AND "optimization models"` oldu ve 12 kayıt getirdi.
2. **İkinci tur görev bloğunu atıyor.** `expansion.expand` ilk turun en sık başlık öbeklerini (hepsi konu sözcüğü)
   ayar bloğuyla birlikte geçiyorlar diye kabul ediyor; ayar eş anlamlıları bu testi doğası gereği geçiyor,
   görev ve yöntem sözcükleri kalıyor. `second_round_vocabulary` sonra görev bloğunu bu kabul edilenlerle
   **değiştiriyor**: sorgu `(ayar) AND (ayar eş anlamlıları)` oluyor. Paket konusunda 166.353 kayıt, 0 doğru eser;
   kuantumda 12.559 kayıt. Ayrıca "quantum network", sorgudaki "quantum networks"ün tekili olduğu hâlde aday
   listesinden elenmiyor (`_holds_any` tam sözcük eşleşmesi arıyor); OpenAlex ikisini aynı sayıyor.
3. **Etiketleme sorgunun iskeletini bozuyor.** Paket sorusunda "channel" ve "error model" sorunun "karşılaştır"
   cümlesinden geliyor; kural onları görev bloğuna koydu, model üç çağrının üçünde ayar bloğuna taşıdı. "channel"
   tek başına 3,6 milyon kayıt; ilk tur 8.712 kayıtla doldu ve 6 doğru eserden 1'ini buldu. Kuantum sorusunda
   sorunun başı olan "mathematical optimization models"ı kural görev bloğuna koydu, model üç çağrının üçünde
   `claim` dedi ve öbek hiçbir sorguya girmedi.

Düzeltilmiş ikinci tur (deneyin C kolu: ayar eş anlamlıları ayar bloğuna, görev bloğu kalır) paket sorusunda
1.176 kayıtla, sorunun sözcükleriyle bulunabilen 4 doğru eserin 4'ünü buldu; kuantumda ilk turun 18'ine 1 ekledi.

## Global constraints

- **Kodun listesi kalır.** Sözcükleri sorudan kod çıkarır, blokları kural önerir, model (SW17) etiketleri gözden
  geçirir. Bu dilim modele yeni bir yetki vermez; yalnız modelin iki etiket kararını kodla sınırlar (Task 3).
- **Yöntem paketi ve sözleşmeler değişmez.** Düzeltmeler kodda; `skill_package_hash` başta ve sonda aynı. Etiketleme
  talimatının (`methods/deixis-research/references/vocabulary-labels.md`) değişmesi gerektiği görülürse **DUR VE
  BİLDİR**.
- **Konu sözcüğü ürün koduna girmez.** Kurallar sorunun biçimine (hangi cümle, hangi öbek) ve sayımlara bakar; hiçbir
  kural "quantum", "packet", "sepsis" gibi bir sözcüğü tanımaz. Test fikstürleri SYNTHETIC ve en az iki alandan.
- **`legacy` iş akışı değişmez.** Sorgu kurma değişiklikleri yalnız `sw` yolunda (`compile_block_queries`,
  `expansion`, `vocabulary`); `compile_queries` ve legacy derleyicisi byte byte aynı.
- **Donmuş protokol saygısı.** Sürdürülen koşu saklı sorgularını arar (bugünkü gibi); yeni kural yalnız yeni
  koşularda uygulanır. Protokol gövdesine yeni alan eklenirse sürüm notu D90'a yazılır.
- 13f'nin bütün testleri (`tests/test_search_parallelism.py` ve fikstürleri) geçmeye devam eder.
- Canlı kütüphane ve 8765 açılmaz. Testlerde ağ yok; canlı olan tek şey Task 5'in kabul ölçümüdür ve yalnız
  OpenAlex sayım / sayfa istekleri ile deneyin betikleri üzerinden yapılır.

## Task 1: sığdırma iki bloğa dengeli

- `_fit_blocks`: sorgu sınıra sığmıyorsa terim, **en çok terimi kalan bloktan** atılır; eşitlikte sondaki bloktan
  (bugünkü sıra). Her blok en az bir terim tutar (bugünkü kural). Blok içinde sondan atılır (sorudaki geçiş sırası).
- [ ] **Tests first:** 5 ayar + 4 görev terimi OpenAlex'te 3 + 3'e iner (bugün 5 + 1); 2 + 8 → 2 + 4 (bugünkü
  sonuç aynı kalır); iki alanın SYNTHETIC terimleriyle. `test_query_compiler.py`'nin bugünkü beklentileri, yalnız
  dengesiz bir listeyi sınayanlar değişir; değişen her beklenti son iletiye.

## Task 2: ikinci tur yalnız ekler, bloğunu kaybetmez

- Aday eleme: sorguda zaten olan bir terimin tekil / çoğul biçimi aday olamaz (`_holds_any` karşılaştırmasına
  sondaki `s`'i atan aynı kök kuralı; deneyin `arm_c.py::stems`'i gibi, genel sözcükler dışarıda).
- Kabul edilen her öbek iki sınıftan birine girer: **ayar eş anlamlısı** (ayar bloğunun bir teriminin köklerinden
  biriyle ortak, genel olmayan bir sözcüğü var) ya da **görev eki** (öbür hepsi).
- İkinci tur sorgusu: yeni ayar eş anlamlısı varsa `(yeni ayar eş anlamlıları) AND (ilk turun görev terimleri OR
  görev ekleri)`; yoksa ve görev eki varsa `(ilk turun ayar terimleri) AND (görev ekleri)`; ikisi de yoksa ikinci
  tur yok. Yeni ayar bloğu ilk turun OpenAlex sorgusundaki ayar genişliğine kesilir. Her iki biçim de ilk turun
  sorgusunu yeniden göndermez ("yalnız ekler", SW2.4).
- Kabul testi (`expand` içindeki sayım eşikleri) değişmez; yalnız kabul edilenin nereye gittiği değişir. Eşiklerin
  görev sözcüklerini eleyen etkisi (deneyde "resource allocation" 140 / 213.947) bu dilimde düzeltilmez; son
  iletide ve D90 Limits'te.
- [ ] **Tests first:** tekil / çoğul aday elenir; ayar eş anlamlısı ayar bloğuna, görev eki görev bloğuna gider;
  üç biçimin her biri (yalnız ayar, yalnız görev, ikisi) doğru sorguyu derler; ikinci tur ilk turun sorgusunu
  tekrarlamaz; `test_expansion.py` / `test_expansion_flow.py`'nin değişen beklentileri son iletiye.

## Task 3: etiketlemenin iki sınırı

Soru İngilizce bir tanıma sorusuysa (`extract`'ın bugün işlediği biçim) ve kuralın yerleştirdiği öbekler için:

- **Karşılaştırma cümlesinin öbeği ayar bloğuna giremez.** Sorunun "Compare …" (ya da kodun bugün tanıdığı eşdeğer
  karşılaştırma kalıbı) cümlesinden gelen bir öbeği model `setting` diye etiketlerse kod onu kuralın bloğunda
  bırakır. Gerekçe: ayar bloğu AND kapısıdır; bir özelliğin oraya girmesi sorguyu alanın dışına açar ("channel").
- **Sorunun baş öbeği sorgudan çıkamaz.** Soru cümlesinin başındaki öbeği ("Which <öbek> have been …") kural
  görev bloğuna koyduysa, model onu `claim`, `outcome` ya da `not_a_term` diye etiketlese de görev bloğunda kalır.
- İkisi de etiketleme adımının çıktısında görünür: öbeğin satırına modelin cevabı, kuralın bloğu ve bu sınırın
  adı yazılır (SW17'nin `rule_block` / `runs` alanlarının yanına). Sessiz bir geri alma yok.
- Karşılaştırma cümlesinin öbeklerini görev bloğundan da çıkarmak (sonuca taşımak) **bu dilimde yok**: kuantumda
  ilk turun 18 doğru eseri tam da bu öbeklerle bulundu; çıkarmanın etkisi ölçülmedi.
- Bu iki kalıbı sorunun biçiminden güvenilir biçimde tanımak mümkün değilse (dil, cümle yapısı) kural yalnız
  tanıdığı biçimde uygulanır, öbür sorular bugünkü gibi kalır; hangi biçimleri tanıdığı son iletiye.
- [ ] **Tests first:** iki alandan SYNTHETIC sorular: karşılaştırma öbeği modelce `setting` denince kuralın
  bloğunda kalır; baş öbek `claim` denince görev bloğunda kalır; sınır uygulanınca satırda görünür; tanınmayan
  biçimdeki soru bugünkü sonucu verir. `test_vocabulary_labels.py` / `test_vocabulary_flow.py`'nin değişen
  beklentileri son iletiye.

## Task 4: Scopus aramadan çıkar; VPN'de son özet kaynağı; `detailed` 1.000

- `CONNECTORS["scopus"]`: `searchable=False` (D87'nin Crossref için yaptığı gibi). Sorgu derlenmez, planda arama
  kaynağı olarak sunulmaz; bağlayıcı kayıtlı kalır (legacy ve eski protokoller).
- Özet tamamlama sırası: Semantic Scholar → Crossref → **Scopus**, üçüncüsü yalnız o koşuda
  `scopus.complete_view_entitled` doğruysa (kurum ağı / VPN; D91) ve yalnız ilk ikisinin dolduramadığı kayıtlar için.
  Scopus'a DOI ile `view=COMPLETE` sorulur; istek sayısı `MAX_LOOKUP_REQUESTS` payından düşer; cevap D77'nin kayıt
  kalıbıyla (`record_lookups`, `abstract_origin="lookup_scopus"`) yazılır. Erişim yoksa adım `skipped` ve nedeni
  görünür; hiçbir istek gönderilmez.
- `SW_READ_LIMIT["detailed"] = 1_000` (D88'in sabiti; D90 değişikliği yazar). `quick` 400 ve `standard` 1.000
  değişmez.
- [ ] **Tests first:** Scopus'a sorgu derlenmez ve planda aranan kaynak değildir; VPN yok (erişim kontrolü `False`)
  → Scopus adımı `skipped`, istek yok; VPN var → yalnız ilk iki kaynağın dolduramadığı DOI'ler sorulur, özet
  `lookup_scopus` kaynağıyla yazılır; `detailed` okuma sınırı 1.000; legacy araştırma Scopus'u bugünkü gibi arar.

## Task 5: canlı kabul ölçümü ve kapanış

- Sözcük deneyinin betikleriyle (`.local/sw-vocabulary-experiment-2026-09-23/`, `common.py`, `arm_a.py`,
  `score.py`) yeni kuralın A kolu üç soruda yeniden koşulur, sonuç yeni bir klasöre
  (`.local/sw-slice13g-acceptance-2026-09-23/`): terimler, derlenen OpenAlex sorguları, sayım, ilk 1.000 / 2.000
  içindeki doğru eserler.
- **Kabul:** ilk ve ikinci turun birleşiminde (ilk 2.000'er kayıt) kuantumda **en az 19**, paket sorusunda **en az
  4** doğru eser (deneyin C kolunun sonucu); her iki soruda ikinci turun OpenAlex sayımı bugünkünden küçük; sepsis
  sorusunda iki turun ilk 25 başlığı yan yana. İlk 1.000'er kayıttaki sayılar da yazılır. Kabul tutmazsa **commit
  yok**: sayılar ve neden satır 13g'ye, son iletiye.
- D90 ve D91'i `docs/decisions.md`'ye yaz (en üste; Status / Date / Context / Decision / Limits). D90 Limits:
  kabul eşiklerinin görev sözcüklerini elemesi düzeltilmedi; "konu tek başına okunabilir büyüklükteyse onu da oku"
  kuralı yok (kuantumda bugünkü bozuk ikinci turun bulduğu 5 eser bu yüzden kaçıyor, aşağıda); üç soru, tek koşu,
  paket sorusunun doğru cevap listesi zayıf, sepsis etiketsiz. D91 Limits: Scopus'un aramaya katkısı yalnız
  18 Eylül'ün tek konusunda ölçüldü.
- Tam pytest; `git diff --check`; `skill_package_hash` aynı; satır 13g → `uygulandı, inceleme bekliyor`; tek commit;
  push.

## Bu dilimde yok

- **"Konu tek başına okunabilir büyüklükteyse onu da oku."** Kuantumda bugünkü bozuk ikinci tur fiilen yalnız konu
  bloğuyla aradı ve görev sözcüğünü özetinde taşımayan 6 doğru eser daha buldu (18 → 24); düzeltilmiş ikinci tur
  bunların 5'ini kaçırıyor. Bir sayım eşiğine bağlı bir kural tek konudan çıkıyor ve ölçülmedi; üçüncü ölçümden
  sonra karar verilir.
- Modelin kelime listesine aday eklemesi (kod sayar). Deneyin B kolu farklı bir düzenekti; bu düzenek ölçülmedi.
- Karşılaştırma cümlesinin öbeklerinin görev bloğundan çıkması (Task 3, gerekçesiyle).

## Bundan sonra (sıra)

1. **Üçüncü ölçüm (13ö'nün üçüncü koşusu):** 13f + 13g birlikte, aynı konu, `gpt-5.6-luna` · medium, üç efor,
   `.local/sw-measure-2026-09-22b/campaign.py` yeni bir klasörde. Süre (hedef 10 / 15 / 20 dk) ve kalite: kuantum
   konusunun 31 doğrulanmış eserinden kaçı dahil edildi, kaçı okundu, kaçı havuzdaydı.
2. **Kesme deneyi** ([sw-read-limit-cut-prompt.md](sw-read-limit-cut-prompt.md)): yalnız üçüncü ölçümde süre hâlâ
   hedefin üstündeyse, ölçümün yeni havuzlarıyla.

## Ölçülmedi

Duvar saati etkisi (üçüncü ölçüm ölçer); yeni kuralın bu üç soru dışındaki davranışı; İngilizce dışı sorular;
`detailed`'ın 1.000'e inmesinin modelin okuduğu ilk 300'e etkisi (deney yalnız OpenAlex sırasındaki doğru eserleri
saydı: kuantumda her turda 2.000 → 1.000 bir eser kaybettirdi); Scopus'un özet tamamlamada VPN'le kaç özet
doldurduğu.
