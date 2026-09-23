# SW dilim 13h — Arama sorgusunu model yazar, kodun sorgusu yanında aranır

**Tarih:** 23 Eylül 2026. **Durum:** dosya hazır. **Ana dosya:** [sw-status.md](sw-status.md). **Karar:** D92 (dilim
yazar). **Önkoşul:** 13g (uygulandı), iki model sorgusu ölçümü (`.local/sw-model-query-experiment-2026-09-23/`,
`.local/sw-model-query-experiment-2026-09-24/result.md`). **Tür:** Kur. **Uygulayan:** Opus · high. **İnceleme:** tam
(Fable); sorgu neyin bulunacağını belirler, kanıtın en başıdır. **Plan:** Opus, 23 Eylül 2026. Dilim 14 (kaynak
yönlendirme) ayrı iş olarak kalıyor.

**Goal:** Sahip 23 Eylül'de sorguyu modelin yazmasına karar verdi. İkinci ölçümün kuralı önceden sabitlendi ve sonuç şu
oldu: yalnız model üç çağrının birinde kuantum sorusunda 17 eser buldu (sınır 18). Model ile kod aynı okuma bütçesinde
üç çağrının üçünde de kuantumda 23 (sınır 20), pakette 4 buldu. Bu dilim ikinci düzeni kurar: model soru başına bir
kez sorguyu yazar, kod cevabı denetler ve sayar, ilk turda modelin sorgusuyla kodun 13g sorgusu birlikte aranır,
ikinci tur modelin sözcüklerinden kurulur. Onay kartı modelin sorgusunu gösterir; kodun sorgusu varsayılan olarak
açık bir seçenek olarak yanında durur.

## Ölçümün gösterdiği (dilimin dayanağı)

1. **İki sorgu birbirini tamamlıyor.** Modelin sorgusu kuantumda kodun bulmadığı 5 eseri getirdi, üç çağrıda da aynı
   beşi (g014, g044, g069, g081, g112). Kodun sorgusu da modelin kaçırdığı 6–9 eseri getirdi.
2. **Model paket sorusunda koddan iyi.** "channel" hiçbir çağrıda sorguya girmedi. İlk turda 500–600 kayıtta 4 eserin
   4'ü bulundu; kodun ilk turu 8.712 kayıtta 1 eser buldu.
3. **Yalnız modelin kaldığı çağrı tek bir terim yüzünden kaldı.** M1 görev bloğuna "mathematical optimization"
   koydu. Terim tek başına 9.926 kayıt, ayar bloğuyla birlikte 0 kayıt veriyor. Kural yalnız tek başına 0 kaydı
   yedekle değiştirdiği için terim kaldı ve boşa gitti.
4. **Revize prompt tuttu.** 9 çağrının 9'u kod denetiminden ilk seferde geçti (en çok 6 terim, iki blok dolu, tekrar
   yok). Görev bloğunda artık hep bir konu terimi var ("entanglement distribution", "packet size", "biomarker").
5. **`kind` tutarsız.** Aynı terim bir çağrıda `topic`, başka bir çağrıda `other` ya da `population` oldu. Tür yalnız
   gösterim içindir; hiçbir kural ona bakmaz.

## Global constraints

- **Konu sözcüğü ürün koduna ve yöntem paketine girmez.** Prompt `.local/sw-model-query-experiment-2026-09-24/
  prompt_p2.md`'nin genel örnekleriyle taşınır. Test fikstürleri SYNTHETIC olur ve en az iki alandan gelir.
- **Kodun yolu değişmez.** Sözcük çıkarma, SW17 etiketlemesi (üç çağrı), `build_vocabulary` ve 13g derleyicisi bugünkü
  gibi çalışır. Kodun sorgusu bugünkü sorguyla byte byte aynıdır. Değişen tek şey, kodun sorgusuna ikinci tur
  yapılmamasıdır (Task 3).
