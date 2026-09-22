# SW dilim 13 — Uçtan uca duman testi: koşu planı

**Tarih:** 22 Eylül 2026. **Durum:** koşuldu (dört koşu; sonuç `.local/sw-smoke-2026-09-22/result.md` ve `result-run4.md`). **Ana dosya:** [sw-status.md](sw-status.md). **Ana plan:** [sw-implementation-plan.md](sw-implementation-plan.md) (§2 kuralları geçerlidir; kural 7'nin ikinci istisnası bu dilimdir). **Önkoşul:** 01–12 (hepsi kapandı). **Tür:** Duman. **Koşan:** Fable · high. **İnceleme:** yok; sonuç kaydı sahibe gider.

**Sahibin kararları (22 Eylül 2026, plan sohbeti; sahip sorulan üç seçeneğe cevap vermedi, plan önerilen varsayılanları alır ve sahip başlamadan değiştirebilir):**

1. **Model:** DeepSeek bağlantısı, `deepseek-flash`, efor `high` (ana plan §2 kural 7'nin ölçüm modeli; Luna kotası bitti). Yanıt ve inceleme adımları da aynı modelle.
2. **Soru:** kuantum dolanıklık dağıtımı sorusu, [prisma-s-hybrid-search-design-2026-09-18.md](prisma-s-hybrid-search-design-2026-09-18.md) §"isolated trial"daki tam metin, değiştirilmeden.
3. **Efor:** `quick` (özet 40 iş, getirme 40 iş, okuma 20 iş). Kaba çağrı sayısı: ölçüt 3 + özet 4 + okuma en çok 40 + yanıt 1 + inceleme 1 ≈ 50.

**Goal:** Dilim 01–12'nin kurduğu `sw` omurgası (dağarcık → ölçüt → onay → arama → özet taraması → getirme → okuma → `selections` → yanıt) bugüne kadar hiçbir yerde baştan sona koşmadı; her dilim sahte modelle sınandı. Bu dilim **tek** araştırmayı gerçek modelle, ayrı bir veri dizininde, sorudan kaynak bağlantılı yanıta kadar koşturur ve **nerede durduğunu** kaydeder. Amaç ölçmek ya da kalite yargısı vermek değil; omurganın ilk kez birleştiği yerde çalıştığını görmek, bulunan hatayı düzeltmek.

## Global constraints

- **Canlı kütüphaneye dokunulmaz:** ayrı `DEIXIS_DATA_DIR` (`.local/sw-smoke-2026-09-22/data`), 8765 dışı port (`8799`), varsayılan veri dizini açılmaz. Kayıt kütüphaneye taşınmaz.
- **Beklenti koşudan önce dondurulur:** `.local/sw-smoke-2026-09-22/protocol.md` ilk çağrıdan önce yazılır (Task 1) ve sonra düzenlenmez; sapma `result.md`'ye yazılır.
- **Kalite yargısı yok.** Etiketlerin doğruluğu, ifadelerin iyiliği, yanıtın kalitesi bu dilimin konusu değildir; "ölçülmedi" diye yazılır (dilim 24). Kaydedilen yalnızca: bitti mi, nerede durdu, aşama başına sayılar, model çağrısı ve token, süre.
- **Hata bulunursa düzeltilir**, dilimin kendi kuralıyla: önce başarısız test (sahte modelle, `tests/`), sonra düzeltme, ayrı commit (`Smoke slice 13: …`), tam pytest yeşil. Düzeltme davranış değiştiriyorsa `D86` girdisi; değiştirmiyorsa karar kaydı yok. Düzeltmeden sonra koşu **baştan** yinelenir (yeni veri dizini, `data-2`), kısmi sürdürme sonuç sayılmaz.
- **Duraklama gerçek üründeki gibi aşılır:** protokol onayı `ask` kalır; kart `awaiting_approval`'da durunca koşan, öneriyi **olduğu gibi** onaylar (`POST /api/runs/{id}/protocol-approval`, düzenleme yok) ve bunu kaydeder. `as_proposed` ayarı kullanılmaz: kartın gerçek yolu ilk kez burada koşar.
- Gömme kapalı (`semantic_search` ayarı `off`); bu koşu SW8'i sınamaz. Denklem okuyucu (Marker) kuruluysa kapalı bırakılır.
- **Bilinen açıklar, koşuda bakılacak** (dilim 12 ön kontrolü, incelemede ele alınmadı): (a) limiter 1'den büyükken bir iş bütçe sınırında tek koşuyla kalabilir — okuma özetinde `not_settled` ile planın `works` sayısı ve `usage.model_calls` karşılaştırılır; (b) `close_ready` istisnayı kayıtsız yutar — kararı olmayan ve `failed` adımı da olmayan iş var mı bakılır.
- Ürün koduna, yöntem paketine ve istemlere **koşu sırasında dokunulmaz**; istem "kötü çıktı" diye düzeltilmez (o dilim 24'ün işi).
- `.local/` izlenmez; yalnızca `sw-status.md`, varsa düzeltme ve `D86` commit'lenir. Yapay zekâ atfı yok.

## Task 1: hazırlık ve dondurulmuş beklenti

- `git pull --ff-only`; `cd apps/web && npm ci && npm run build` (sunucu `dist/`i verir).
- `.env`'de `DEEPSEEK_API_KEY` var mı: `GET /api/connections/deepseek` `ready: true` demeli; değilse dur ve sahibe sor (anahtar istenmez).
- `.local/sw-smoke-2026-09-22/protocol.md`: tarih, commit hash'i, `skill_package_hash`, model / efor / soru / ayarlar, ve **beklenti**: (1) keşif koşusu onay duraklamasından sonra `completed`; (2) getirme koşusu kendiliğinden açılır ve `completed`; (3) okuma koşusu kendiliğinden açılır ve `completed`; (4) en az bir iş `included`, `origin = code_rule`; (5) yanıt koşusu `structurally_valid` bir yanıt verir ve her çapası saklı pasaja çözülür. Başka sayı tahmini yazılmaz.
- Sunucu: `DEIXIS_DATA_DIR=<abs .local/…/data> DEIXIS_SEARCH_WORKFLOW=sw DEIXIS_FULLTEXT_FETCH=auto DEIXIS_FULLTEXT_ADJUDICATION=auto PYTHONPATH=backend uv run python -m deixis serve --port 8799 --no-browser`, arka planda, günlüğü `.local/…/server.log`.

## Task 2: koşu

API ile (CSRF: `GET /api/session` → `x-deixis-csrf`), her adım zaman damgasıyla `.local/…/log.md`'ye:

1. `POST /api/researches`: soru, `effort: quick`, `model_connection: deepseek`, `requested_model: deepseek-flash`, `reasoning_effort: high`, `source_scope: academic`. Keşif koşusu kendiliğinden başlar.
2. Koşuyu izle (`GET /api/researches/{id}`, olaylar). `awaiting_approval`'da: kartın gövdesini (dağarcık, ölçüt, parçalar, ifadeler, dışlama sözcükleri) `log.md`'ye kopyala, olduğu gibi onayla.
3. Keşif `completed` olunca: getirme koşusunun kuyruğa girdiğini, bitince okuma koşusunun girdiğini bekle. Her koşu için: durum, süre, adım sayısı, `failed` adımlar ve `error_code`'ları.
4. Okuma bittiğinde `POST …/runs {"kind": "answer"}`; bitince yanıtın durumunu ve çapa çözümünü kaydet.
5. Koşu herhangi bir yerde `paused` / `failed` kalırsa: neden kodu, ilgili adım çıktısı ve günlük satırı kaydedilir; **sürdürülmez**. Neden bir üründe hata ise Global constraints'teki düzeltme yolu; neden dış ise (sağlayıcı 5xx, anahtar, kota) not edilir ve koşu bir kez yeni veri dizininde yinelenir.

## Task 3: sayılar

Sunucu durduktan sonra `library.sqlite` salt okunur açılır (`sqlite3 'file:…?mode=ro'`), `result.json`'a:

- Aşama başına: bulunan, tekil iş, kod aşamasında kapanan, modele giden, `candidate` / `out_of_scope` / `unresolved` (gerekçe koduna göre), getirilen / `no_fulltext` / `text_unreadable` / `not_reached`, okunan / `include` / `criterion_not_met` / `unresolved` (koda göre) / `not_settled` / `identity_unconfirmed` / `whole_text`, `selections` dağılımı ve kökeni, yanıt durumu ve çapa sayısı. Kaynak: `code:*` özet adımlarının çıktıları (`run_steps.output_json`) ve `stage_decisions` / `selections`; ikisi tutmuyorsa **ikisi de** yazılır.
- Model: koşu başına `usage.model_calls`; `model_sessions.token_usage_json` toplamı (girdi / çıktı), başarısız ve `invalid_model_output` oturum sayısı, şema onarımı sayısı.
- Süre: koşu başına duvar saati; okuma koşusunda iş başına ortalama.
- Alıntı doğrulama: `model_proposals`'ta `quote_verified` oranı, parça başına; doğrulanmayan alıntıların ilk üçü modelin metni ve en yakın sayfa metniyle (yargısız, örnek olarak).

## Task 4: kayıt ve kapanış

- `result.md`: beklentinin beş maddesi tek tek tuttu / tutmadı; nerede durdu; bulunan hatalar ve commit'leri; sayı tablosu; **ölçülmedi** listesi (etiket doğruluğu, ifade kalitesi, yanıt kalitesi, ikinci konu, `standard` / `detailed` efor, gömme açıkken davranış, limiter > 1 bütçe gediğinin ürünle tetiklenip tetiklenmediği — yalnızca gözlendiyse yazılır).
- `sw-status.md` satır 13: `koşuldu` + tek cümle sonuç + `.local` yolu; düzeltme varsa hash'i. SW belgesine durum satırı eklenmez (tasarım kararı yok). Bu dilim tam pytest'i **yalnızca** düzeltme yaptıysa koşar.
- Sunucu durdurulur; `.local/…/data` silinmez (kanıt), sahip isterse siler.

## Son ileti

Beklentinin beş maddesi; nerede durdu; aşama sayıları (tek tablo); çağrı, token, süre; bulunan hatalar ve commit'leri; düzeltme yapıldıysa yinelenen koşunun sonucu; ölçülmeyenler; canlı kütüphaneye ve 8765'e dokunulmadığı; hangi kararların (model, soru, efor) plan varsayılanı olduğu.

## Açık noktalar

- **Tek konu, tek koşu, tek model:** çıkan her sayı örnektir, ölçüm değil. İkinci konu dilim 24.
- **Sahip görmeli:** koşu, sahibin kararı olmadan ilk kez iş dahil edecek ve `sw` yanıtı o işlere dayanacak; sonuç canlı kütüphaneye girmez.
- **Onay kartı elle onaylanıyor:** kartın anlaşılırlığı ölçülmez (08b'nin açık noktası).
- **Bütçe:** `quick` `max_model_calls`'ta onarım ve başarısız çağrı sayıldığı için okuma koşusu 20 işin bir kısmını `not_reached` bırakabilir; bu bir hata değil, kayıttır.
