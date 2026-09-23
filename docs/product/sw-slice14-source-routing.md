# SW dilim 14 — Kaynak yönlendirme ve Semantic Scholar bulk araması

**Tarih:** 23 Eylül 2026. **Durum:** plan; aşağıdaki beş karar sahip tarafından onaylandı (23 Eylül 2026). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** D93 (dilim yazar). **Önkoşul:** 04, 13f–13h (kapandı, `46e54ac`).
**Tür:** Kur (ölçülmedi). **Uygulayan:** Opus · medium. **İnceleme:** tam (Sol high) öneriyorum; satırda `toplu`
yazıyor, ama dilim sorguların nereye gideceğini değiştiriyor ve migration getiriyor. **Plan:** Opus, 23 Eylül 2026.
**Kaynak:** [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md) SW3.1–4 ve 3.7.

**Goal:** Bugün bir sw araması, kapsamda anahtarı olan her sağlayıcıya aynı sorguyu gönderiyor: OpenAlex, Semantic
Scholar, arXiv, bioRxiv, PubMed, IEEE Xplore, CORE, SerpApi. Sırayı ilk turun sorgu sınırı (`quick` 3, `standard` 8,
`detailed` 12 sorgu) kesiyor. SW3'e göre OpenAlex her zaman aranır. Alan kaynağını (IEEE, PubMed, arXiv) kod, sorunun
alan dağılımına bakarak seçer. Semantic Scholar yedek olarak aranır, bundan sonra bulk uç noktasıyla (sahip kararı,
`fdd2274`). Her kaynak iki sayı bildirir: kaç kayıt getirdi ve bunların kaçını yalnız o getirdi. Bu dilim bu dördünü
kurar.

## Elimizdeki sayılar