- **Sessiz geri dönüş yok.** Model çağrısı düşerse koşu yalnız kodun sorgusuyla kendiliğinden devam etmez (Task 1).
- **`legacy` iş akışı değişmez.** `compile_queries` ve legacy protokol gövdesi byte byte aynı kalır.
- **Donmuş protokol saygısı.** Sürdürülen koşu saklı sorgularını arar. Yeni düzen yalnız yeni kapsam revizyonlarında
  uygulanır. Yeni alanlar için protokol gövdesinin sürüm notu D92'ye yazılır.
- **`skill_package_hash` değişir.** Yeni yöntem dosyası buna yol açar. Eski ve yeni değer son iletiye ve D92'ye
  yazılır.
- 13f ve 13g'nin testleri geçmeye devam eder; değişen her beklenti son iletiye yazılır.
- Canlı kütüphane ve 8765 açılmaz. Testlerde ağ yoktur. Canlı çalışan tek şey Task 6'nın kabul ölçümüdür.

## Task 1: model adımı `search_query`

- Yöntem dosyası `methods/deixis-research/references/search-query.md`. İçeriği `prompt_p2.md`'nin developer bölümüdür,
  adımın zarf alanları (`step_input_id`, `scope_revision`, `skill_package_hash`, `schema_version` =
  `deixis.search_query.v1`) eklenir. `RUNTIME_FILES["search_query"] = ("SKILL.md", "references/search-query.md")`.
  Paketin bütünlük denetimi (bağlantılar, `provenance.json`) geçer.
- Sözleşme `contracts/research/search-query.schema.json`. Kaynağı `schema_p2.json`: `setting` / `task` (terim, `kind`
  ∈ topic | method | population | other, `why`), `setting_backup` / `task_backup`. `domain/contracts.py`'de
  `TASK_OUTPUTS`, `SCHEMA_VERSIONS` ve anlam denetimleri yer alır: seçilen terimler toplam en çok 6, iki blok da dolu,
  aynı terim iki kez yok (blok içinde ve bloklar arasında), terimde sorgu sözdizimi yok (tırnak, parantez, `AND` /
  `OR` / `NOT`), 1–4 sözcük. `tests/fixtures/research/{step-inputs,fake-outputs}.json` ve
  `tests/fakes.py::valid_response` güncellenir.
- StepInput yalnız soruyu, `language_hint`'i ve kullanıcının `key_terms`'ünü taşır. Kodun sözcük listesi modele
  verilmez; ölçülen düzen budur.
- Kapsam revizyonu başına **bir çağrı** yapılır (`operation_key` `search_query`), oylama yoktur. Gönderilen her şey
  çağrıdan önce saklanır (`_model_step`). Anlam denetimi düşerse **en çok bir onarım** yapılır, ikincisi yoktur.
  `succeeded` bir adım saklı çıktısını döner; sürdürülen koşu modeli yeniden çağırmaz.
- Çağrı ya da onarım düşerse: `protocol_approval == "ask"` iken kart açılır, hatayı gösterir ve iki yol sunar: "yeniden
  dene" (yeni çağrı, ayrı `operation_key`, bir kez) ya da "yalnız kodun sorgusuyla ara". `as_proposed` iken koşu
  `search_query_failed` ile duraklar. Kullanıcının seçimi onay kaydına yazılır.
