# SW dilim 17a — Tam metin getirme keşifle üst üste

**Tarih:** 24 Eylül 2026. **Durum:** uygulandı (D98, kabul `.local/sw-slice17a-acceptance-2026-09-24/result.md`); plan hazır; Sol · medium'un ikinci görüşü, onay turu ve üç sözleşme denetimi işlendi, son denetimde "uygulamaya hazır, bulgu yok" (`sol-contract4.md`); prompt: [sw-slice17a-prompt.md](sw-slice17a-prompt.md). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** yeni D numarası (dilim yazar). **Önkoşul:** 15 (kapandı, D95), 17 (son
denetim yapılmadı, `80caa75`). **Tür:** Kur. **Plan:** Opus 5.5 · high, 24 Eylül 2026. **Ölçüm:**
`.local/sw-slice17a-plan-2026-09-24/` (`overlap.py`, `overlap.json`, `safe_set.py`, `safe_set.json`). **İkinci görüş:**
`gpt-5.6-sol` · medium, salt okunur (`sol-medium.md`): karar 1, 3, 5, 6'yı değişiklikle kabul etti, 2 ve 4'e itiraz etti;
dokuz bulgusunun hepsi aşağıya işlendi ("Ortak kararlar"). Onay turunda (`sol-approval.md`) Sol karar 1, 3, 4, 5, 6,
8'i onayladı; 2 ve 7'yi değişiklikle onayladı ve tek eksik olarak iki kararı birleştiren kalıcı sözleşmeyi istedi. O
sözleşme "Kalıcı koordinasyon sözleşmesi" bölümünde.