1. **Hangi kaynak ne getirdi** (üçüncü D88 ölçümü, `.local/sw-measure-2026-09-24/`; ham sayfalardan `bysource.py`
   ile okundu). 31 doğrulanmış kuantum eserinden havuzda 19 / 25 / 30 vardı. Yalnız bir kaynağın bulduğu eserler:
   - `quick`: OpenAlex 12, S2 1.
   - `standard`: OpenAlex 5, IEEE 2 (g096, g052).
   - `detailed`: OpenAlex 3, S2 2 (g126, g030), IEEE 1 (g096).

   PubMed, CORE ve SerpApi doğrulanmış eser getirdi (en çok 8, 3 ve 5), ama hiçbiri yalnız kendisinin bulduğu bir
   eser getirmedi. arXiv üç eforda da sıfır kayıt döndü (406 sorunu, TODO'da).
2. **S2 bulk denemesi** (`.local/sw-s2-bulk-probe-2026-09-23/`). İlk turun sorguları efor başına 2–3 istekte ve
   4–6 sn'de 20 / 21 / 20 doğrulanmış eser getirdi. Bugünkü S2 araması 6 / 8 / 19 getiriyor ve `detailed`'da 8,7
   dakika sürüyor. `quick`'te bulk, OpenAlex'in 400 kayıtlık okumasının kaçırdığı 4 eseri havuza ekledi.
3. **Alan dağılımı denemesi** (`.local/sw-slice14-fields-probe-2026-09-23/`). Modelin kapı sorgusu için soru başına
   bir OpenAlex isteği gönderildi (`group_by=primary_topic.field.id`):

   | soru | kayıt | alanlar (payı en büyük olanlar) |
   |---|---:|---|
   | kuantum | 1.113 | Bilgisayar Bilimi %79, Fizik ve Astronomi %9, Mühendislik %7 |
   | paket (kablosuz sensör) | 584 | Bilgisayar Bilimi %82, Mühendislik %16 |
   | yenidoğan sepsisi | 1.807 | Tıp %89, Biyokimya ve Genetik %3, İmmünoloji %2 |

   Üç sorunun hiçbiri aşağıdaki eşiğe yakın değil. Seçilen kaynakların payı en az %86, dışarıda kalanların payı en
   çok %9. Eşik %10 ile %80 arasında nereye konsa bu üç soruda sonuç değişmez. Eşiği sınayan bir soru olmadığı için
   eşik ölçülmüş sayılmaz.

## Sahibin onayladığı kararlar (23 Eylül 2026)

1. **Yönlendirme onaydan önce yapılır.** SW3.2 "ilk OpenAlex turunun alan dağılımı" diyor. Önerim şu: ilk turu
   beklemek yerine, onay kartından önce modelin kapı sorgusu için tek bir `group_by` isteği gönderilsin. Üç
   gerekçem var:
   - Protokol ilk aramadan önce donduruluyor (SW14). Tur sonrası yönlendirme koşunun ortasında yeni bir protokol
     revizyonu açardı.
   - `group_by` isteği yalnız ilk sayfanın değil, bütün sonuç kümesinin dağılımını veriyor.
   - Kullanıcı hangi kaynağın neden seçildiğini onay kartında görür.

   Maliyeti tek bir istektir; sayım probları da zaten bu aşamada gönderiliyor.
2. **CORE ve SerpApi sw aramasından çıkar, bioRxiv PubMed'le birlikte yönlenir.** SW3 bu üçünün adını anmıyor.
   Ölçümde CORE ve SerpApi yalnız kendisinin bulduğu bir eser getirmedi; SerpApi ücretli. bioRxiv zaten OpenAlex
   üzerinden aranıyor ve kuantumda sıfır kayıt getirdi; yaşam bilimi sorusunda PubMed'in yanında anlamlı. İkisi de
   Scopus gibi yalnız sw aramasından çıkar (`sw_searchable=False`); `legacy` onları bugünkü gibi arar.
3. **Sorgu sınırı altında sıra: OpenAlex → S2 → alan kaynağı.** SW3.4, S2'yi yedek olarak sayıyor. Buna karşın
   ölçüm şunu gösteriyor: `quick`'in sınırı üç sorguya yetiyor ve bulk bu eforda OpenAlex'in kaçırdığı 4 eseri
   getirdi. IEEE'nin yalnız kendisinin bulduğu eserler yalnız `standard` ve `detailed`'da çıktı, orada sınır her
   kaynağa yer bırakıyor (`standard` 2 + 2 + 2 + 2 = 8). Bu sırayla `quick` alan kaynağını hiç aramaz; bu da D93'e
   yazılır.
4. **`legacy`'nin S2 araması değişmez.** `/paper/search` yolu, `legacy` sorgusu ve protokol gövdesi byte byte aynı
   kalır.
5. **Dağılım okunamazsa kapsamdaki her alan kaynağı aranır.** Yönlendirme `unavailable` olarak kaydedilir ve kartta
   gösterilir. Kaynak eksik kalırsa kaçan eser kaybı, fazladan gönderilen istekten daha pahalıdır. Bu adım gizli bir
   geri dönüş değil, kayıtlı bir varsayılandır.

## Global constraints

- **Konu sözcüğü ürün koduna girmez.** Alan-kaynak tablosu OpenAlex'in alan adlarını kullanır (Computer Science,
  Medicine …), soruların sözcüklerini kullanmaz. Test fikstürleri SYNTHETIC olur ve en az iki alandan gelir.
- **`legacy` değişmez** (karar 4). `compile_queries` ve `legacy` protokol gövdesi byte byte aynı kalır.
- **Donmuş protokole saygı.** Sürdürülen koşu saklı sorgularını, sorgunun adını verdiği uç noktayla arar. Uç nokta
  adı taşımayan eski bir S2 sorgusu `/paper/search`'e gider. Yeni düzen yalnız yeni kapsam revizyonlarında uygulanır.