- Kullanıcı `key_terms` verdiyse bu terimler iki bloğa bugünkü gibi girer, model çağrılmaz (SW2.6'nın sırası). Adım
  `skipped: user_key_terms` yazar.
- [ ] **Tests first:** geçerli cevap adımda saklanır; 7 terim, boş blok, iki kez geçen terim ve sözdizimli terim birer
  anlam hatasıdır; tek onarım sonrası düzelen cevap kullanılır; ikinci kez bozuk cevap düşmüş sayılır; düşen çağrıda
  `ask` kartı açar, `as_proposed` duraklar ve kodun sorgusu kendiliğinden aranmaz; sürdürülen koşuda ikinci çağrı
  yoktur; `key_terms` varken çağrı yoktur; araç öğesi ve başka model cevabı bugünkü gibi reddedilir.

## Task 2: kod denetimi ve sayımlar

- Seçilen her terim iki kez sayılır: tek başına ve öbür bloğun seçilmiş terimleriyle birlikte (`_count_probe`,
  OpenAlex). En çok 24 sayım isteği yapılır (6 seçilmiş + 6 yedek, ikişer).
- **Tek başına 0 kayıt** veren terimin yerine aynı bloğun sıradaki yedeği girer. Yedek de aynı iki sayımdan geçer.
  Yedek kalmadıysa terim düşer; blok boşalırsa Task 1'in düşme yolu işler.
- **Öbür blokla 0 kayıt** yalnız uyarıdır (`no_records_with_other_block`), terim yerinde kalır. Otomatik değişim
  ölçülmedi; ilk ölçümün kuralı bunu yapıyordu, ikincisinin kuralı yapmıyordu.
- 1 milyon kuralı (`VERY_LARGE_COUNT` ile ayar terimi elemek) bu adımda **uygulanmaz**; büyük sayım yalnız kartta
  görünür.
- Adımın çıktısı modelin ham cevabını, türleri, her sayımı, her değişimi (hangi terim, hangi yedek, neden), uyarıları ve
  son terim listesini taşır. Son liste `compile_block_queries`'in okuduğu sözcük biçimindedir (`origin: "model"`).
- Sayılamayan bir terim (sayım `None`) uyarıyla yerinde kalır ve reddedilmez. Modelin terimini kod elemez; genişleme
  adaylarında ise durum farklıdır (D90'daki gerekçe).
- [ ] **Tests first:** tek başına 0 → yedek girer ve kaydı yazılır; yedek de 0 → sıradakine geçilir; yedek kalmazsa
  terim düşer; boşalan blok düşme yolunu açar; öbür blokla 0 → uyarı, terim kalır; 1 milyonluk ayar terimi kalır;
  sayılamayan terim kalır ve uyarı yazılır; sayım sayısı 24'ü geçmez; sürdürülen koşu sayımları yeniden istemez.

## Task 3: iki sorgu birlikte, ikinci tur modelden

- İlk tur: modelin sözcükleri ve kodun sözcükleri ayrı ayrı `compile_block_queries` ile derlenir. Her sorgu
  sözlüğüne `origin: "model" | "code"` yazılır. `max_provider_requests` sınırında önce modelin sorguları, sonra kodun
  sorguları yer alır. Sınıra sığmayan sağlayıcı / kaynak çifti adım çıktısında adıyla kaydedilir.
- Her sorgu eforun `SW_READ_LIMIT`'iyle okunur (`detailed` 1.000; ölçülen MK düzeni budur). D89'un sorgu payı sorgu
  başına bugünküyle aynı kalır. Toplam istek ödeneği sorgu sayısıyla büyür; eski toplam iki sorguya bölünmez. Artan
  istek sayısı ve süre Task 6'da ölçülür.
- İkinci tur (`expand`, `second_round_vocabulary`) modelin sözcüklerinden kurulur. Adaylar yalnız **modelin
  sorgusunun** ilk tur kayıtlarından çıkar (ölçülen düzen). Kodun sorgusuna ikinci tur yapılmaz.
- Kullanıcı kartta kodun sorgusunu kapattıysa yalnız modelin sorguları aranır. Model düşmüş ve kullanıcı "yalnız kod"
  dediyse yalnız kodun sorguları aranır; ikinci tur bu durumda bugünkü gibi kodun sözcüklerinden kurulur (13g).
- Kayıt birleştirme, yazım sırası ve D89'un sorgu dizini sırası değişmez: modelin sorguları önce gelir.
- Arama satırı ya da görünüm hangi sorgunun hangi kaydı getirdiğini `origin` ile okuyabilmeli. Bunun için yeni bir
  sütun gerekirse yeni numaralı bir migration eklenir.
- [ ] **Tests first:** iki sözlük iki sorgu takımı verir ve `origin`'leri doğrudur; sınıra sığmayan kodun sorgusu
  kaydedilir; her sorgu kendi okuma sınırını ve payını alır; ikinci tur adayları yalnız modelin sorgusunun
  kayıtlarından gelir ve kodun sorgusu ikinci tura girmez; kod kapalıyken ve "yalnız kod" seçiliyken doğru takım
  aranır; 13f'nin sıra eşitliği fikstürleri (`tests/fixtures/search_parallelism/`) tek sözlükle byte byte aynıdır.

## Task 4: onay kartı

- `apps/web/src/ProtocolApproval.tsx` modelin sorgusunu ana liste olarak gösterir: blok, terim, `kind`, `why`, tek
  başına ve öbür blokla sayım, yedekler, yapılan değişim, uyarılar. Derlenen OpenAlex sorgusu metin olarak görünür.
- Kartın bugünkü terim düzeltmeleri (sil, ekle, taşı) **modelin sözcüklerine** uygulanır. Eklenen terim bugünkü gibi
  sayılır (slice 08c).
- Kodun sorgusu altta ayrı bir bölümdür: terimleri ve derlenmiş sorgusu salt okunur görünür, bir anahtar varsayılan
  olarak açıktır ("Kodun sorgusunu da ara"). Kodun terimleri kartta düzeltilmez.
- Model düştüyse kart hatayı ve Task 1'in iki yolunu gösterir.
- Metinler `i18n.ts` / `labels.ts` üzerinden iki dilde yazılır. `.impeccable.md` okunur.
- Onayın farkı (`DiffList`) modelin sözcüklerindeki düzeltmeleri ve kodun sorgusunun açık / kapalı durumunu yazar.
- [ ] **Tests first:** API görünümünün testi (`test_protocol_approval.py` / `test_approval_flow.py`): kart verisi
  modelin terimlerini, türleri, sayımları, uyarıları ve kodun sorgusunu taşır; düzeltme modelin sözcüklerine
  uygulanır; anahtar kapalı onay kodun sorgusunu aramaz. Playwright süitine (`apps/web/e2e`) bir durum eklenir:
  `fixture_server.py`'nin betikli modeli yeni adımı cevaplar, kart iki bölümü gösterir, anahtar kapatılıp onaylanır.
  `npm run build`, `npm run lint` ve A–G durumları geçer.

## Task 5: protokol gövdesi

- `build_protocol` sw gövdesine şu alanları ekler: `search_query`. Bu alanda şunlar yer alır: yöntem dosyasının yolu ve
  `skill_package_hash` (prompt sürümü), `schema_version`, model (bağlantı / model / efor), modelin ham cevabı, sayımlar,
  değişimler, uyarılar ve son terimler. Ayrıca `code_query_searched` (true / false / neden) ve gerçekten aranan
  sorgular `origin`'leriyle yazılır. Model düşüp "yalnız kod" seçildiyse `search_query` düşüşü ve kullanıcının seçimini
  yazar.
- `PROTOCOL_SCHEMA` `v1` kalır. Yeni alanlar eski gövdelerde yoktur ve yoklukları "bu alan o sürümde yoktu" demektir.
  Sürüm notu D92'ye yazılır. `legacy` gövdesi byte byte aynı kalır.
- [ ] **Tests first:** `test_protocol_record.py`: sw gövdesi yeni alanları taşır; aynı durum aynı özeti verir;
  `legacy` gövdesi değişmez; model düşüp "yalnız kod" seçilince gövde bunu söyler; donmuş eski gövdeyle sürdürülen koşu
  saklı sorgularını arar.

## Task 6: canlı kabul ölçümü ve kapanış

- Ürünün koduyla, 8765 açılmadan, 13g kabulünün düzeni (`accept.py` gibi, ayrı veri dizini ve `Settings`) yeni bir
  klasöre kurulur (`.local/sw-slice13h-acceptance-<tarih>/`). Deneyin üç sorusu ve doğru cevap listeleri
  (`sw-vocabulary-experiment-2026-09-23/common.py`) kullanılır. Model `gpt-5.6-luna` · medium, efor `detailed`. Her
  soru **üç ayrı kapsam revizyonunda** koşulur (ürün tek çağrı yapar; üç revizyon bir çağrının ne kadar
  kaçırabileceğini gösterir). Onay `as_proposed`, kod sorgusu açık.
- **Kabul:** her revizyonda ilk ve ikinci turun birleşiminde, her sorgunun ilk 1.000 kaydında, kuantumda **en az 20**,
  paket sorusunda **en az 4** doğru eser. Sepsiste her revizyonun iki turunun ilk 25 başlığı yazılır. Keşfin OpenAlex
  istek sayısı ve duvar saati 13g kabulüyle yan yana yazılır. Bir koşul tutmazsa **commit yok**: sayılar ve neden
  satır 13h'ye ve son iletiye yazılır.
- D92'yi `docs/decisions.md`'nin en üstüne yaz (Status / Date / Context / Decision / Limits). Limits: tek model, üç
  soru; paket sorusunun cevap listesi zayıf; sepsis etiketsiz; yalnız OpenAlex sırası sayıldı (modelin sonra okuyup
  dahil ettiği değil); öbür sağlayıcılarda model sorgusunun davranışı ölçülmedi; `quick` / `standard`'da iki sorgu
  ölçülmedi; "öbür blokla 0" için otomatik yedek ölçülmedi; `kind` tutarsız; ikinci tur adaylarının iki sorgunun
  kayıtlarından çıkarıldığı düzen koşulmadı.
- Tam pytest; `git diff --check`; `skill_package_hash` eski → yeni son iletiye; satır 13h → `uygulandı, inceleme
  bekliyor`; tek commit; push.

## Bu dilimde yok

- **Yalnız model varsayılanı.** Kural geçmedi (kuantum 17 < 18). Kullanıcı kartta kodun sorgusunu kapatarak bunu
  seçebilir; varsayılan değildir.
- **"Öbür blokla 0" için otomatik yedek.** Yalnız uyarıdır; bir sonraki ölçüm karar verir.
- **SW17 etiketlemesinin kaldırılması.** Kodun sorgusu olduğu gibi kalır; üç etiket çağrısı sürer.
- **Kodun sorgusuna ikinci tur.** Ölçülen düzende yoktu.
- **Modelin kodun listesini görmesi** ya da kodun modelin listesini düzeltmesi.

## Bundan sonra (sıra)

1. **Üçüncü ölçüm (13ö'nün üçüncü koşusu):** 13f + 13g + 13h birlikte, aynı konu, `gpt-5.6-luna` · medium, üç efor.
   Süre (hedef 10 / 15 / 20 dk) ve kalite: kuantum konusunun 31 doğrulanmış eserinden kaçı dahil edildi, kaçı
   okundu, kaçı havuzdaydı.
2. **Kesme deneyi** ([sw-read-limit-cut-prompt.md](sw-read-limit-cut-prompt.md)): yalnız süre hâlâ hedefin
   üstündeyse.

## Ölçülmedi

İki sorgunun duvar saatine etkisi (Task 6 ve üçüncü ölçüm ölçer); OpenAlex dışındaki sağlayıcılarda modelin sorgusu;
Luna dışındaki modeller; İngilizce dışı sorular; bu üç soru dışındaki alanlar; kullanıcının kartta modelin terimlerini
nasıl düzelttiği.