**Goal:** Bir `sw` araştırmasında tam metin getirme bugün keşif koşusunun tamamı bittikten sonra ayrı bir koşuda
başlıyor (D83'ün adıyla yazılmış sapması). SW10.1 getirmenin özet taramasının kod aşamasından hemen sonra, arka planda
başlamasını istiyordu. Bu dilim o sözü yerine getirir: özet taramasının kod adımı biter bitmez, getirileceği kesinleşen
işlerin PDF'i çekilmeye başlar; model hâlâ öteki işlerin özetlerini okurken. Getirilen iş kümesi, sınırlar, kodlar ve
okuma koşusu bugünküyle aynı kalır. Değişen yalnız getirmenin ne zaman başladığıdır.

## Elimizdeki sayılar

Ölçüm saklı 13 kütüphanede yapıldı: dilim 15 kabulünün 11 kütüphanesi (9'u kuantum sorusu `q1`, 4'ü ikinci soru `q2`) ve
dilim 16'nın iki canlı koşusu (`q1`). Salt okunur, ağsız, modelsiz. İki betik var:

- `overlap.py` getirme koşusunun kendi adımlarını yeniden oynatıyor: aynı işler, aynı iş başı süreler, aynı anda 4 iş
  (`FULLTEXT_FETCH_PARALLEL`). Tek fark bir işin ne zaman başlayabildiği. Oynatma gerçek getirme süresini yuvarlanmış
  değerlerde en çok 0,02 dk farkla veriyor.
- `safe_set.py` kütüphaneyi belleğe kopyalayıp getirme planının dondurulduğu âna geri alıyor (sonraki özet ve tam metin
  kararları, sonra getirilen PDF'ler ve sonra değişen seçimler çıkarılıyor). O anki durumdan `fulltext.fetch_plan`
  saklı planı **13 kütüphanenin 13'ünde birebir** yeniden veriyor. Sonra her an için karar 2'nin "güvenli küme" kuralını
  uyguluyor ve getirmeyi o kuralla oynatıyor.

1. **Kod adımından keşfin sonuna kadar geçen süre, yani kazancın üst sınırı:** `quick` 1,5–2,1 dk, `standard`
   2,2–4,8 dk, `detailed` 4,3–4,4 dk. Bu aralığı özet taramasının iki model koşusu dolduruyor. Zincirleme bu sürenin
   içinde koşuyor (0,2–0,7 dk); 13 kütüphanenin hepsinde zincir istekleri son model partisinden önce bitiyor.
2. **Kod adımında güvenli olan işler:** `quick`'te getirilen 92–100 işin 43–64'ü (%47–70), `standard`'da 112–125'in
   68–79'u, `detailed`'da 312–325'in 157–197'si. Bunların hepsi kodun `blocks_in_title` ile aday bıraktığı ve modelin
   okuma planına girmeyen işler; hiçbirinin son kararı bir model adımından gelmiyor.
3. **Kazanç** (dakika; getirmenin bugünküne göre ne kadar erken bittiği):

   | Efor | Kütüphane | Bugünkü getirme | "Sıralı" kural | "Güvenli küme" (karar 2) | "Kendi kararı" |
   |---|---|---|---|---|---|
   | `quick` | 8 | 2,4–6,3 | 0,9–1,4 | 1,5–2,1 | 1,5–2,1 |
   | `standard` | 3 | 3,7–6,7 | 2,1–4,8 | 2,2–4,8 | 2,2–4,8 |
   | `detailed` | 2 | 13,7 | 4,1–4,3 | 4,3–4,4 | 4,3–4,4 |

   "Sıralı": bir iş, kendisi ve plan sırasında önündeki bütün işler kesinleşince başlar. "Güvenli küme": iş kesinleşmiş
   ve bekleyen her işin aday çıktığı en kötü planın sınırı içindeyse başlar. "Kendi kararı": işin kendi kararı
   yazılınca başlar; sınırı gözetmez. Güvenli küme 13 kütüphanenin hepsinde kazancın üst sınırına varıyor ve **son planda
   olmayan hiçbir işi erken başlatmıyor** (13'te 0). Sıralı kuralın kazancı son planın işleri üzerinden oynatıldığı
   için iyimser; gerçek bir sıralı kural bunu da veremeyebilir (Sol, bulgu 2).
4. **Uçtan uca süreye etkisi.** Dilim 15'in kabulünde kuantum `quick` 14,0 dk, `standard` 24,9 dk sürdü (hedef 10 ve
   15). Bu dilim `quick`'i yaklaşık 1,5–2 dk, `standard`'ı 2–5 dk kısaltır. **`quick` hedefe tek başına varmaz.** 17a
   satırındaki "~2–3 dk" tahmini `quick` için fazlaydı.
5. **Getirme bittikten sonra okumanın bitmesine kalan süre** (okuma koşusunun kuyruğa girmesi, planı ve modeli dâhil):
   `quick` 0,8–2,8 dk, `standard` 3,9–6,2 dk, `detailed` 12–15 dk. Okumanın getirmeyle üst üste binmesi (getirilen iş
   okunmaya hemen başlar) muhtemelen bu dilimden büyük bir kazançtır. Ölçülmedi; bu dilimde yok (karar 7).

## Ortak kararlar (Claude + `gpt-5.6-sol` · medium, 24 Eylül 2026)

1. **Mimari: getirme keşif koşusunun içine taşınır; iki eş zamanlı koşu yok.** `sw` keşif koşusu, özet taramasının kod
   adımından sonra getirmeyi aynı koşunun içinde eş zamanlı bir kol olarak başlatır. Model özet partileri ve zincirleme
   sürerken getirme de sürer. Keşif koşusu iki kol da bitince `completed` olur. Kendiliğinden bir `fulltext_fetch`
   koşusu açılmaz. Kullanıcının elle başlattığı getirme koşusu (`POST /runs`, `fulltext_fetch`) bugünkü gibi kalır.

   Gerekçe: worker bütün araştırmalar için aynı anda tek koşu yürütüyor (`worker.py:99`, tek `current_run_id`);
   araştırma başına tek etkin koşu kuralı store'da (`store.create_run`, `ACTIVE_RUN_STATUSES`). İki eş zamanlı koşu
   worker'ı, model sınırlayıcısının paylaşımını, iki koşunun birlikte duraklatılmasını ve arayüzün "bir etkin koşu"
   varsayımını (`app.py`, `views.py`, `Transcript.tsx`) değiştirmeyi gerektirir. Dilim 18 ve 22 de getirmenin içine
   girecek; o etkileşim onlara da taşınırdı.

2. **Başlama kuralı: güvenli küme, taban görüntüsüyle.** Kod adımı bitince kod bir **taban görüntüsü** saklar: o anda
   tam metin kodu taze olan işler ve PDF metni olan işler (`work_id` ile). Güvenli küme hep bu tabanla hesaplanır;
   getirme kolunun kendi yazdığı kodlar (`not_read_yet`, `no_fulltext`, `text_unreadable`) ve kendi eklediği PDF'ler
   hesaba girmez. Yoksa erken getirilen iş `_settled` ya da `already_text` olup plandan düşer ve arkadaki işler öne
   kayar (Sol, bulgu 4). Her parti kapanışında ve zincirlemenin kod adımlarından sonra kod, okuma planında olup partisi
   kapanmamış işleri aday sayarak planı yeniden hesaplar (`fulltext.fetch_plan`, tabanla). Kesinleşmiş ve bu en kötü
   planın sınırı içindeki her iş getirilir. Bekleyen bir iş kapsam dışı ya da belirsiz çıkarsa sonraki işler yalnız
   yukarı kayar.

   **Kanıtın koşulları** (Sol, bulgu 3). Kural, keşif sürerken şunlar olmadıkça son planla aynı kümeyi getirir: kişinin
   bir işi elle dahil etmesi, hariç tutması ya da geri alması; bir insan tam metin kararı (insan kuyruğu); bir işin
   anahtar sözcük ile zincir arasında yer değiştirmesi. Bunlardan biri olursa erken getirilen iş getirilmiş kalır,
   sınırdan sayılır ve plan kaydında adıyla "önce getirildi, son planda yok" diye yazılır; kalan yer son plana göre
   dolar. Eşit küme iddiası o koşu için bırakılır ve kabul raporunda sayılır.

   **Kimlik `work_id`.** Getirme hakkı (hangi işin getirileceği) ve adımı `work_id` ile tutulur, baş kaydıyla değil:
   zincirleme bir kaydı yayımlanmış sürümle birleştirirse baş değişir ama iş aynı kalır. Kalıcı çıktı en az şunları
   taşır: `baseline_settled`, `baseline_has_text`, `claimed` (hangi anda güvenli olduğu), `fetched_early`, son planın
   kendisi ve sapmalar. Şema, atomik yazım noktaları ve devam kuralı "Kalıcı koordinasyon sözleşmesi" bölümünde.

3. **Bütçe: açık bir kip.** Keşif koşusunun bütçesine `fulltext_fetch: {"mode": "overlap", ...fetch_budget(effort)}`
   girer (iş sınırı, zincir odası, model çağrısı 0). Eski yol ile yeni yol yalnız anahtarın varlığından değil bu açık
   kipten ayrılır. Bu dilimden önce kuyruğa girmiş bir keşif koşusunda kip yoktur; bugünkü gibi sonunda ayrı getirme
   koşusunu kuyruğa koyar ve o koşunun bitişi okumayı açar. `fulltext_fetch = off` iken getirme hiç başlamaz.

4. **Duraklatma: tek durum yazarı.** Kollar `_checkpoint` çağırmaz; yalnız durma isteğini okur
   (`_stop_requested`) ve yeni iş ya da parti göndermeyi keser. Model kolundaki bugünkü `_send_through_limiter`
   çağrısı bu kipte `_checkpoint` yerine durma isteğini okur; yoksa koşu, getirme kolunda dört iş hâlâ uçuştayken
   `paused` görünür (Sol, bulgu 5). Bir kolu `cancel()` ile kesmek yok: indirme adımları yarım kalırdı. Koordinatör iki
   kolun uçuştaki işlerini boşaltır, sonra bir kez `_checkpoint` çağırır. Model kaynaklı `_pause` (bağlantı yok, bütçe)
   da koordinatöre bildirilir, getirme boşaltılır, sonra yazılır. Beklenmeyen bir hata öteki kolu durdurur, boşaltır ve
   sonra yükselir. Devam eden koşu getirilmiş işleri adım anahtarından tanır ve güvenli kümeyi taban görüntüsü ile saklı
   kararlardan yeniden hesaplar. Çökmeden sonra worker'ın `outcome_unknown` / `paused` kuralı değişmez.

5. **Okuma koşusunu açan yol açık.** Yeni kipteki keşif koşusu tamamlanınca, gömülü getirmenin özeti yazılmışsa,
   `_queue_fulltext_adjudication` doğrudan keşif koşusundan çağrılır (aynı turda, `await` yok, D85). İdempotans anahtarı
   ayrıdır (`fulltext_adjudication:after:<keşif koşusu>`); eski yolun anahtarı (`…:after:<getirme koşusu>`) değişmez.
   Okuma tam bir kez açılır; iki yol da testle sabitlenir (Sol, bulgu 6).

6. **Zaman çizelgesi.** Getirme keşif turunun içinde bir aşama satırı olur ("Tam metin getiriliyor: N / M"). Tarama ve
   PDF aşamaları aynı anda "sürüyor" görünebilir; tur, getirme özeti yazılmadan başarı söylemez. Ayrı "Tam metin getirme"
   turu kendiliğinden açılmaz. Elle başlatılan getirme koşusunun turu bugünkü gibi kalır.

7. **17b ayrı, sözleşme şimdi.** Okumanın getirmeyle üst üste binmesi bu dilimde uygulanmaz: okumanın ayrı model
   bütçesi, iş başı iki çağrısı, donmuş okuma planı ve kimlik denetimi hata yüzeyini büyütür. Ama 17a'nın kalıcı iş
   kaydı ve olayı 17b'nin okuyacağı biçimde tanımlanır: `work_id` ile getirme hakkı, işin getirme sonucu (kod, dosya,
   okunacak sürüm) ve bir iş hazır olduğunda yazılan olay (`fulltext_work_settled`). 17b bunu okur, 17a'ya dokunmaz.
   Durum makinesi ve teslim kuralı "Kalıcı koordinasyon sözleşmesi" bölümünde.

8. **Kabul: kapılar deterministik, canlı süre betimleyici.** Kabul kapıları: küme eşitliği (tabanla, kanıtın
   koşulları altında), idempotans, iki kolun her bitiş sırasında duraklatma, okumanın tam bir kez açılması ve "son
   model partisi bitmeden en az bir getirme adımı başladı". Canlı iki koşu (kuantum `quick` ve `standard`, protokol
   olduğu gibi, gömme `off`, model sahibin seçimi; son ölçümler `codex` / `gpt-5.6-luna` · medium) süreyi yalnız
   betimler: tek koşu 1–5 dakikalık bir nedensel kazancı kanıtlamaz. Canlı koşuda şunlar da kaydedilir: `host_gate`
   bekleme süresi, model çağrılarının duvar süresi, olay döngüsü gecikmesi, PDF kayıt işlemlerinin süresi, zincirin
   süresi (Sol, bulgu 7). `host_gate` kaldırılmaz; yalnız etkisi ölçülür.