- **Model yok.** Bu dilim hiçbir model çağrısı eklemez. Yöntem paketi ve `skill_package_hash` değişmez.
- **S2 hızı D67'ye bağlı.** Bulk da aynı süreç geneli kapıdan geçer (istekler arasında en az 2 sn) ve 429 yeniden
  denemesi sınırlı kalır.
- Canlı kütüphane ve 8765 açılmaz, testlerde ağ yoktur. Canlı çalışan yalnız Task 1'in sıralama karşılaştırması ve
  Task 6'nın kabulüdür.

## Task 1: bulk kesim sırası (ürün kodu yok)

- Bulk ilgiye göre sıralamaz. Sıra ölçütü yalnız `paperId` (varsayılan), `publicationDate` ya da `citationCount`
  olabilir. `quick` sorgu başına 400, öbür eforlar 1.000 kayıt okur. Bu yüzden sonuç sayısı okuma sınırını aşınca
  hangi kayıtların kaldığını sıra belirler.
- Üçüncü ölçümün altı ilk tur sorgusunu (üç efor × model/kod, OpenAlex metni bulk sözdizimine çevrilmiş) üç sırayla
  gönder: `paperId`, `citationCount:desc`, `publicationDate:desc`. Her birinde 31 doğrulanmış eserden kaçının ilk
  400 ve ilk 1.000 kayıtta olduğunu say. Toplam en çok 18 istek, D67 aralığıyla. Klasör:
  `.local/sw-slice14-bulk-sort-<tarih>/`.
- **Önceden sabitlenen kural:** altı sorgunun toplamında ilk 400 kayıtta en çok doğrulanmış eseri tutan sıra seçilir.
  Eşitlikte varsayılan sıra (`paperId`) kalır. Sonuç D93'e yazılır. Tek konudur; D93'ün Limits bölümü bunu söyler.

## Task 2: S2 bulk bağlayıcısı ve sorgu biçimi

- `semantic_scholar.py`'ye `/graph/v1/paper/search/bulk` eklenir: `query`, `fields` (bugünkü `FIELDS`; alanların
  hepsi bulk'ta var), Task 1'in `sort` değeri, `token` ile sayfa. `Connector`'da sw okuması `sw_options` ile bulk'a
  gider, `paging="cursor"` olur. `legacy` çağrısı bugünkü `search`'ü aynen kullanır.
- Derleyici S2'yi sw'de düz sözcük sağlayıcısı olmaktan çıkarır (`PLAIN_PROVIDERS`). Blok sorgusu bulk sözdizimiyle
  yazılır: `("a" | "b") + ("c" | "d")`. Öbekler tırnak içinde gider, sözcük sınırı kalkar. Bu, 13g
  düzeltmesindeki "her bloktan en az bir sözcük" kuralını S2 için gereksiz kılar; kural Crossref için kalır.
- Derlenen her S2 sorgusu `endpoint: "bulk"` ve `sort` taşır; protokol bunları yazar. Okuyucu uç noktayı sorgudan
  alır (donmuş protokol kuralı). İkinci tur da aynı biçimle derlenir.
- Okuma sınırı `SW_READ_LIMIT`'tir (400 / 1.000 / 1.000). Bulk tek istekte 1.000'e kadar kayıt verir; `quick`
  bunun ilk 400'ünü alır. Sonraki isteğe ancak sınır 1.000'i aşarsa gerek olur, bugün hiçbir efor aşmıyor.
- Testler: sözdizimi (öbek, VEYA, VE, tek terimli blok), `token` sayfalaması, eski düz sorgunun `/paper/search`'e
  gitmesi, `legacy` isteğinin byte byte aynı kalması, D67 kapısı.

## Task 3: yönlendirme adımı

- Yeni kod adımı `source_routing`, `search_query`'den sonra ve onaydan önce çalışır. Modelin kapı sorgusu için
  (model yoksa ya da "yalnız kod" seçildiyse kodun kapı sorgusu için) bir OpenAlex isteği gönderir:
  `group_by=primary_topic.field.id`. Toplamı ve alan paylarını adımda saklar. Sürdürülen koşu isteği yeniden
  göndermez.
- Kural tablosu `domain/rules.py`'de `SOURCE_ROUTES` adıyla durur (elle seçildi, ölçülmedi):
  - IEEE Xplore ← Computer Science + Engineering.
  - arXiv ← Physics and Astronomy + Mathematics + Computer Science.
  - PubMed ve bioRxiv ← Medicine, Nursing, Health Professions, Dentistry, Veterinary, Neuroscience, Immunology and
    Microbiology, Biochemistry Genetics and Molecular Biology, Pharmacology Toxicology and Pharmaceutics,
    Agricultural and Biological Sciences.

  Bir kaynak, alanlarının toplam payı `ROUTE_SHARE = 0.25` veya üstündeyse seçilir. OpenAlex ve S2 her zaman
  aranır.
- Kaynak ancak araştırmanın kapsamında ve yapılandırılmışsa seçilebilir. Kullanıcının kapsamdan çıkardığı bir
  kaynak seçilmez. Kart kaynak listesini düzenletmez; kaynak çıkarmanın yeri kapsamdır.
- Kullanıcı kartta terimleri düzeltir ve kapı sorgusu değişirse yönlendirme yeni sorguyla bir kez daha okunur.
  Aynı sorgu için istek tekrar gönderilmez.
- Derleyici kapsamın listesini değil, yönlendirilmiş listeyi alır. Sıra karar 3'teki gibidir: OpenAlex (model,
  kod), S2 (model, kod), sonra seçilen alan kaynakları.
- Testler: üç SYNTHETIC dağılım (mühendislik, tıp, eşiğe yakın bir karışım); kapsam dışı kaynak; okunamayan dağılım
  (karar 5); düzeltmeden sonra yeniden okuma; sürdürülen koşunun istek göndermemesi; `quick` sınırında alan
  kaynağının düşmesi.

## Task 4: kaynak başına iki sayı ve kayıt başına bütün isabetler

- Migration `0049_candidate_hits.sql`: `candidate_hits(research_id, scope_revision, source_version_id,
  search_run_id)`, birincil anahtar `(source_version_id, search_run_id)`. Her sayfa yazılırken aday satırıyla aynı
  işlemde doldurulur. Bugün aday satırı yalnız ilk bulan aramayı tutuyor; bu tablo bir kaydı bulan her aramayı tutar.
- Bu tablo 13h incelemesinin ertelenen bulgusunu (3) kapatır. İkinci turun aday listesi, kayıt modelin
  sorgularından herhangi birinde çıktıysa o kaydı alır. Kaydı yalnız bütün isabetleri ikinci turdansa dışarıda
  bırakır.
- Koşu görünümü her kaynak için tur başına iki sayı verir: getirdiği iş sayısı ve yalnız onun getirdiği iş sayısı
  (DOI ve iş birleşmesinden sonra, o koşu içinde). Zaman çizelgesindeki "şurada arandı" satırı bunları gösterir.
  Protokol gövdesi arama bitmeden dondurulduğu için bu sayılar oraya girmez.
- Eski araştırmalar için tablo geriye dönük doldurulmaz. Görünüm onlar için "sayılmadı" der, 0 demez.
- SW3.7'nin "birkaç araştırmada kendi eserini getirmeyen kaynak o alanda kapanır" kuralı kurulmaz. Alan başına
  doğrulanmış eser listesi yok; sayılar yalnız biriktirilir.

## Task 5: onay kartı ve protokol

- Kartın sorgular bölümü seçilen kaynakları payıyla gösterir. Örnek: "IEEE Xplore: Computer Science + Engineering,
  1.113 kaydın %86'sı". Dışarıda kalanlar gerekçesiyle listelenir ("pay %0", "kapsamda değil", "sw aramasında yok").
  Dağılım okunamadıysa kart bunu söyler. Önce `.impeccable.md` okunur. Türkçe dizgeler `i18n.ts`'ye eklenir.
  Playwright H durumuna yönlendirme satırı eklenir.