## Kalıcı koordinasyon sözleşmesi (karar 2 ve 7)

Yeni tablo yok: sözleşme bugünkü `run_steps` satırları (işlem anahtarıyla tek) ve araştırma olaylarıyla kurulur. Hepsi
yeni kipteki keşif koşusunun adımlarıdır.

1. **Taban görüntüsü: `fetch_baseline` adımı** (`code:fetch_baseline`). `code:abstract_stage` başarıyla bittikten
   sonra, getirme kolu başlamadan, tek kısa işlemde yazılır. Çıktı: `{"version": 1, "as_of": <an>, "scope_revision",
   "criterion_hash", "limit", "chain_room", "keyword_order_step": <ranking adımının kimliği>, "settled": [work_id…],
   "has_text": [work_id…], "hash": …}`. `settled` ve `has_text` sıralı listelerdir; `hash`, `hash` alanı dışındaki
   nesnenin `domain.canonical.sha256_hex` özeti (deponun tek kanonik biçimi). Aynı tabanın başka sırayla kurulması aynı
   özeti verir (test). `settled`: o anda taze bir `OWNED_CODES` tam metin kodu
   taşıyan işler; `has_text`: bir sürümünde güncel çıkarımdan PDF metni olan işler. Başarıyla yazılmış adım devamda
   aynen okunur, yeniden hesaplanmaz. Kapsam revizyonu koşuyu zaten durdurur (`_stop_requested`).