- Protokol gövdesine `source_routing` girer: probun sorgusu, toplam, alan payları, `ROUTE_SHARE`, tablo sürümü,
  seçilen ve dışarıda kalan kaynaklar ve gerekçeleri. Bunun yanında S2 sorgularının `endpoint` ve `sort` alanları
  yer alır. Gövdenin sürüm notu D93'e yazılır; `legacy` gövdesi değişmez.

## Task 6: canlı kabul ve kapanış

- Ürünün koduyla, 8765 açılmadan, 13h kabulünün düzeninde bir klasör kurulur:
  `.local/sw-slice14-acceptance-<tarih>/`. Model `gpt-5.6-luna` · medium. Onay `as_proposed`. Koşu keşif bitince
  durur; getirme ve yanıt yoktur.
- **Kabul:**
  - Kuantum sorusu üç eforda koşulur. Havuzdaki doğrulanmış eser sayısı üçüncü ölçümün 19 / 25 / 30'unun altına
    düşmez. S2'nin kendi kayıtları `detailed`'da 31 eserin en az 18'ini tutar (bulk denemesi 20).
  - Paket sorusu `detailed`'da koşulur. Bulunabilir 4 eserin 4'ü havuzdadır.
  - Yönlendirme şöyle çıkar: kuantum ve paket → IEEE + arXiv; sepsis → PubMed + bioRxiv. Sepsis yalnız
    yönlendirme adımına kadar koşulur.
  - S2 istek sayısı efor başına en çok 6'dır.

  Koşullardan biri tutmazsa commit yapılmaz; sayılar ve neden satır 14'e ve son iletiye yazılır.
- Keşif süresi ve sağlayıcı başına istek sayısı üçüncü ölçümle yan yana yazılır. Bunlar kabul koşulu değildir;
  süre hedefini 13ö ölçer.
- D93, `docs/decisions.md`'nin en üstüne yazılır (Status / Date / Context / Decision / Limits). Limits:
  - Eşik ve tablo elle seçildi; üç soru eşiği sınamıyor.
  - Dağılım yalnız `primary_topic`'ten okunuyor.
  - Bulk sırası tek konuda seçildi.
  - `quick` alan kaynağını aramıyor.
  - CORE ve SerpApi tek konudaki ölçüme dayanılarak çıkarıldı.
  - SW3.7'nin kapatma kuralı kurulmadı.
  - arXiv hâlâ sıfır kayıt dönüyor.
- Tam pytest, web build ve lint, Playwright; `git diff --check`; satır 14 → `uygulandı, inceleme bekliyor`; tek
  commit; push.

## Bu dilimde yok

- **Atıf zinciri** ve S2'nin ikinci atıf grafiği olarak kullanımı (SW3.4'ün ikinci yarısı, SW3.6): dilim 15.
- **Tam metin sırası:** dilim 14a.
- **Europe PMC:** 21 Eylül'deki plan kararı onu dilim 14'e ertelemişti. Ama Europe PMC bir tam metin kaynağı ve
  SW3 onu anmıyor. Önerim onu 14a'dan sonraya, tam metin işlerinin yanına almak; bu da sahibin kararı.
- arXiv'in 406'sı ve Scopus DOI grupları: TODO.md'de duruyorlar.

## Ölçülmedi

- Yönlendirme eşiğinin sınır durumları.
- Mühendislik ve tıp dışındaki alanlar ve İngilizce dışı sorular.
- Bulk sırasının başka konulardaki etkisi.
- Yalnız bir kaynağın getirdiği kayıtların ilgililiği; iki sayı bunu ölçmez, yalnız sayar.
- Kaynak azalınca özet aşamasının ve okumanın süresi (13ö ölçer).