2. **Getirme hakkı ve sonucu: `fulltext_work:<work_id>` adımı** (`code:fulltext_work`, bugünkü türle). Durumlar adımın
   kendi durumudur:
   - `pending`: hak verildi. Adım, iş güvenli kümeye girdiği anda tek işlemde, hak kaydıyla birlikte açılır:
     çıktı `{"claim": {"claimed_at": <an>, "early": true|false}}`. `run_steps`'te açılış zamanı sütunu olmadığı için
     zaman çıktıda tutulur; bunun için store'a adımı çıktısıyla açan küçük bir yol eklenir (`step` bugün çıktısız
     açıyor). Bir kez açılan hak geri alınmaz.
   - `running`: istek yolda (`start_step`).
   - `succeeded`: sonuç yazıldı. **Tek işlemde:** adımın çıktısı, `fulltext_work_settled` olayı ve işin tam metin
     kodu (`_write_fulltext_codes`). Bugün kod ve adım iki ayrı işlemde yazılıyor; bu kipte birleşir. Tek istisna insan
     kararı: sürümde bir insan tam metin kararı varsa `_write_fulltext_codes` bugünkü gibi kod yazmaz. O zaman adım ve
     olay yine yazılır, çıktı `"code_written": false, "held_by": "human"` der ve olayın `code` alanı boş olur (yarış
     testi). Çıktı: `{"claim", "work_id", "head", "read_version", "code", "code_written", "held_by", "asset_id",
     "identity", "route", "requests_unanswered"}`.
   - `failed`: bugünkü kural (D18). Kod yazılmaz, iş sonraki koşuda yeniden denenir.
   - `outcome_unknown`: çökme anında `running` olan adım (worker'ın açılış kuralı). Devamda yeniden gönderilir, bugünkü
     `_fulltext_work` gibi (yalnız `succeeded` ve `failed` atlanır). Bu yüzden teslim **en az bir kez**dir: yanıt
     gelmeden çöken bir işin isteği her devamda bir kez daha gider. Sınır adımın kendi `attempt` sayacıdır
     (`start_step` her başlangıçta artırıyor): `FULLTEXT_WORK_ATTEMPTS = 3` başlangıçtan sonra hâlâ `outcome_unknown`
     olan adım gönderilmez, `failed` / `fetch_not_settled` ile kapanır, kod yazılmaz ve iş sonraki koşuda yeniden
     denenir (D18'in "cevap yoksa karar yok" kuralı). Getirme yalnız okur; isteğin tekrarı bir şey yazmaz.
3. **Son plan: `fulltext_plan` adımı**, model kolu bitince bir kez: tabanla hesaplanmış plan (bugünkü çıktı alanları),
   artı `baseline_hash`, `claimed_early` (model kolu bitmeden hakkı verilen işler), `deviations`
   (`[{work_id, reason: "user_selection" | "human_fulltext" | "group_change"}]`: hakkı verilmiş ama son planda olmayan
   işler) ve `conditions_held` (sapma yoksa `true`). Planın kalan işlerine hak verilir, getirilir; en sonda
   `fulltext_summary`.
4. **Olay: `fulltext_work_settled`** `{run_id, work_id, head, read_version, code, asset_id, step_id}`. Olay yalnız
   uyandırır: tüketici (17b'nin okuması, arayüz) gerçeği adımdan ve karardan okur, olaydan değil. Olay adımla aynı
   işlemde yazıldığı için adımı olmayan olay, olayı olmayan başarılı adım olmaz. Geç başlayan ya da yeniden başlayan
   tüketici olay akışının ortasından başlamaz. Önce araştırmanın en son olay kimliğini okur (`E`), sonra koşunun
   `succeeded` `fulltext_work:*` adımlarını baştan tarar, sonra olayları `after_id = E` ile izler. Taramadan önce
   alınan `E` sayesinde tarama sırasında biten bir iş ya taramada ya olaylarda görülür, ikisinde birden görülürse
   idempotans onu tek sayar; arada kaçan iş olmaz (tek bağlantı ve olayın adımla aynı işlemde yazılması bunu sağlar). Tüketicinin kendi işlem anahtarı da `work_id`
   taşır (17b'de `fulltext_adjudication:<work_id>:<koşu>`); aynı işi iki kez görmesi bir şey değiştirmez.
5. **Devam ve çökme.** Devam eden koşu: taban adımı okunur; hakkı verilmiş adımlar anahtarlarından tanınır;
   `succeeded` ya da `failed` olanlar atlanır, `pending` olanlar gönderilir; güvenli küme taban ile saklı özet
   kararlarından yeniden hesaplanır ve yalnız hakkı verilmemiş işlere yeni hak açılır. Son plan adımı yazılmışsa aynen
   okunur. `succeeded` ya da `failed` adımın işi yeniden gönderilmez; `outcome_unknown` olanınki bir kez daha gidebilir
   (madde 2).
6. **Kanıtın dayandığı sabitler.** Bütçe (koşunun kendi `fulltext_fetch` alt anahtarı), anahtar sözcük sırası (kod
   adımından önce yazılmış `ranking` adımı), kapsam revizyonu ve ölçüt özeti (taban adımında) koşu boyunca sabittir.
   Zincir sırası `chain_ranking` adımı yazılınca sabitlenir; zincir grubuna o adımdan ve zincir işlerinin özet
   kararlarından önce hak verilmez. Kişinin seçimi ve insan kararı sabit değildir: değişirse karar 2'deki sapma yolu.
7. **Testle sabitlenen:** bu kipte hiçbir alt çağrı `_checkpoint` yazmaz (koordinatör dışında `update_run` ile
   `paused` yazan yol yok); başarılı adımın çıktısı, olayı ve (insan kararı yoksa) kodu birlikte vardır ya da hiçbiri
   yoktur; insan kararıyla yarışta kod yazılmaz ama adım ve olay yazılır; devam `succeeded`/`failed` adımı yeniden
   göndermez; taban adımı devamda değişmez ve özeti sıradan bağımsızdır.

## Global constraints

- **Yalnız `sw`.** `legacy` araştırmanın keşfi, getirmesi ve API'si değişmez.
- **Getirilen küme, kodlar ve okuma değişmez** (karar 2'nin koşulları altında). Getirme yalnız kendi üç `unresolved`
  kodunu yazar (`fulltext.OWNED_CODES`: `not_read_yet`, `text_unreadable`, `no_fulltext`); hiçbir iş getirmeyle dahil ya
  da hariç olmaz. Kullanıcının kararı atlanır, üzerine yazılmaz.
- **Model sözleşmesi ve yöntem paketi değişmez.** `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca` kalır. Migration beklenmiyor (son `0051`);
  kalıcı iş kaydı adım çıktısına sığmazsa yeni numaralı dosya. Yeni neden kodu yok.
- **Tek SQLite bağlantısı.** Kollar olay döngüsünde; yazmalar kısa eşzamanlı işlemler, bir işlemin içinde `await` yok.
  Model sınırlayıcısı getirmeyi saymaz; getirme kendi 4'lük sınırıyla ve `fetch.host_gate` ile koşar. Zincirleme ile
  başka kopya araması aynı OpenAlex kilidini paylaşır; biri ötekini bekletebilir (ölçülür, karar 8).
- **Konuya özgü hiçbir şey yok.** Kural sıralamadan, gruplardan ve sınırlardan türer.

## Task taslağı

1. **Güvenli küme (saf fonksiyon).** `fulltext.py`: `safe_to_fetch(works, order, limit, chain_order, room, pending,
   baseline)`. Özellik testi: bekleyen işlerin bütün son sonuçlarında (aday, kapsam dışı, belirsiz) erken getirilen her
   iş son planda. Ayrı testler: `already_text`, taze ve eskimiş karar, çok sürüm ve baş değişimi, zincir odasının
   anahtar sözcük kotasından ayrı kalması, tabanın getirme kolunun kendi kodlarını maskelemesi, kanıt koşullarından
   biri bozulunca sapmanın adıyla sayılması.
2. **Keşfin içinde getirme kolu ve koordinatör.** `flow._discovery`: kod adımından sonra taban görüntüsü (adım) ve
   getirme kolu; her parti kapanışı ve zincirlemenin kod adımları kolu yeni güvenli işlerle besler; model kolu bitince
   kalan plan getirilir; `fulltext_plan` ve `fulltext_summary` keşif koşusunda, `work_id` anahtarlı getirme adımlarıyla.
   Model kolunun durma kontrolü bu kipte `_checkpoint` değil `_stop_requested`. Okuma koşusu karar 5'teki gibi.
3. **Duraklatma, iptal, devam, çökme.** Kullanıcı duraklatması, iptal, kapsam revizyonu, model kaynaklı `_pause`,
   beklenmeyen hata; iki kolun iki bitiş sırası. Çökme: ağ yanıtından önce, dosya yazıldıktan sonra, karar
   yazıldıktan sonra, son plan yazılmadan önce. Devamda `succeeded` ya da `failed` adımın isteği yeniden gitmez;
   `outcome_unknown` adımınki her devamda bir kez daha gider, üç başlangıçtan sonra `failed` / `fetch_not_settled` ile
   kapanır (sözleşme madde 2; art arda üç çökme testi).
4. **Zaman çizelgesi.** `Transcript.tsx` keşif turunda getirme aşaması, `labels.ts`, `i18n.ts`.
5. **Testler.** Mevcut sabitleyen testler yeni kipe göre: `test_a_completed_sw_discovery_run_is_followed_by_one_retrieval_run`
   (eski kip; yenisi okumanın doğrudan açıldığını sınar), `test_a_paused_discovery_run_queues_nothing`,
   `test_an_answer_run_waits_for_the_retrieval_run_and_is_free_once_it_is_paused`,
   `test_an_sw_run_chains_after_the_abstract_stage`, `test_the_keyword_ranking_read_plan_and_fetch_plan_are_unchanged_by_chaining`.
   Yeni: getirmenin son model partisi kapanmadan başladığı, aynı işleri getirdiği, eski bütçeli koşunun eski yolu izlediği,
   okumanın her iki yolda tam bir kez açıldığı. Playwright A–J.
6. **Kabul ve kapanış** (karar 8), D kaydı, SW10 durum satırı, sw-status satırı.

## Bu dilimde yok

- Okumanın getirmeyle üst üste binmesi (17b; sözleşmesi karar 7'de).
- Getirmenin paralelliğini (4), iş sınırlarını ya da `host_gate`'i değiştirmek.
- Worker'ın aynı anda birden çok koşu yürütmesi.
- Yanıt koşusunun süresi.

## Ölçülmedi

Getirme ile model partilerinin aynı anda koşmasının model çağrılarını, zincirlemeyi ya da olay döngüsünü yavaşlatıp
yavaşlatmadığı: oynatma iş başı süreleri sabit tutuyor, ağ ve yayıncı davranışı eş zamanlılıkta değişebilir. Kişinin
keşif sürerken bir işi elle değiştirmesinin ne sıklıkla olduğu. Kuantum dışı konularda kod adımında güvenli olan iş
payı (ölçülen 13 kütüphanenin 9'u `q1`, 4'ü `q2`). `safe_set.py`'nin geri alması seçimleri kodun durumuna döndürüyor;
bu kütüphanelerde plan anından önce kişinin seçtiği iş yoktu, başka kütüphanede bu varsayım tutmayabilir.
