# SW dilim 21 — Yerleşik yerel gömme

**Tarih:** 25 Eylül 2026. **Durum:** plan hazır; A1, B1, C1 önerildiği gibi (sahip soru sorulmadan ilerlenmesini istedi, 2026-09-25).
**İkinci görüş:** `gpt-6-sol` · high, salt okunur. **Birinci tur** (`sol/answer-r1.md`): "hazır değil", 11 bulgu;
eşgüdümcünün isteğiyle on biri de koddan doğrulandı ve işlendi: (1) "soru zaten İngilizce" yolu kendi dil denetimine
takılıyordu → ayrı doğrulama, yalnız güncel sorunun aynısı (karar 6); (2) model kaldırılınca saklı benzerliklerin
kullanımı → sabit modelin saklı çıktısı okunur, yeni gömme yapılmaz, çıktıda ayrı sayılır (karar 5); (3) uzun gömmede
ayar değişirse benzerlik ve sıralama farklı modeli okuyabiliyordu → koşunun gömme modeli adım açılırken dondurulur,
sıralama onu okur (karar 4a); (4) `uv`'nin önbelleği ve Python yükleme yeri veri dizinine, çökmüş kurulumun
toparlanması, tamamlanma işareti (karar 2); (5) yüklenen PDF uyarısı gönderim anını öngöremiyordu → koşullu metin,
gönderilen dosya ve pasaj sayısı adım çıktısında (karar 10); (6) kısmi pasaj gömmesinin yanıttaki sonucu tanımlandı
(karar 4); (7) 429 beklemesi kesilebilir, bekleme bütçesi adım boyunca paylaşılır (karar 8); (8) beş dosya tek
manifestle her yerde denetlenir, alt süreç cevabı doğrulanır (karar 1, 2); (9) boyut ve süre metinleri ölçümün
sınırına çekildi, "no text leaves the computer" yalnız gömmeye bağlandı (karar 9, 12); (10) prompt planı `main`'deki
commit'ten okur, SW8'den bilinçli sapmalar adlarıyla (aşağıda "SW8'den sapmalar"); (11) sütun yolu, paket sayısı
(18), "kapalı"nın yeri düzeltildi. **İkinci tur** (`sol/answer-r2.md`): "hazır değil"; 11'in 6'sı kapandı (1, 5, 6, 11
ve plan sözleşmesi olarak 9'un eski kısmı), 5'i açık kaldı ya da yeni eksik gösterdi; eşgüdümcünün isteğiyle 1–5.
maddeler koddan doğrulandı ve işlendi (6. madde, planın `main`'e işlenmesi, eşgüdümcünündür): (1) her koşuda, eksik
kaynak olmasa da model kimliği taşıyan bir `source_similarity` adımı açılır, saklı skorlar bu adımdan okunur;
"yalnız dört sinyal" ile "saklı beşinci sinyal" ayrıldı (karar 4a, 5); (2) `finish_step` çıktıyı değiştirdiği için
kimlik her bitişte aynı kayıttan yeniden yazılır (karar 4a); (3) 429 bütçesi adım çıktısında kalıcı, sürdürme kalanı
oradan kurar (karar 8); (4) kurulum işi diskte bir iş dosyasıyla izlenir, kaldırma ile çalışan süreç sıralandı (karar 2);
(5) manifest önbelleğinin sınırı yazıldı, disk metni Python ve `uv` önbelleğini anar (karar 1, 2). **Üçüncü tur**
(`sol/answer-r3.md`): "hazır değil", 4 bulgu (2 yüksek, 2 orta), dördü de koddan doğrulandı ve işlendi: (1) kaldırma
başında yeni istekleri kapatan `removing` durumu, silme bitene dek (karar 2); (2) kurulumun sahipliği bir OS kilidiyle
(`fcntl.flock`, `worker.py`'nin deseni), `uv` alt süreçleri kilidi miras alır, toparlanma yalnız kilidi alabilirse
temizler (karar 2); (3) `_finish_embedding_step` ve saniyelik yazma son saklı çıktıyla birleştirir, bitişte
`waited_seconds` korunur (karar 4a, 8); (4) `available` "son tam denetimi geçti ve o günden beri dosyalar değişmedi"
demektir, tam denetim süreç başlangıcında zorunlu kapıdır (karar 1, 3). **Altıncı tur** (`sol/answer-r6.md`): 2 yüksek bulgu, ikisi de işlendi: (1) "eksik yoksa sorguyu gömme" kuralı
pasajlarda sırayı imkânsız kılıyordu → kural ayrıldı: kaynaklarda saklı skor yeter, pasajlarda sorgu her zaman gömülür,
model yoksa sözcük sıralaması (karar 4); (2) `ready` denetiminde ölen kurulumun çalıştırıcısı yaşarken toparlanma
ortamı silebilirdi → toparlanma silmeden önce kullanımda kilidinde de `LOCK_EX` ister, alamazsa bir sonrakine bırakır
(karar 2). **Beşinci tur** (`sol/answer-r5.md`): 3 bulgu ve 1 düşük, dördü de işlendi: (1) kurulum kendi `ready`
denetimini özel kilitle engelliyordu → kilit sırası (a)–(f), dosya adımlarından sonra paylaşımlıya iniş, denetim
çalıştırıcısı kilidi miras alır (karar 2); (2) eksik yoksa sorgu da gömülmez (karar 4); (3) Windows'ta bütün yerleşik
uç noktaları `unsupported_platform` (karar 1); (düşük) promptun yazma listesine iş dosyası ve iki kilit dosyası.
**Dördüncü tur** (`sol/answer-r4.md`): 3 bulgu
(1 yüksek, 2 orta), üçüncü turun gerisi kapandı; üçü de işlendi: (1) kaldırma aynı veri dizinini kullanan ikinci bir
sunucunun çalıştırıcısını görmüyordu (`app.py:372`: işçi kilidini alamayan sunucu API'yle çalışmaya devam ediyor) →
"model kullanımda" kilidi, çalıştırıcı paylaşımlı tutar, kaldırma ve kurulum özel ister (karar 2); (2) iptal yalnız bu
sürecin sahip olduğu işi durdurur, iş dosyasını yalnız kilidin sahibi yazar (karar 2); (3) Windows bu dilimde
desteklenmez, `unsupported_platform` (karar 1, "Bu dilimde yok"). **Yedinci tur** (`sol/answer-r7.md`): bulgu yok, "hazır". Tur başına bulgu: 11, 5 (açık kalan), 4, 3, 3 (+1 düşük), 2, 0. **Prompt:** [sw-slice21-prompt.md](sw-slice21-prompt.md). **Ana dosya:**
[sw-status.md](sw-status.md). **Karar:** yeni D numarası (dilim yazar; en yüksek D102, yani D103). **Önkoşul:** 01 (D70),
kapandı; D79'un gömme sinyali ve kurtarma kolu ile D101'in "gömmenin öne aldıkları" tablosu bu dilimin girdisidir.
**Tür:** Kur. **Uygulayan:** Opus · high (satır 21 medium diyordu; ayrı bir çalışma ortamı, kurulum işi, alt süreç
protokolü, bir migration ve bütün sağlayıcılar için parti parti yazma aynı dilimde, köşe durumlarında yargı gerekir).
**İnceleme:** toplu (Sol · high). **Plan:** Opus 5.5 · high (plan turunun kuralı Fable · high; bu oturum Opus'ta koştu).
**Ölçüm:** `.local/sw-slice21-plan-2026-09-25/` (atılacak bir arm64 venv'de `fastembed` 0.8.1 + `onnxruntime` 1.30.0;
`download.py` → `download.json`, `stored.py` → `stored.json`, `timing.py` → `timing.json`, `truncation.py` →
`truncation.json`, `largest256.py` → `largest256.json`; saklı kütüphaneler salt okunur açıldı; ürünün venv'i ve
`uv.lock` değişmedi; model, port ve canlı veri dizini yok; tek ağ erişimi modelin bir kez indirilmesi). **Kapsam:** SW8
madde 3, 4 ve 6; SW8 durum satırının iki açığı (kısmi sonuç, HTTP 429). Madde 7'nin raporu D101'de; kapatma kuralı açık
gereksinim kalır.

**Goal:** Anlamsal arama bugün bir Gemini ya da OpenAI anahtarı, ya da ayrıca kurulmuş Ollama / LM Studio ister (D29).
DEIXIS'i kullanacak kişilerin çoğunda bunlar yok. Bu dilim anahtarsız bir seçenek kurar: "This computer · built-in",
yani `BAAI/bge-small-en-v1.5`'in bu bilgisayarda çalışan kopyası. Kişi onaylayınca bir kez indirilir, boyutu önceden
söylenir, metin bilgisayardan çıkmaz. Yalnız İngilizce okur; soru İngilizce değilse araştırma başına bir İngilizce cümle
istenir, yoksa bu araştırmada yerleşik kol kapalı kalır ve arayüz bunu söyler. Ayarlar ekranı Gemini'yi ve yerleşiği başa koyar
(kapalı sonda kalır; sapmalar aşağıda adıyla), Gemini için ücretsiz anahtarın nasıl alınacağını ve ücretsiz katmanda Google'ın metni
kullanabileceğini yazar. Aynı dilimde gömme adımı, hangi sağlayıcı olursa olsun, yarım kalan işi saklar ve HTTP 429'da
sınırlı bekleyip yeniden dener.

## Bugün kod ne yapıyor

Kod 25 Eylül 2026'da `464e721` üzerinde okundu (`documents/embeddings.py`, `workflow/flow.py`, `workflow/ranking.py`,
`workflow/probes.py`, `workflow/views.py`, `workflow/store.py`, `workflow/protocol.py`, `workflow/decisions.py`,
`workflow/equations.py`, `documents/math_reader.py`, `domain/vocabulary.py`, `api/app.py`, `credentials.py`,
`apps/web/src/Connections.tsx`, `Transcript.tsx`, `labels.ts`; migration `0015`, `0017`, `0040`, `0052`).

- **Sağlayıcı soyutlaması (D29).** `embeddings.PROVIDERS = ("gemini", "openai", "ollama", "lm_studio", "off")`
  (`embeddings.py:27`). `chosen()` (`:85`) kayıtlı seçimi, yoksa `GEMINI_API_KEY` varsa Gemini'yi, yoksa `off`'u verir.
  `Embedder` (`:93`) sağlayıcıya göre Gemini'nin `batchEmbedContents`'ine ya da OpenAI biçimli `/embeddings`'e gider;
  `stored_model` Gemini için çıplak ad, öbürleri için `sağlayıcı:model`. Her istek 100 metinlik parti (`BATCH`, `:28`);
  herhangi bir parti başarısızsa `EmbeddingError` atılır ve o ana kadar alınan vektörler atılır. 429'da bekleme yok.
  `options()` (`:113`) seçeneklerin listesini ve seçilemeyenin nedenini verir.
- **Kaynak benzerliği.** `_source_similarity` (`flow.py:1924`) başlık + özet pasajlarını belgeye, `scope["question"]`'ı
  sorguya gömer, sonuçları `source_similarities`'e (araştırma, revizyon, model, sürüm) tek seferde yazar. `sw`'de keşif
  koşusunda bütün havuz için ve sıralamadan önce çağrılır (`:542`, D79); `legacy`'de taranan adaylar için taramadan
  sonra (`:581`). Adım anahtarı `source_similarity`; ara denetim noktası (`_checkpoint`) yok, yani duraklatma gömme
  bitene kadar beklemez değil, gömme bitmeden fark edilmez. Hata `embedding_failed` ile adımı kapatır, koşu sürer.
- **Model kimliği iki kez okunur.** `_source_similarity` Ayarlar'ı başta okur (`flow.py:1930`); `_ranking` aynı
  koşuda daha sonra `_embedding_model()` ile yeniden okur (`flow.py:1234-1258`). Arada ayar değişirse sıralama başka
  modelin (çoğu zaman boş) benzerliklerini okur. Sıralama saklı benzerliği modelin şu an çalışıp çalışmadığına bakmadan
  okur (`ranking.py:391-405`).
- **Sıralama.** `rank_pool` (`ranking.py`) saklı benzerliği beşinci sinyal yapar; benzerliği olmayan kayıt sinyalin
  kuyruğuna düşer ve kurtarılamaz (`inspection_order`, `RESCUE_OUTSIDE_TOP = 200`, `RESCUE_EMBEDDING_TOP = 50`). Yani
  kısmi bir benzerlik kümesi bugün de tutarlı biçimde okunur: puanlanmış kayıtlar sıralanır, gerisi kuyrukta. Nedenler:
  `embedding_off`, `no_stored_similarity`. D101'in `probes.py:348`'i gömme koştuysa öne alınanları okur.
- **Yanıtın pasaj sıralaması.** `_semantic_ranking` (`flow.py:3931`) dahil işlerin **bütün** pasajlarını gömer (yalnız
  yanıta giden 48'i değil), vektörleri `passage_embeddings`'e (pasaj, model) yazar, bir pasaj model başına bir kez
  gömülür. Tablo sütunlarının doldurulması aynı işlevi sütun metniyle çağırır (`:4304`). Başarısızlıkta sözcük sıralaması
  tek başına kalır.
- **Sorgu metni.** Kaynak benzerliğinde ve yanıtın pasaj sıralamasında sorgu `scope["question"]`, dili ne olursa
  olsun; tablo sütununda `query_text`, yani sütunun adı ve talimatı (`flow.py:4301-4304`). Bir İngilizce cümle alanı yok.
  `sw` akışı İngilizce olmayan soruda `key_terms_needed` ile durur (`flow.py:648-653`); kişi yeni bir kapsam
  revizyonunda İngilizce anahtar terimleri verir (`0040_scope_key_terms.sql`, `store.revise_scope`). Dil kuralı
  `domain/vocabulary.py:56` `detect_language`: ipucu varsa ipucu; Latin dışı harf varsa "başka dil"; aksanlı harf varsa
  İngilizce işlev sözcüğü payı 0,2'nin altındaysa "başka dil"; uzun ve hiç işlev sözcüğü yoksa "başka dil"; gerisi
  İngilizce. Aksansız yazılmış başka dilde bir soru İngilizce okunur (işlevin kendi belgesi söylüyor).
- **Kapsam revizyonu ve eskime.** Yeni bir revizyon her kararı eskitir: `decisions.is_stale` kararın `scope_revision`'ı
  güncel olandan farklıysa eskimiş sayar (`decisions.py:152-155`). Bir cümleyi sonradan eklemek için yeni revizyon açmak
  bu yüzden bütün kararları eskitir.
- **Protokol.** `build_protocol`'ün `signals` listesi gömme girdisinde yalnız `model`'i taşır (`protocol.py:203`);
  `_embedding_model` (`flow.py:1228`) yapılandırılmış modeli okur. `signals` ölçüt alanlarının dışında, ayarı değiştirmek
  hiçbir kararı eskitmez (D79 madde 7).
- **Ayarlar.** `GET/PUT /api/semantic-search` (`app.py:798-823`); `SemanticChoice.provider` beş değerli `Literal`
  (`app.py:133`); şu an seçilemeyen sağlayıcı reddedilir, yerine başkası konmaz. `Connections.tsx:454` bölümü sırayı
  sunucunun listesinden alır (Gemini, OpenAI, Ollama, LM Studio, kapalı); Gemini için "Passage text is sent to Google"
  der; ücretsiz anahtarın nasıl alınacağını ya da ücretsiz katman uyarısını söylemez.
- **İsteğe bağlı yerel bileşen deseni (D52).** Marker kendi ortamında (`<veri dizini>/tools/marker`, uv ile) kurulur,
  modelleri `<veri dizini>/tools/marker-models`'e iner; `EquationService` (`workflow/equations.py:77`) arka planda
  adım adım kurar, iptal eder, kaldırır ve Ayarlar'da gösterir (`app.py:771-796`); `MathReader`
  (`math_reader.py:256`) tek bir alt süreci satır başına bir JSON istekle kullanır ve boşta kalınca kapatır. D52: masaüstü
  paketlerinde (P10) bileşen istek üzerine indirilir, pakete konmaz.
- **Masaüstü paketi yok.** Uygulama `uv run python -m deixis serve` ile yerel web uygulaması olarak çalışır;
  Tauri paketlemesi P10'da, sonraki bir aşamadır (`docs/product/README.md:11`, `implementation-plan.md:300`). SW8'in
  "`onnxruntime`'ın masaüstü paketindeki davranışı" sorusunun bugün karşılığı: paketlenecek bir masaüstü yapısı yok;
  soru "`onnxruntime` DEIXIS'in kendi ortamına mı girer, yoksa D52 gibi istekle indirilen ayrı bir ortama mı"dır
  (soru B).
- **Bağımlılık.** `pyproject.toml` ve `uv.lock`'ta `fastembed`, `onnxruntime`, `numpy`, `tokenizers` ve
  `huggingface-hub` yok.

## Elimizdeki sayılar

Ölçüm Apple M1 Pro (10 çekirdek, 32 GB), yerel arm64 Python 3.12.13, `fastembed` 0.8.1, `onnxruntime` 1.30.0. Tek
bilgisayar; daha yavaş makineler ölçülmedi.

1. **Kurulum.** `fastembed` arm64 uv venv'e sorunsuz kuruldu; DEIXIS'in kilidinde olmayan 18 paket getirdi
   (`onnxruntime`, `numpy`, `tokenizers`, `huggingface-hub`, `hf-xet`, `pillow`, `protobuf`, `flatbuffers`, `loguru`,
   `mmh3`, `py-rust-stemmers`, `requests`, `tqdm`, `pyyaml`, `fsspec`, `filelock`, `charset-normalizer`, `urllib3`), kurulu boyut 145 MB (`onnxruntime`
   76 MB, `numpy` 22 MB, `pillow` 13 MB, `tokenizers` 10 MB). İndirilen tekerlek baytları ölçülmedi (uv önbellekten
   kurdu).
2. **Model.** `fastembed`'in `BAAI/bge-small-en-v1.5`'i, Hugging Face'teki `Qdrant/bge-small-en-v1.5-onnx-Q`
   deposunun nicemlenmiş ONNX'idir (revizyon `aa8f8b060edb00e03bfdd08813a2949946c8ba55`), 384 boyut, 512 jeton. Beş dosya,
   toplam 67.179.163 bayt: `model_optimized.onnx` 66.465.124 (sha256 `51f1bd0a…31`), `tokenizer.json` 711.396,
   `config.json` 706, `tokenizer_config.json` 1.242, `special_tokens_map.json` 695 (tam özetler `download.json`'da).
   SW8'in "yaklaşık 130 MB"ı bu dosya değil. Sabit revizyonlu adres (`…/resolve/<revizyon>/<dosya>`) düz bir HTTP
   yönlendirmesiyle iner; yanıt başlığı `x-linked-etag` dosyanın sha256'sına eşit. İlk yükleme indirme dahil 8,8 sn,
   sonraki yükleme 0,22 sn.
3. **Kütüphanenin dışına yazma.** `fastembed`'in kendi indirmesi `cache_dir` verilse de `~/.cache/huggingface/`'a
   yazdı (`.agent_harnesses.json` ve `xet/logs/`). Dosyalar düz bir klasöre konup `specific_model_path` ve
   `local_files_only=True`, `HF_HUB_OFFLINE=1` ve oturum içi bir `HF_HOME` ile yüklenince hiçbir şey dışarı yazılmadı ve
   ağa gidilmedi (`timing.json`, `hf_home_probe_written: []`).
4. **Süre, 512 jeton (fastembed'in varsayılanı).** SW7 havuzu (1.369 kayıt, 1,98 M karakter, başlık + özet): 64'lük
   partilerle 166 sn ve 108 sn (iki koşu; ikincisi her 64 metni ayrı bir iş parçacığı çağrısıyla), 256'lık partilerle
   227 sn. SW8'in "yaklaşık iki dakika"sı bu aralıkta. En büyük saklı havuz (6.696 kayıt, 8,67 M karakter): **748 sn**.
   Aynı araştırmanın dahil işlerinin bütün pasajları (1.078 pasaj, 1,23 M karakter): 86 sn; ilk 48 pasaj 4,1 sn.
5. **256 jetonda kesmek.** SW7 havuzunda, SW8'in 20 pozitifiyle (`truncation.json`): 512 jeton 106 sn, gömme tek başına
   ortanca 90, ilk 100'de 11; beş sinyal RRF ortanca 102, ilk 100'de 10; kurtarma kolu (200 / 50) g044 ve g062'yi getirdi.
   **256 jeton 51 sn**, tek başına 101,5 / 10, beş sinyal **104 / 10**, kurtarılan aynı iki pozitif. 128 jeton 24 sn ama
   tek başına 151 / 8, beş sinyal 135,5 / 9, kurtarılan g010 ve g044 (g062 düştü). Dört sinyal tek başına 157,5 / 8.
   En büyük havuz 256 jetonda **251 sn** (512 jetonda 748; 64 kayıtlık parti ortanca 2,4 sn, en çok 2,5 sn). Tek konu, 20 pozitif; farklar istatistiksel olarak
   sağlam değil (SW8'in sınırı aynen geçerli).
6. **Olay döngüsü.** Gömme `asyncio.to_thread` ile 64'lük partiler halinde koşarken 50 ms'de bir uyanan bir sayaç 2.073
   ölçümde en çok 19,4 ms, yüzde 95'te 2,3 ms gecikti. ONNX ve tokenizer GIL'i bırakıyor; yani iş parçacığı da döngüyü
   kilitlemez. Seçim bu yüzden döngüye değil paketlemeye ve belleğe dayanır (soru B).
7. **Bellek.** Süreç başına en yüksek yerleşik bellek: 256'lık partilerin de koştuğu ölçümde 8,0 GB, yalnız 64'lük
   partilerle 3,1 GB (512 / 256 / 128 jeton art arda), en büyük havuz 256 jetonda 1,2 GB. Bellek süreç
   kapanınca geri verilir.
8. **Saklı araştırmalarda gömme hiç koşmadı.** 46 saklı `sw` kütüphanesinin 46'sında ayar `{"provider": "off"}`; hiçbir
   koşuda `similarity:*` ya da `embedding:*` adımı yok. D79'un beşinci sinyali, kurtarma kolu ve D101'in "gömmenin öne
   aldıkları" tablosu bugüne dek yalnız sentetik testlerle koştu. Havuz (güncel revizyonun aday sürümleri) 43
   araştırmada 0'dan büyük, ortanca 2.458, en çok 7.711; kayıt başına ortalama özet 1.043 karakter. Dahil işleri olan 33
   araştırmada gömülecek pasaj 29–1.447 (ortanca yaklaşık 500). Hiçbir araştırmada dil ipucu ya da anahtar terim yok;
   saklı sorular İngilizce.

Sayıların gösteremediği: ikinci bir alan; daha yavaş bir bilgisayar; Gemini'nin ücretsiz katmanındaki hız sınırı (SW8
bilerek ölçmedi); pasaj düzeyinde yerel modelin erişim kalitesi; kişinin yazdığı İngilizce cümlenin sorudan ne kadar
uzaklaştığı.

## SW maddeleri: kurulan, açık kalan

| Madde | Bugün | Bu dilimde |
|---|---|---|
| SW8.3 Ayarlar sırası: Gemini (ücretsiz anahtar, nasıl alınır), yerleşik, kapalı; OpenAI / Ollama / LM Studio aynı | Sıra sunucunun listesinden, yerleşik yok, anahtar yolu yok | Kurulur (karar 9) |
| SW8.4 anahtarsız, hesapsız, ayrı uygulamasız yerleşik giriş; onayla tek indirme, boyut gösterilir | Yok | Kurulur (karar 1–3); ortamın yeri soru B |
| SW8.4 aynı sağlayıcı yanıtın pasaj sıralamasına da hizmet eder | Seçilen sağlayıcı iki yolda da | Yerleşik de iki yolda (karar 3); pasaj düzeyinde kalite ölçülmedi |
| SW8.4 ücretsiz anahtar uyarısı; kişinin yüklediği PDF'in metni gömülmeden önce yine | Yok | Kurulur (karar 9, 10); ücretsiz katman koddan anlaşılamıyor |
| SW8.5 model yok ya da kapalıyken dört sinyal aynı | Tutuyor (D79) | Yerleşik için de; eksik dosya ve ölen süreç dahil (karar 5) |
| SW8.6 yalnız İngilizce; İngilizce cümle, kapsam revizyonuyla saklı; yoksa kol kapalı ve arayüz söyler | Yok | Kurulur (karar 6) |
| SW8.6 bağlı bir modelin bir kez önerisi, kişi onaylar | Yok | A1 (kabul): bu dilimde yok |
| SW8 durum satırı: kısmi sonuç yok, 429'da bekleme yok | Doğru | Kurulur, bütün sağlayıcılar için (karar 4, 8) |
| SW8.7 kolun katkısı her araştırmada; kapatma | Rapor D101'de; kapatma yok | Değişmez; kapatma açık gereksinim |

## Kararlar

1. **Yerleşik model DEIXIS'in ortamında değil, D52 gibi istekle kurulan ayrı bir ortamda koşar** (B1, kabul
   edildi). Ortam `<veri dizini>/tools/embedding` (uv, Python 3.12, `fastembed==0.8.1` sabit), model dosyaları
   `<veri dizini>/tools/embedding-models/bge-small-en-v1.5@aa8f8b0/`. DEIXIS `fastembed`'i hiç içe aktarmaz;
   `documents/embedding_runner.py` o ortamda koşar, yalnız standart kütüphaneyi ve `fastembed`'i içe aktarır ve satır
   başına bir JSON istek cevaplar: ilk satır `{"ready": true, "fastembed": "<sürüm>", "onnxruntime": "<sürüm>",
   "dimensions": 384}`; istek `{"id", "kind": "document" | "query", "texts": [...]}`, cevap `{"id", "vectors": [<base64
   float32>...]}` ya da `{"id", "error"}`. Süreç `specific_model_path`, `local_files_only=True`, `HF_HUB_OFFLINE=1`,
   `HF_HOME=<veri dizini>/tools/embedding-hf-home` ile başlar (sayı 3); tokenizer 256 jetonda keser (karar 4).
   `documents/local_embedding.py`'deki `LocalEmbedder` `MathReader`'ın düzenini izler: tek süreç, tek kilit, istekler
   sırayla, `LOCAL_IDLE_SECONDS = 300` boşta kalınca kapatılır (bellek, sayı 7), çökmüş süreç bir sonraki istekte bir kez
   yeniden başlatılır. Başlarken süreç model dosyasının sha256'sını sabitle karşılaştırır, tutmazsa `ready` yerine hata
   verir. **Yalnız POSIX (macOS, Linux):** sahiplik ve kullanım kilitleri `fcntl.flock` ve `pass_fds`'e dayanır;
   Windows'ta (`os.name != "posix"`) yerleşik seçenek bu dilimde yoktur: `options()` onu `available: false`, neden
   `unsupported_platform` ile verir, bütün yerleşik uç noktaları platformu kilit yoluna girmeden, ilk iş denetler: `GET …/builtin` 200 ile
   `{"status": "unsupported_platform"}` döner, `install`, `cancel` ve `DELETE` 409 `unsupported_platform`,
   `LocalEmbedder` hiçbir kilit dosyası açmadan `builtin_unavailable`; Ayarlar "The built-in model is not available on
   Windows yet" yazar. Worker'ın Windows yolu (`msvcrt`, `worker.py:22`) burada kopyalanmaz.
   **Bütünlük tek manifestle** (`MODEL_FILES`: beş dosyanın adı, baytı, sha256'sı): çalıştırıcı `ready`'den önce
   beşini de denetler; `options()` ve `GET …/builtin` aynı manifesti okur (tam sha256 denetimi servis başlarken, kurulum bitince
   ve her süreç başlangıcında yapılır; arada `options()` ve durum uç noktası son tam denetimin sonucunu dosyaların
   `(boyut, mtime_ns, inode)`'u değişmedikçe kullanır. Bu önbellek bir bütünlük kanıtı değildir: aynı boyut ve zaman
   damgasıyla değişmiş bir dosyayı ancak süreç başlangıcındaki tam denetim yakalar, ve orada adım karar 5'e göre düşer.
   Ayarlar "checked" değil "files checked at install and each time the model starts" der); kurulum işi de aynı manifestle indirir. Eksik ya da bozuk
   tek bir yardımcı dosya (tokenizer, yapılandırma) üçünde de aynı sonucu verir: kullanılamaz. **Cevabın denetimi:**
   `LocalEmbedder` her cevapta kimliğin istekle aynı, vektör sayısının metin sayısına eşit, her vektörün 384 boyutlu ve
   bütün değerlerin sonlu olduğunu denetler; tutmayan cevap `builtin_bad_reply` hatasıdır ve süreç kapatılır.
   **Neden:** (1) `uv.lock` ve her kullanıcının kurulumu değişmez; 145 MB'lık yük yalnız bu seçeneği isteyenin
   diskine iner; (2) D52 masaüstü paketi için "istekle indirilir, pakete konmaz" kuralını zaten koydu, `onnxruntime`
   sorusu aynı yoldan kapanır; (3) süreç boşta kapanınca bellek geri verilir (256 jetonda 1,2 GB, 512'de 3 GB'a kadar); (4) duraklatma ve iptal süreci
   bekletebilir ya da öldürebilir. **Bedeli:** makinede `uv` gerekir (Marker da ister; uygulama zaten `uv run` ile
   başlıyor), bir alt süreç protokolü ve kurulum işi yazılır. Döngü kilidi bir neden değildir: sayı 6, iş parçacığının
   da döngüyü kilitlemediğini gösterdi.
2. **İndirme: onay, boyut, ilerleme, özet, yer, toparlanma.** Ayarlar'da yerleşik satırı indirilmemişken "Download"
   düğmesini ve "Needs about 212 MB of disk (runtime about 145 MB installed, model 67 MB), plus about 74 MB if uv has
   to download Python 3.12, plus uv's download cache (not measured)" satırını gösterir. 74 MB, bu makinede uv'nin kurduğu
   CPython 3.12.13'ün dizin boyutudur; önbellek kurulumdan sonra silinmez (yeniden kurulumu hızlandırır) ve kaldırmada
   silinir. 145 MB,
   ölçülen kurulu boyuttur (`RUNTIME_DISK_ESTIMATE`); ağdan inecek tekerlek baytları ölçülmedi, metin indirme miktarı
   vaat etmez. Onay penceresi disk boyutunu, yeri (`<veri dizini>/tools/…`) ve gömmede metnin bilgisayardan
   çıkmadığını söyler. Onaydan sonra `workflow/local_embedding_service.py`'deki `EmbeddingService` (`EquationService`'in ikizi) dört
   adımlı bir arka plan işi koşar: (1) `uv venv`, (2) `uv pip install fastembed==0.8.1`, (3) beş model dosyasını sabit
   revizyonlu adresten DEIXIS'in kendi `httpx` istemcisiyle indirir, her birini önce `*.part`'a yazar, bayt sayısını ve
   sha256'yı koddaki sabitle karşılaştırır, tutarsa yerine taşır, tutmazsa siler ve işi `failed` yapar (hiçbir dosya
   yarım kalmaz); (4) sürecin `ready` satırı ve bilinen bir cümlenin 384 boyutlu, birim uzunlukta vektörü; ancak bu dört adım geçince
   `<veri dizini>/tools/embedding/installed.json` (sürüm, revizyon, tarih) en son yazılır; "kurulu" yalnız bu dosya ve
   manifest tutarsa denir. **Veri dizininin dışına yazma yok:** `uv` adımları `UV_CACHE_DIR=<veri dizini>/tools/uv-cache`,
   `UV_PYTHON_INSTALL_DIR=<veri dizini>/tools/uv-python` ve `UV_PYTHON_PREFERENCE=only-managed` ile koşar (Python 3.12
   yoksa uv onu veri dizinine indirir; sistemdeki Python'a dokunmaz), `HF_HOME` karar 1'deki gibi. **Toparlanma:**
   Kurulum işi bellekte değil diskte izlenir (`EquationService.job` bellekte, `equations.py:269`; burada yetmez):
   `<veri dizini>/tools/embedding-job.json` işin başında `{"status": "running", "step", "started_at", "pid"}` ile
   yazılır, her adımda güncellenir, bitişte `succeeded` / `failed` / `cancelled` ve `finished_at` ile kapanır (her
   yazma geçici dosya + `os.replace`). **Sahiplik bir OS kilidiyle** (worker'ın tek sahiplik düzeni, `worker.py:3`,
   `:48`): kuran süreç `<veri dizini>/tools/embedding-install.lock`'u `fcntl.flock(LOCK_EX | LOCK_NB)` ile işin başından
   sonuna tutar ve dosya tanıtıcısını `uv` alt süreçlerine `pass_fds` ile geçirir; `flock` açık dosya tanımına bağlı
   olduğu için kilit, DEIXIS ölse bile son `uv` alt süreci bitene dek tutulu kalır. `EmbeddingService` başlarken ve her
   kurulum ya da kaldırma başında kilidi engellemeden almayı dener: alamazsa başka bir süreç (ya da ondan kalan bir
   `uv`) hâlâ yazıyordur — hiçbir şey silinmez, iş "running in another process" görünür, kurulum ve kaldırma 409.
   **Kurulumun kilit sırası:** (a) kurulum kilidini alır; (b) `removing` gibi yeni istekleri kapatır ve bu sürecin
   açık çalıştırıcısını kapatır (o anki isteği bitince; kendi paylaşımlı kilidi böylece bırakılır); (c) model
   kullanımda kilidinde `LOCK_EX | LOCK_NB` ister, alamazsa 409 `in_use_by_another_process`, iş başlamaz, istekler
   yeniden açılır; (d) dosya yazan adımları (ortam, paket, model dosyaları) özel kilit altında koşar; (e) `ready`
   denetiminden önce aynı tanıtıcıda `flock(LOCK_SH)` ile kilidi paylaşımlıya indirir ve denetim çalıştırıcısını bu
   tanıtıcıyı `pass_fds` ile vererek başlatır, çalıştırıcı paylaşımlı kilidi miras alır; (f) denetim bitince çalıştırıcı
   kapanır, `installed.json` yazılır, kilitler bırakılır, istekler açılır. `flock`'ta özelden paylaşımlıya geçiş atomik
   değildir, ama arada başka bir süreç özel kilidi alamaz: onu isteyen her yol (kurulum, kaldırma) önce kurulum
   kilidini ister ve o (a)'dan (f)'ye bu süreçtedir.
   Alabilirse ve iş dosyası `running` diyorsa iş yarıda kalmıştır. Silmeden önce model kullanımda kilidinde de
   `LOCK_EX | LOCK_NB` istenir: kurulum `ready` denetimindeyken ölen bir sürecin denetim çalıştırıcısı paylaşımlı kilidi
   hâlâ tutuyor olabilir (kurulum kilidini değil). Alınamazsa hiçbir şey silinmez, iş dosyasına dokunulmaz, kurulum
   kilidi bırakılır; toparlanma bir sonraki başlangıçta ya da kurulumda yeniden denenir. Alınırsa dosya `failed`,
   `output: "stopped when DEIXIS closed"` olur, `*.part` dosyaları ve `installed.json`'ı olmayan ortam silinir, sonra
   iki kilit bırakılır;
   `GET …/builtin` bu işi gösterir. PID yalnız gösterim içindir, karar kilitten çıkar. **İş dosyasını yalnız kurulum
   kilidinin sahibi yazar:** kuran süreç, ya da toparlanmada kilidi aldıktan sonra toparlayan süreç; başka hiçbir yol
   (`GET`, iptal, ikinci sunucu) ona yazmaz. **İptal:** `POST …/builtin/cancel` yalnız bu sürecin başlattığı ve hâlâ
   sahip olduğu işi durdurur (görevi ve `uv` alt sürecini iptal eder, iş dosyasını `cancelled` yazar, sonra kilidi
   bırakır); kurulum kilidi başka bir süreçteyse 409 `in_use_by_another_process`, iş dosyasına dokunulmaz; bu süreçte
   çalışan iş yoksa 409 `no_install_running`. **Model kullanımda kilidi (bütün süreçler için):**
   `<veri dizini>/tools/embedding-in-use.lock`. `LocalEmbedder` çalıştırıcıyı başlatmadan önce bu dosyada
   `fcntl.flock(LOCK_SH | LOCK_NB)` alır ve tanıtıcıyı `pass_fds` ile çalıştırıcıya geçirir; kilit çalıştırıcı
   yaşadıkça (DEIXIS ölse bile) tutulu kalır, süreç kapanınca bırakılır. Paylaşımlı kilidi alamazsa (biri özel kilitle
   kuruyor ya da siliyor) istek `builtin_unavailable` alır. Aynı veri dizinini kullanan ikinci bir DEIXIS sunucusu
   (`app.py:372`: işçi kilidini alamayan sunucu API'yi sunmaya devam eder) kendi çalıştırıcısında aynı paylaşımlı kilidi
   tutar. Her kurulumun başında da `*.part` silinir;
   manifesti tutan tam dosyalar yeniden indirilmez. **Kaldırma ile çalışan süreç:** `DELETE …/builtin` önce kurulum
   kilidini alır (alamazsa 409). Sonra, aynı olay döngüsü adımında ve hiçbir `await`'ten önce, `LocalEmbedder.removing =
   True` olur: bu andan sonra gelen her istek kilide ya da süreç başlatmaya hiç varmadan `builtin_unavailable` alır.
   Sonra `LocalEmbedder.close()` (o an süren bir istek bitene ya da `SECONDS_PER_BATCH_LIMIT` dolana dek bekler, süreci
   kapatır), sonra model kullanımda kilidinde `LOCK_EX | LOCK_NB` istenir: alınamazsa başka bir sürecin çalıştırıcısı
   modeli kullanıyordur, hiçbir şey silinmez, `removing` kalkar, kilitler bırakılır ve cevap 409
   `in_use_by_another_process` ("in use by another DEIXIS process"). Alınırsa `installed.json`, sonra ortam ve model
   dosyaları silinir. `removing`, kurulum kilidi ve kullanımda kilidinin özel tutuşu
   silme bitene dek sürer; ancak sonra `removing = False` olur ve kilit bırakılır (artık `installed.json` olmadığı için yeni istek
   yine `builtin_unavailable` alır). Bir koşunun sonraki partisi `builtin_unavailable` alır ve adım karar 5'e göre
   `partial` biter; silme sürerken hiçbir süreç başlamaz, yarım silinmiş dosyayı okuyan bir süreç olmaz. İş durumu
   (`step`, `steps`, indirilen bayt, çıktının son kısmı) `GET /api/semantic-search/builtin`'de; `POST …/builtin/install`
   (409 çalışırken), `POST …/builtin/cancel`, `DELETE …/builtin` (seçiliyken de silinebilir; o zaman karar 5). Yeniden
   denemek aynı düğme; tamamlanmış ve özeti tutan dosya yeniden indirilmez. Başarısız iş kişiye adımını ve çıktısını
   gösterir. Uygulama kendiliğinden indirmez, seçim kendiliğinden yerleşiğe geçmez (`chosen()` değişmez).
3. **Sağlayıcı soyutlamasına giriş.** `embeddings.PROVIDERS`'a `"builtin"` eklenir; `SemanticChoice.provider` aynı.
   `stored_model` yerleşik için `builtin:bge-small-en-v1.5@aa8f8b0:256` — revizyon ve jeton kesimi adın içinde, çünkü
   ikisinden biri değişirse vektörler başka bir modelin vektörüdür ve `source_similarities` / `passage_embeddings`
   anahtarı bunu ayırmalıdır. `Embedder.embed` yerleşikte `FlowDeps.local_embedder`'a gider; `task_type`
   `RETRIEVAL_QUERY` → `kind: "query"` (fastembed'in `query_embed`'i), öbürü `"document"`. `options()` yerleşiği Gemini'nin
   hemen ardından verir: `available`, "son tam sha256 denetimini geçti ve o günden beri dosyaların `(boyut, mtime_ns,
   inode)`'u değişmedi" demektir, "şu an doğrulandı" değil; cevap `last_full_check: {"at", "passed"}` taşır ve Ayarlar
   "Ready · files checked {time}" yazar. Güvenlik kapısı süreç başlangıcındaki tam denetimdir; o kapı düşerse önbellek
   `passed: false` olur ve `available` hemen `false` döner. Değilse neden
   ("Not downloaded", "Download failed", "Downloading", "Files do not match"). `create_app(..., local_embedder=None)` ve `FlowDeps.local_embedder`
   test için enjeksiyon noktasıdır; pytest gerçek süreci, `fastembed`'i ya da ağı hiç görmez (karar 11). Yerleşik hem
   kaynak benzerliğine (`sw` ve `legacy`) hem yanıtın ve tablo sütunlarının pasaj sıralamasına hizmet eder.
4. **Parti, döngü, duraklatma, kısmi sonuç; bütün sağlayıcılar.** `_source_similarity` ve `_semantic_ranking` metinleri
   partiler halinde gönderir (yerleşikte `LOCAL_BATCH = 64`, HTTP sağlayıcılarda mevcut `BATCH = 100`); **her partiden
   sonra** o partinin sonucunu aynı işlemde yazar (`save_source_similarities` / `save_passage_embeddings`) ve
   `_checkpoint`'i çağırır. Sorgu vektörü ilk partiden önce bir kez alınır (bugün sonda alınıyor; başta almak bir partinin
   boşa gitmesini önler). Kural iki yolda farklıdır. **Kaynaklar** (`_source_similarity`): saklı olan benzerliğin kendisi,
   bir skordur; eksik kaynak yoksa sorgu da gömülmez, model hiç çağrılmaz ve adım saklı benzerliklerle `succeeded`
   biter (karar 5), model kurulu olmasa bile. **Pasajlar** (`_semantic_ranking`, yanıt ve tablo sütunu): saklı olan
   yalnız pasaj vektörüdür, sıra için sorgu vektörü her zaman gerekir; bu yüzden sorgu her koşuda gömülür, bütün pasaj
   vektörleri saklı olsa da. Model kullanılamıyorsa (kurulu değil, süreç başlamıyor, sorgu isteği düşüyor) pasaj yolu
   bugünkü gibi sözcük sıralamasına düşer, adım `failed` ve nedeniyle (`builtin_unavailable` vb.) biter; saklı pasaj
   vektörleri durur. Sonuç: duraklatma ve iptal en çok bir parti gecikir (256 jetonda 64 kayıt ≈ 2,4 sn, sayı
   5); sürdürülen koşu yalnız eksik olanları gömer (mevcut `scored_sources` / `passage_embeddings` mantığı); bir parti
   başarısız olursa önceki partiler saklı kalır ve adım `partial` biter (`run_steps.status`'ta zaten var), çıktısında
   `{"model", "sources" | "passages", "embedded", "missing", "query_origin", "rate_limited_waits"}`. Sıralama kısmi
   kümeyi bugünkü kuralla okur (puanı olmayan kuyrukta, kurtarılamaz); `signals.embedding.available` kaç kaydın
   puanlandığını zaten söyler. Yerleşik 256 jetonda keser (`LOCAL_MAX_TOKENS = 256`, `local_embedding.py`'de, adın
   içinde): sayı 5'te süre yarıya indi, kurtarılan pozitifler ve beş sinyal ortancası aynı kaldı. HTTP sağlayıcılarının
   metin sınırı (`MAX_CHARS`) değişmez. Döngü: yerleşikte iş alt süreçte, DEIXIS yalnız boruya yazar ve okur; aynı
   bağlantıda veritabanı yazıları olay döngüsü iş parçacığında kalır, `await` hiçbir işlemin içinde değil.
   **Pasajlarda kısmi sonuç:** `_semantic_ranking`'te bir parti başarısız olursa, vektörü olan pasajlar (saklı + bu
   adımda gömülenler) benzerliğe göre sıralanıp döndürülür, vektörü olmayanlar anlamsal listede yer almaz ve yalnız
   sözcük sıralamasından gelir (`fuse_rankings` bir listede olmayan öğeyi öbüründeki yeriyle alır); adım `partial`.
   Hiç vektör yoksa bugünkü gibi `None` ve sözcük sıralaması. Yanıt ve tablo sütunu aynı kuralı kullanır.
4a. **Koşunun gömme modeli dondurulur.** Bir sağlayıcı seçiliyse ve (yerleşikte) sorgu metni varsa, keşif koşusu
   **her zaman** bir `source_similarity` adımı açar, eksik kaynak olmasa da (bugün `flow.py:1937-1938` eksik yoksa adım
   açmadan dönüyor; bu değişir). Adım açılırken `identity = {"provider", "stored_model"}` açılış çıktısına yazılır
   (`store.step(..., output=...)`, `store.py:695`). `finish_step` çıktıyı olduğu gibi değiştirdiği için
   (`store.py:760`), bu adımların her bitişi, başarı, `partial` ve `failed` dahil, tek bir yardımcıdan
   (`_finish_embedding_step`) geçer ve çıktıyı `son saklı çıktı | identity | sayılar` olarak yazar: önce adımın en son
   saklı çıktısını okur (açılış kimliği ve karar 8'in `waited_seconds` / `rate_limited_waits`'i orada), üstüne bu
   bitişin sayılarını koyar, kimliği en son yeniden yazar; karar 8'in saniyelik yazması da aynı birleştirmeyle yapılır
   (`set_step_output` de çıktıyı bütünüyle değiştirdiği için, `store.py:772`); hata ayrıntısı `error_json`'da,
   kimlik hiçbir bitişte silinmez. Duraklatmada adım bitmez, açılış çıktısı durur. Sürdürülen koşu `store.step` ile
   aynı adımı alır ve kimliği oradan okur, Ayarlar'dan değil. Dilimden önce açılmış, çıktısı `None` olan bir adım
   sürdürülürse kimlik bir kez güncel ayardan yazılır (`set_step_output`) ve adım çıktısında `identity_from:
   "resume"` işaretiyle kalır. `sw` keşif koşusunda `_ranking` `_embedding_model()` yerine bu adımın kimliğini okur
   (adım yoksa, yani sağlayıcı kapalıysa ya da yerleşikte cümle yoksa, `None`). Aynı yardımcı `_semantic_ranking`'in
   adımları için de geçerlidir. Ayar gömme
   sırasında değişirse bu koşu eski modelle biter, yeni seçim sonraki koşuda geçerlidir. Protokolün `signals` girdisi
   D79'daki gibi yapılandırılmış modeli söyler; ikisi farklıysa sıralama çıktısının `embedding_model`'i gerçekte okunanı
   söyler.
5. **Model yoksa ya da süreç ölürse adım yumuşak düşer.** Yerleşik seçili ama kurulu değil, özet tutmuyor, süreç
   başlamıyor, bir istek `READY_TIMEOUT` / `SECONDS_PER_BATCH_LIMIT` içinde cevap vermiyor ya da süreç ölüyor →
   `EmbeddingError`, adım `failed` (hiç parti yazılmadıysa) ya da `partial`, `error_code = "embedding_failed"`, hata
   metninde `builtin_unavailable` / `builtin_timeout` / `builtin_stopped`. Dört kod sinyali aynı sıralar, koşu duraklamaz
   ve durmaz (SW8.5, D79). İki durum ayrıdır: **yalnız dört sinyal** — o revizyon ve model için hiç saklı benzerlik
   yoksa (sıralama nedeni `no_stored_similarity`); **saklı beşinci sinyal** — varsa, sıralama onları okur ve eksik
   kayıtlar kuyrukta kalır. Karar 4a'nın adımı her koşuda açıldığı için bu ayrım adımdan okunur: model kurulu değilse
   adım eksik kaynak için `failed` ya da `partial` biter ama `from_store` sayısını taşır; eksik kaynak yoksa model hiç
   çağrılmaz ve adım `succeeded` biter (`embedded: 0`). **Saklı benzerlikler:** aynı revizyon ve aynı `stored_model`
   için daha önce yazılmış benzerlikler, model şimdi kurulu olmasa da okunur: `stored_model` revizyonu ve kesimi taşıdığı için bunlar aynı
   sabit modelin ölçümüdür, yeniden gömülse aynı çıkardı. Yeni gömme yapılmaz; sıralama çıktısı `from_store` ile kaç
   benzerliğin saklıdan, kaçının bu koşudan geldiğini ayrı sayar; Transcript "{n} similarities from an earlier run; the
   built-in model is not installed now" der. Kişi yerleşiği kaldırınca saklı vektörler silinmez (D29: "earlier vectors
   are kept"). Hiçbir durumda başka bir sağlayıcıya geçilmez (AGENTS.md "Never substitute"). Transcript'in
   mevcut "Similarity unavailable; ordered by search position" satırı yerleşik için "The built-in model was not
   available; the records were ordered without the embedding" olur, kısmide "{n} of {m} records scored".
6. **İngilizce cümle: ayrı tablo, revizyon başına bir kez yazılır.** Migration `0053_english_questions.sql`:
   `scope_english_questions (research_id, scope_revision, text, origin CHECK (origin IN ('user', 'question')),
   created_at, PRIMARY KEY (research_id, scope_revision))`. **Kural** (`workflow/english_question.py`,
   `embedding_query(store, scope)`): yerleşik için sorgu metni (a) soru `detect_language(question, language_hint) ==
   "en"` ise sorunun kendisi (`query_origin: "question"`), (b) değilse o revizyonun satırı (`"english_question"`), (c)
   ikisi de yoksa `None`: yerleşik kol o araştırmada kapalıdır, adım açılmaz, sıralama nedeni
   `english_question_missing`, pasaj sıralaması sözcükle kalır ve `semantic_retrieval` adımı `skipped` çıktısıyla
   (`{"reason": "english_question_missing"}`, durum `succeeded`) yazılır ki Transcript bunu söyleyebilsin. Gemini, OpenAI,
   Ollama ve LM Studio soruyu yazıldığı gibi alır; cümle onlara hiç gitmez. Tablo sütununun sorgu metni için de aynı dil
   kuralı: İngilizce değilse yerleşikte o sütun sözcükle sıralanır. **Yazma:** `PUT /api/researches/{id}/english-question`
   `{text, expected_version}` güncel revizyona yazar; revizyonda satır varsa 409, metin boşsa, 500 karakteri aşıyorsa ya da
   `detect_language(text, None) != "en"` ise 422. "Soru zaten İngilizce" düğmesi ayrı bir gövdeyle gelir
   (`{"use_question": true, "expected_version"}`): dil denetimi yapılmaz, sunucu güncel revizyonun sorusunu olduğu gibi
   `origin: 'question'` ile yazar (dil kuralının yanlış "başka dil" dediği hâl; istemci metin göndermez, böylece
   yalnız güncel sorunun aynısı yazılabilir). Her iki yazma araştırmanın `version`'ını artırır ve aynı işlemde
   `english_question_saved` olayını (`{"scope_revision", "origin"}`) yazar; kapsam revizyonu açılmaz. **Taşıma:** `revise_scope` yeni
   revizyonu yazarken soru metni aynıysa (yalnız anahtar terim ya da yönlendirme değiştiyse) satırı aynı işlemde yeni
   revizyona kopyalar; soru değiştiyse kopyalamaz. **Neden ayrı tablo:** kapsam revizyonları yazıldıktan sonra
   değişmez, ve cümleyi eklemek için yeni revizyon açmak bütün kararları eskitir (`decisions.py:152-155`). Tablo
   revizyonla anahtarlıdır (SW8.6 "stored with the scope revision"), bir kez yazılır; bir revizyonun benzerlikleri hep aynı
   sorgu metniyle hesaplanır, çünkü cümle yazılmadan yerleşik hiç gömmez, yazıldıktan sonra değişmez. **Zamanlama:**
   cümle keşif koşusunun sıralamasından sonra yazılırsa o koşunun sıralaması gömmesizdir (nedeni kayıtlı); aynı
   revizyonun sonraki keşif koşusu ya da yanıt koşusu cümleyi kullanır. **Eski araştırmalar:** satır yok; soru
   İngilizceyse hiçbir şey değişmez; değilse kol kapalıdır ve arayüz söyler. `legacy` de aynı kuralla çalışır.
   **Dil kuralının hataları, yazılı:** aksansız başka dilde soru İngilizce okunur ve yerleşik o soruyu gömer (SW8'in
   ölçümünde Türkçe soruda gömme tek başına ortanca 350'ye düştü, beş sinyal füzyonu 155–194 aralığında kaldı; bedel
   küçük ama sıfır değil); aksanlı özel adlarla dolu İngilizce soru "başka dil" okunabilir, çıkış yolu "Soru zaten
   İngilizce" düğmesi.
7. **Modelin çeviri önerisi bu dilimde yok** (A1, kabul edildi). Cümleyi kişi yazar. Öneri için bir model adımı
   gerekir: yeni sözleşme şeması, yöntem paketinde yeni bir dosya, `RUNTIME_FILES` girdisi, fikstürler ve
   `valid_response`; `skill_package_hash` değişir. Üstelik İngilizce olmayan `sw` sorusu bugün hiçbir model çağrısından
   önce `key_terms_needed` ile duruyor (`flow.py:648-653`), yani önerinin koşacağı bir koşu anı da yok; ya 08c'nin terim
   önerisi gibi duraklamış koşuya istek yazılıp koşu sürdürülür, ya da yeni bir koşu türü açılır. SW8.6 "may propose"
   diyor. A1'de `skill_package_hash` aynı kalır.
8. **HTTP 429'da sınırlı ve kesilebilir bekleme, bütün HTTP sağlayıcıları.** Partileri artık akış gönderir (karar 4);
   `Embedder.embed` tek partiyi alır ve adımın `RateBudget` nesnesini (`retries_left_for_batch`, `seconds_left`)
   ve bir `stop` çağrısını (akışın `_checkpoint`'i) parametre olarak alır, böylece 180 sn tavanı adımın bütün partileri
   arasında paylaşılır. **Bütçe kalıcıdır:** her bekleme dilimi bittiğinde (1 sn'de bir) gerçekten beklenen süre adım
   çıktısına işlenir (`waited_seconds`, `rate_limited_waits`; `set_step_output` ile, kimliğin yanına); duraklatmayla
   kesilen bir bekleme de o ana kadar beklenen saniyeyle kaydedilir, sonra `RunStopped`. Sürdürülen adım
   `seconds_left = EMBED_MAX_WAIT_SECONDS - waited_seconds` ile başlar. Parti başına deneme sayısı kalıcı değildir:
   sürdürülen koşu yarıda kalan partiyi baştan gönderir ve ona üç yeni deneme hakkı verir; toplam süreyi adımın kalıcı
   180 sn'si sınırlar. `embed` ve `embed_openai_compatible` 429 aldığında
   `Retry-After` başlığını (saniye), Gemini'de yoksa gövdedeki `RetryInfo.retryDelay`'i okur; ikisi de yoksa 10, 20, 40
   sn. Parti başına en çok `EMBED_RATE_LIMIT_RETRIES = 3` yeniden deneme, koşu adımı başına toplam bekleme en çok
   `EMBED_MAX_WAIT_SECONDS = 180`; bekleme `EMBED_MAX_WAIT_SECONDS`'ı aşacaksa beklenmez, adım o partide `partial` /
   `failed` biter (karar 4). Bekleme 1 sn'lik `asyncio.sleep` dilimleriyle yapılır ve her dilimden sonra `stop`
   çağrılır: duraklatma, iptal ya da yeni kapsam revizyonu en çok 1 sn içinde işlenir (bekleme yarıda kalır, parti
   gönderilmez, önceki partiler saklı). Her
   bekleme adım çıktısında sayılır (`rate_limited_waits`, `waited_seconds`) ve Transcript satırı "rate limited, waited
   {s} s" der (AGENTS.md: hız sınırları görünür kalır). Bekleme efora göre değişmez: D88'in `quick`'te beklememe kuralı
   sağlayıcı aramaları içindir ve gömme bir aramanın yerini tutmaz; üç deneme ve 180 sn tavanı adımın süresini
   sınırlar. Sabitler `embeddings.py`'de; ücretsiz katmanın gerçek sınırı ölçülmedi.
9. **Ayarlar → Semantic search.** Sıra (sunucu listesi ve arayüz aynı): **Gemini**, **This computer · built-in**,
   OpenAI, This computer · Ollama, This computer · LM Studio, **Off**. SW8.3 üç seçenek sayar (Gemini, yerleşik, kapalı)
   ve OpenAI / Ollama / LM Studio'nun "olduğu gibi kaldığını" söyler; sırayı dördüncü öğeler için belirtmez. Kapalı
   bugünkü gibi sonda kalır: bir sağlayıcı seçenekleri arasında "yok" seçeneğini ortaya koymak listeyi böler ve bugünkü
   Ayarlar da onu sonda gösteriyor. Bu bir sapmadır, aşağıda adıyla yazılı. Metinler (hepsi `i18n.ts` üzerinden, İngilizce
   anahtar):
   - Gemini, satırın altında: "Reads the question in any language. Needs a Google AI Studio key; a free key works."
     Anahtar yoksa: "Get a free key: sign in at aistudio.google.com/apikey, create a key, paste it under Cloud models →
     Gemini." (bağlantı `https://aistudio.google.com/apikey`). Gemini seçiliyken: "Passage text is sent to Google. If your
     key is on Google's free tier, Google may use the text you send to improve its products. DEIXIS cannot tell which
     tier your key is on." "Recommended" rozeti yok: SW8.3'ün önerisi tek konuya dayanıyor; metin nedenini (her dil,
     ücretsiz anahtar) söyler, üstünlük iddia etmez.
   - Yerleşik: "Runs on this computer. No key, no account. For semantic search, no text leaves the computer; the model
     you chose for the research steps still receives what it receives today. English only: a research whose question is
     not in English needs one English sentence." Durum: indirilmemiş (disk boyutu ve Download), iniyor (adım i / n,
     bayt), hazır, başarısız (adım ve çıktı, Try again), kaldır. Süre cümlesi yalnız ölçülen sayıyla ve ölçüldüğü
     makineyle: "Measured on one Apple M1 Pro: 1,369 records took 51 seconds, 6,696 records about 4 minutes. Other
     computers were not measured."
   - Off ve öbürleri bugünkü gibi.
10. **Kişinin yüklediği PDF'in metni Google'a gitmeden önce.** `research_view` yeni bir `semantic` alanı verir:
    `{"provider", "stored_model", "arm": "on" | "off" | "english_question_missing" | "not_installed",
    "english_question": {"text", "origin"} | null, "needs_english_question": bool}`. Düğmeye basıldığı anda hangi
    pasajların gönderileceği bilinemez: yanıt koşusu önce `_inspect` ile yeni PDF metni edinebilir (`flow.py:2342-2350`),
    sonra dahil işlerin bütün pasajlarını gömer (`:3944-3949`). Bu yüzden uyarı bir sayı vaat etmez. Sağlayıcı Gemini
    iken yanıt isteme ve tablo doldurma düğmelerinin altında, dahil işlerden herhangi birinde `origin = 'user_upload'`
    varlık olsun olmasın, her zaman aynı koşullu satır: "If the included sources have PDFs you uploaded, their text is
    sent to Google to rank passages. On Google's free tier, Google may use it to improve its products." (OpenAI'da aynı
    satır OpenAI der, ücretsiz katman cümlesi olmadan.) Engelleyen pencere yok. Gerçekte ne gittiği gönderimden sonra
    kayıtlıdır: `_semantic_ranking`'in adım çıktısı `uploaded_files_sent` ve `uploaded_passages_sent` sayar (bu adımda
    sağlayıcıya giden, `user_upload` varlığından gelen pasajlar), Transcript "Text of {n} uploaded PDF(s) was sent to
    Google" der.
11. **Araştırma görünümü, Transcript, protokol.** `semantic.arm == "english_question_missing"` iken Kaynaklar sekmesinin
    başında tek satırlık bir uyarı ve satır içi form: "The built-in semantic model reads English only. This question is
    not in English, so the built-in model is off for this research. Add one English sentence that says what you are
    looking for." Alan, Kaydet, ve "The question is already in English". Kaydedilince uyarı "Built-in model uses: {text}"
    satırına döner. Sıralama nedeni `english_question_missing` → "no English sentence for the built-in model"
    (`labels.ts` `signalReasons`). Transcript `embeddingOf` `builtin`'i tanır, simgesi dizüstü, adı
    "This computer · built-in". **Protokol gövdesi değişmez:** `signals`'ın gömme girdisindeki `model` yerleşikte
    `builtin:bge-small-en-v1.5@aa8f8b0:256` olur, başka alan eklenmez; sorgu metninin kökeni ve özeti adım çıktısında
    (`query_origin`, `query_sha256`). Böylece mevcut yapılandırmaların protokol özeti aynı kalır.
12. **Kanıt sözcükleri.** Benzerlik yalnız sıra verir; hiçbir metin "relevant", "better", "recommended because more
    accurate" demez. Yerleşik için "private" değil "for semantic search, no text leaves the computer" (indirme hariç,
    bir kez, Hugging Face'ten); cümle yalnız gömmeyi kapsar, araştırmanın bulut modellerine bir söz vermez. Boyut "disk",
    süre "measured on one Apple M1 Pro" diye yazılır.
    Kurulum ve indirme adımları ayrı durumlar: "downloaded", "checked", "ready" birbirinin yerine kullanılmaz (AGENTS.md:
    kurulu, yapılandırılmış ve çalışmış ayrı durumlardır). Ücretsiz katman cümlesi "may" der ve DEIXIS'in katmanı
    bilmediğini söyler.

## SW8'den sapmalar

Bu plan aşağıdaki yerlerde SW8'in metninden bilinçli olarak ayrılır; bu dilim için plan geçerlidir (`docs/README.md`'nin
"review's text holds" önceliği bu maddelerde uygulanmaz), D103 bunları adıyla taşır:

1. **Kapalı sonda** (SW8.3 onu üçüncü sayar): karar 9.
2. **"Recommended" rozeti yok** (SW8.3 Gemini'yi önerilen diye anar): karar 9; metin nedeni söyler.
3. **Modelin çeviri önerisi yok** (SW8.6 "may propose"): karar 7, A1.
4. **Yerleşik 256 jetonda keser** (SW8 ölçümü 2.000 karakterlik metinle, 512 jetonla yapıldı): karar 4, sayı 5.
5. **"About 130 MB" yerine ölçülen boyut** (67 MB model, yaklaşık 145 MB kurulu ortam): karar 2.
6. **Ücretsiz katman uyarısı her Gemini kullanımında, koşullu** (SW8.4 "where a free-tier key is in use"; katman
   anahtardan anlaşılamıyor) ve yüklenen PDF uyarısı sayı vermeden, koşullu (SW8.4 "before a user-uploaded PDF's text is
   embedded"; gönderilecek küme düğme anında bilinmiyor): karar 9, 10.

## Sahip kararları (25 Eylül 2026: A1, B1, C1 önerildiği gibi)

Sahip soru sorulmadan ilerlenmesini istedi; eşgüdümcü üç öneriyi kabul etti ve satır 21'e yazdı. Seçenekler kayıt için
aşağıda duruyor.

- **A — İngilizce cümleyi model önersin mi?** Öneri **A1**: bu dilimde hayır; kişi yazar, "soru zaten İngilizce" düğmesi
  var (karar 6, 7). Bedel: İngilizce olmayan soruyla yerleşiği seçen kişi bir cümle yazmak zorunda. *A2*: yeni bir
  model adımı (`english_question`), kişi araştırma görünümündeki düğmeyle ister, model bir kez önerir, kişi düzeltip
  kaydeder; yeni şema, yöntem dosyası, fikstürler, `skill_package_hash` değişir, bir de koşu anı tasarlanmalı (08c'nin
  isteği gibi). Önerilmez: SW8.6 "may" diyor, anahtar terimleri zaten kişi yazıyor.
- **B — Yerleşik model nerede koşsun?** Öneri **B1**: D52 gibi ayrı, istekle kurulan ortam ve alt süreç (karar 1).
  *B2*: `fastembed` DEIXIS'in kendi bağımlılığı olur (`pyproject.toml` + `uv.lock`, 18 yeni paket, her kuruluma 145
  MB), gömme `asyncio.to_thread` ile 64'lük partilerde koşar; indirme yalnız model dosyalarıdır (67 MB), kod daha az,
  ama bellek uygulama ömrünce tutulur (256 jetonda 1,2 GB) ve her kullanıcı `onnxruntime`'ı taşır. Sayı 6'ya göre ikisi de
  olay döngüsünü kilitlemez.
- **C — Havuzun tamamı gömülsün mü?** Yerleşik, keşif koşusunda sıralamadan önce bütün havuzu gömer (D79). Bu, koşuya
  en büyük saklı havuzda yaklaşık 4 dakika (251 sn) ekler (256 jetonda, bu makinede), D88'in 10 / 15 / 20 dakika hedefine
  karşı. Öneri **C1**: tamamı gömülür, Ayarlar süreyi söyler (karar 9); kurtarma kolu kod sırasının ilk 200'ü dışındaki
  kayıtları arar, bir tavan tam o kayıtları keser. *C2*: efora göre bir tavan (ör. kod sırasının ilk 1.000 / 2.000 /
  3.000 kaydı gömülür, gerisi kuyrukta); süre sınırlanır, ama D79'un "bütün havuz" kararı değişir ve tavanın ötesindeki
  kayıt kurtarılamaz; SW7 havuzunda kurtarılan iki pozitif kod sırasında 623. ve 414. idi. *C3*: gömme ilk arama turundan
  hemen sonra arka planda başlar, genişleme turu ve ikinci kaynak sorgularıyla üst üste koşar; süre kazancı en büyük ama
  17a'nın üst üste binme kuralları gibi ayrı ve tam incelenen bir dilim ister.

## Global constraints

- **Anahtarsız, ağsız çalışma.** Yerleşik indirmeden sonra ağa hiç gitmez; indirme yalnız onayla ve yalnız sabit
  revizyonlu adrese. Hiçbir dosya depoya, `~/.cache`'e (`uv` ve Hugging Face önbellekleri dahil), `uv`'nin kullanıcı
  Python dizinine ya da veri dizininin dışına yazılmaz (karar 2).
- **Gömmenin yetkisi yok** (SW8.2, SW8.5). Kayıt silmez, dahil etmez, eşik değildir; kapalı, eksik, kısmi ya da
  başarısızken dört kod sinyali aynı sıralar; koşu gömme yüzünden ne durur ne duraklar.
- **Başka sağlayıcıya sessiz geçiş yok.** Seçili sağlayıcı çalışmazsa adım başarısız ya da kısmi kaydedilir.
- **Model sözleşmesi değişmez** (A1'de): `skill_package_hash`
  `sha256:7d4e238c3e9feebd451c77fb997aff717a3617008bd4165be56f9fba46bf6fca`, şemalar, yöntem paketi, fikstürler aynı.
  Protokol gövdesinin biçimi aynı (karar 11). Neden kodu tablosu aynı.
- **Tek migration:** `0053_english_questions.sql`. Eski migration düzenlenmez.
- **`uv.lock` değişmez** (B1'de). DEIXIS süreci `fastembed`, `onnxruntime` ya da `numpy`'yi hiç içe aktarmaz.
- **Konuya özgü hiçbir şey yok;** dil kuralı mevcut `detect_language`'dir.
- **Kanıt sözcükleri** karar 12'deki gibi.

## Task taslağı

1. **Model dosyaları ve indirme** (`documents/local_embedding.py`; karar 2). Sabitler: depo, revizyon, beş dosyanın adı,
   baytı ve sha256'sı, `RUNTIME_BYTES_ESTIMATE`, `LOCAL_BATCH`, `LOCAL_MAX_TOKENS`, `LOCAL_IDLE_SECONDS`. `download_model(
   client, target)`: `.part` → özet → taşı. Testler (`httpx.MockTransport`, küçük sahte dosyalar ve monkeypatch'li
   sabitler): doğru dosya iner ve yerine geçer; bir bayt farklı dosya `.part` ile birlikte silinir ve iş `failed`; zaten
   tutan dosya yeniden istenmez; yönlendirme izlenir; veri dizini dışına yazılmaz; iş iptal edilince `.part` kalmaz;
   önceki bir çökmeden kalan `.part` servis başlarken silinir; `installed.json`'ı olmayan ortam kurulu sayılmaz ve
   yeniden kurulur; beş dosyadan yalnız `tokenizer.json` eksik ya da bir baytı farklıyken `options()`, `GET …/builtin`
   ve çalıştırıcının `ready`'si aynı sonucu (kullanılamaz) verir.
2. **Çalıştırıcı ve alt süreç** (`documents/embedding_runner.py`, `LocalEmbedder`; karar 1, 5). Testler, gerçek
   `fastembed` yerine `sys.executable` ile koşan sahte bir çalıştırıcı betiğiyle (aynı protokol, sözcükten türeyen
   vektörler): `ready` satırı; sıra ve boyut korunur; boşta kapanır ve sonraki istekte yeniden başlar; ölen süreç
   `builtin_stopped`; cevap vermeyen süreç `builtin_timeout` ve öldürülür; özet tutmayan model `ready` yerine hata;
   yanlış kimlikli, eksik vektörlü, 383 boyutlu ya da `NaN` taşıyan cevap `builtin_bad_reply` ve süreç kapanır; DEIXIS
   sürecinde `fastembed` / `onnxruntime` / `numpy` `sys.modules`'ta yok. Gerçek çalıştırıcı yalnız kabulde (task 9) koşar.
3. **Kurulum servisi ve uç noktalar** (`EmbeddingService`, `GET/POST/DELETE /api/semantic-search/builtin…`; karar 2).
   Testler (`EquationService` testlerinin deseniyle, sahte `uv` betiği): dört adım sırayla, çalışırken ikinci kurulum 409,
   iptal, kaldırma, başarısız adımın çıktısı, CSRF ve Host denetimi; sahte `uv` betiği aldığı ortamı yazar ve test
   `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` ve `HF_HOME`'un veri dizininin altında olduğunu doğrular; `running` diyen,
   başka `pid`'li bir iş dosyasıyla servis başlatılır → iş `failed`, "stopped when DEIXIS closed", `.part` ve yarım
   ortam silinmiş; aynı durumda kilit başka bir süreçte tutuluyken (test kilidi ayrı bir süreçte alır) hiçbir şey
   silinmez, iş "running in another process", kurulum ve kaldırma 409; çalışan bir gömme isteği sürerken `DELETE` →
   istek biter, `removing` sürerken gelen yeni istek süreç başlatmadan `builtin_unavailable` alır, sonra dosyalar
   silinir, sonraki parti `builtin_unavailable`; kurulum sürerken `DELETE` 409; aynı boyut, `mtime_ns` ve inode'la
   değiştirilmiş model dosyası `options()`'ta son denetimin sonucuyla (`available: true`, `last_full_check.at` eski)
   görünür, süreç başlangıcındaki tam denetimde `ready` yerine hata verir, adım karar 5'e göre düşer ve bundan sonra
   `available: false` olur; **iki süreç:** ayrı bir süreç sahte çalıştırıcıyı başlatıp kullanımda kilidini paylaşımlı
   tutarken bu süreçte `DELETE` → 409 `in_use_by_another_process`, hiçbir dosya silinmez, `removing` kalkar; aynı
   durumda kurulum 409; öbür süreç kapanınca `DELETE` başarır; kaldırma sürerken (özel kilit tutulu) öbür süreçte gelen
   istek `builtin_unavailable`; **iptal:** kurulum kilidi başka süreçteyken `cancel` 409 `in_use_by_another_process` ve
   iş dosyası bayt bayt aynı; bu süreçte iş yokken 409 `no_install_running`; kendi işini iptal eden süreç iş dosyasını
   `cancelled` yazar ve kilidi bırakır; **Windows:** `os.name` monkeypatch'le `"nt"` → `options()` yerleşiği
   `unsupported_platform` ile verir, kurulum 409 `unsupported_platform`, `GET …/builtin` 200 `unsupported_platform`, `cancel` ve `DELETE` 409 `unsupported_platform`,
   hiçbir kilit dosyası açılmaz; **kurulum ve açık çalıştırıcı:** bu süreçte çalıştırıcı açıkken (bir istek sürerken)
   kurulum başlar → istek biter, çalıştırıcı kapanır, sonra özel kilit alınır, kurulum sürerken gelen istek
   `builtin_unavailable`; **kurulum altında `ready`:** dosya adımlarından sonra kilit paylaşımlıya iner, denetim
   çalıştırıcısı başlar ve `ready` verir (bu sırada başka süreçte `DELETE` ve kurulum 409), kurulum `succeeded`,
   `installed.json` yazılır; **toparlanma ve `ready`:** ayrı bir süreç kurulumu başlatır, `ready` denetimi sürerken
   (denetim çalıştırıcısı paylaşımlı kilidi tutarken) ana süreç öldürülür, bu süreçte servis başlatılır → kurulum kilidi
   alınır ama kullanımda kilidi alınamaz, hiçbir dosya silinmez, iş dosyası aynı; denetim çalıştırıcısı çıkınca bir
   sonraki başlangıç toparlar (`failed`, yarım ortam silinir); **bütün pasaj vektörleri saklı:** model kuruluyken yanıt
   koşusu yalnız sorguyu gömer (sahte gömücüye tek çağrı), anlamsal sıra saklı vektörlerle kurulur, adım `succeeded`;
   model kurulu değilken sorgu gömülemez, pasajlar sözcükle sıralanır, adım `failed` `builtin_unavailable`, saklı
   vektörler silinmez; tablo sütunu aynı; **kaynaklarda eksik yokken sorgu gömülmez:** model kurulu değilken bütün havuzu saklı bir revizyonda
   yeni keşif koşusu → sahte gömücüye hiçbir çağrı yok (sorgu dahil), adım `succeeded`.
4. **Sağlayıcı** (`embeddings.py`, `app.py`; karar 3, 9). Testler: `options()` sırası Gemini, yerleşik, OpenAI, Ollama,
   LM Studio, kapalı; yerleşik kurulu değilken `available: false` ve neden, `PUT` 422 ile reddeder; kurulunca kaydedilir;
   `stored_model` revizyonu ve kesimi taşır; `chosen()` yerleşiği kendiliğinden seçmez.
5. **Parti, kısmi sonuç, duraklatma, 429** (`flow.py` `_source_similarity`, `_semantic_ranking`, `embeddings.py`; karar
   4, 5, 8). Testler, Gemini sahte uç noktası ve sahte yerel gömücüyle: üçüncü partide hata → ilk iki partinin
   benzerlikleri saklı, adım `partial`, sıralama puanlananları sıralar ve dört kod sinyali gömmesiz koşuyla aynı;
   ikinci partiden sonra duraklatma istenir → koşu o partiden sonra durur, sürdürülünce yalnız eksikler gömülür ve
   toplam çağrı sayısı tek seferlik koşuyla aynı; 429 `Retry-After: 2` → bekler (saat monkeypatch'li), aynı partiyi
   yeniden gönderir, `rate_limited_waits: 1`; `Retry-After` tavandan büyükse beklemez; Gemini gövdesindeki
   `retryDelay` okunur; üç 429 sonra adım `partial`; yerleşik kurulu değil → `failed`, `builtin_unavailable`, dört sinyal
   aynı, koşu `completed`; yerleşik seçiliyken hiçbir istek Gemini'ye gitmez; **kesilebilir bekleme:** `Retry-After: 60`
   beklenirken duraklatma istenir → koşu 1 sn içinde durur, parti gönderilmez; aynı durumda yeni kapsam revizyonu →
   koşu `scope_revised` ile iptal; **paylaşılan bütçe:** iki ayrı partide 100'er saniyelik 429 → ikincisi tavanı aşacağı
   için beklenmez, adım `partial`; **model dondurma:** gömme sırasında (ikinci partiden sonra) Ayarlar Gemini'den
   yerleşiğe ve kapalıya çevrilir → koşu Gemini ile biter, sıralama Gemini benzerliklerini okur, `embedding_model`
   Gemini; sürdürülen koşu da; **saklı benzerlik:** yerleşikle bir koşu, sonra yerleşik kaldırılır, aynı revizyonda yeni
   keşif koşusu → yeni gömme yok, sıralama saklı benzerlikleri okur, `from_store` havuz kadar, yeni kayıtlar kuyrukta;
   **eksik yokken adım:** bütün havuz saklıyken yeni keşif koşusu yine `source_similarity` adımını açar, model
   çağrılmaz, `embedded: 0`, `from_store` havuz kadar, sıralama beşinci sinyali okur; model kurulu değilken aynısı;
   **kimlik korunur:** adım `succeeded`, `partial` ve `failed` biter → üçünde de çıktıda `provider` ve `stored_model`
   var; duraklatılıp Ayarlar değiştirilip sürdürülen koşu açılış kimliğiyle biter; çıktısı `None` olan eski adım
   sürdürülünce `identity_from: "resume"`; **kalıcı bütçe:** 120 sn'lik 429 beklemesinin 50. saniyesinde duraklatma →
   çıktıda `waited_seconds` 50, sürdürülünce kalan 130 sn, ardından 150 sn'lik `Retry-After` beklenmez ve adım
   `partial` ve bitiş çıktısında `waited_seconds` 50 + beklenen, kimlik ile birlikte; `failed` biten ve 429 beklemesi
   olmuş bir adımın çıktısında da `waited_seconds` ve kimlik durur; **pasaj kısmi:** `_semantic_ranking`'te ikinci parti düşer → dönen liste yalnız vektörü olan pasajlar, adım
   `partial`, yanıt girdisi sözcük + kısmi anlamsal füzyonla; tablo sütunu aynı; sürdürülen yanıt koşusu yalnız eksik
   pasajları gömer. Mevcut D79 testi
   (`test_the_four_code_signals_rank_the_same_with_the_embedding_off_failing_or_on`) değişmeden geçer.
6. **İngilizce cümle** (`0053`, `workflow/english_question.py`, `store.py`, uç nokta, `views.py`; karar 6, 10, 11).
   Testler: İngilizce soru → sorgu sorunun kendisi, satır yazılmaz; Türkçe aksanlı soru, satır yok → yerleşik adım
   açılmaz, sıralama nedeni `english_question_missing`, `semantic_retrieval` `skipped`; cümle yazılınca sonraki keşif
   koşusu onu gömer (`query_origin: "english_question"`, `query_sha256`); aynı revizyona ikinci yazma 409; Türkçe cümle
   422; "soru zaten İngilizce" (`use_question: true`) dil denetimine takılmadan güncel sorunun aynısını
   `origin: 'question'` ile yazar (algılayıcının "başka dil" dediği aksanlı özel adlı İngilizce bir soruyla), istemci
   metni kabul edilmez; iki yazma da `version`'ı artırır ve `english_question_saved` olayını yazar; `expected_version`
   eskiyse 409; anahtar terim revizyonunda soru aynı
   → satır kopyalanır, soru değişti → kopyalanmaz; cümle yazmak hiçbir kararı eskitmez (`staleness_key` aynı) ve
   revizyon açmaz; Gemini seçiliyken cümle gönderilmez, soru olduğu gibi gider; `legacy` araştırmada da aynı kural;
   tablo sütunu Türkçe metinle yerleşikte sözcükle sıralanır; migration eski kütüphanede satırsız açılır.
7. **Görünüm ve uyarılar** (`views.py`; karar 10, 11). Testler: `semantic` alanının her `arm` değeri;
   uyarı satırının koşulu yalnız sağlayıcıdır (Gemini / OpenAI), bir sayı taşımaz; yanıt koşusu `_inspect`'te yeni bir
   `user_upload` metni edinir ve onu gömerse adım çıktısının `uploaded_files_sent` / `uploaded_passages_sent`'i onu sayar,
   önceden gömülmüş pasajlar sayılmaz; protokol gövdesi sentetik bir `sw` akışında yerleşik dışı sağlayıcılarla dilimden önceki özeti
   verir, yerleşikle yalnız `model` alanı farklı.
8. **Arayüz** (karar 9–11). `.impeccable.md` önce. `Connections.tsx` yerleşik satırı, indirme onayı ve ilerleme, Gemini
   anahtar yolu ve uyarı; `ResearchView.tsx` Kaynaklar sekmesindeki satır ve form, yanıt ve tablo düğmesinin altındaki
   PDF satırı; `Transcript.tsx` yerleşik adı ve kısmi / bekleme / yok satırları; `labels.ts` yeni neden. Playwright:
   yeni **N** (`builtin-embedding.spec.ts`), fikstür sunucusu `DEIXIS_FIXTURE_BUILTIN_EMBEDDING=fake` ile sahte kurulum ve
   sahte gömücü: Ayarlar sırası; Download onayı boyutu gösterir, ilerleme, hazır, seçip kaydetme; Gemini'nin anahtar
   yolu metni ve seçiliyken ücretsiz katman cümlesi; Türkçe soruyla araştırmada uyarı ve form, kaydedince satır değişir;
   Gemini seçiliyken yüklenmiş PDF'i olan dahil işte yanıt düğmesinin altındaki satır. Mevcut A–M senaryoları
   değişmeden geçer. Ekran görüntüsüyle masaüstü ve telefon genişliğinde.
9. **Kabul** (`.local/sw-slice21-acceptance-<tarih>/`; model yok; ağ yalnız (a)'daki bir indirme). (a) Ürünün kurulum
   işiyle oturum dizinindeki bir `DEIXIS_DATA_DIR`'e gerçek kurulum: dört adım, beş dosyanın baytı ve özeti sabitlerle
   aynı, `~/.cache/huggingface`'te, `~/.cache/uv`'de, `~/.local/share/uv/python`'da ve veri dizini dışında kurulum anından
   yeni ya da değişmiş dosya yok (öncesi / sonrası dosya listesi ve mtime), süre yazılır; kurulumu model indirmesinin
   ortasında süreci öldürerek kes, uygulamayı yeniden başlat: `.part` kalmamış, iş `failed`, yeniden kurulum tam
   dosyaları indirmeden bitirir. (b) Gerçek
   çalıştırıcıyla SW7 havuzunun metinleri ve en büyük saklı havuzun göç ettirilmiş kopyası `_source_similarity`
   üzerinden: süre, planın sayı 5'iyle karşılaştırılır (±%30; aşarsa nedeni yazılır); gömme sürerken `GET /api/health`
   gecikmesi (1 sn'de bir, yüzde 95 ve en çok); sürecin en yüksek belleği. (c) Planın iki saklı kütüphanesinin (17a
   `standard` kuantum ve bir paket boyutu araştırması) göç ettirilmiş kopyalarında keşif koşusunun sıralamasını yerleşik
   benzerlikle yeniden kur (model ve ağ yok; sıralama adımı yeni bir koşuda): dört kod sinyalinin satırları gömmesiz
   sıralamayla bayt bayt aynı, `signals.embedding.available` havuz kadar, kurtarılan kayıtların listesi ve sayısı
   yazılır (bir iyilik iddiası değil). (d) Aynı kopyada gömmenin ortasında duraklat, sürdür: yalnız eksikler gömülür,
   toplam = havuz. (e) Türkçe soruyla sentetik bir araştırmada cümle yazılmadan ve yazıldıktan sonra iki keşif koşusu:
   ilkinde neden `english_question_missing`, ikincisinde gömme koştu.
10. **Kapanış.** D103 (A, B, C'nin sahip cevabıyla). Limits: tek bilgisayar, tek konu; 256 jeton kesimi tek havuzda
    seçildi; pasaj düzeyinde yerel model ölçülmedi; ücretsiz katmanın hız sınırı ve 429 davranışı canlı ölçülmedi,
    bekleme sabitleri elle seçildi; saklı hiçbir araştırmada gömme koşmamıştı; dil kuralının iki hatası; kolun kapatma
    kuralı (SW8.7) açık. `search-workflow-review-2026-09-18.md`'de SW8'in durum satırı (3, 4, 6 kuruldu, A'ya göre 6'nın
    öneri kısmı; kısmi sonuç ve 429 kapandı). `sw-status.md` satır 21.

## Kabul koşulları

- Pytest tam koşu: bilinen tek hata (`test_extraction_is_stopped_when_it_exceeds_the_memory_limit`) ayrı, kalan tam koşu
  geçti; mevcut testler değişmeden geçer; hiçbir test ağa, gerçek `uv`'ye ya da `fastembed`'e gitmez; build temiz; lint
  uyarı sayısı 17'yi aşmaz; Playwright A–N geçer.
- Task 9'un (a)–(e)'si yazılı; (c)'de dört kod sinyali aynı.
- `skill_package_hash` aynı (A1); en yüksek migration `0053`; `uv.lock` aynı (B1); protokol gövdesi yerleşik dışı
  sağlayıcılarla aynı.

## Bu dilimde yok

- Modelin İngilizce cümle önerisi (A2).
- Çok dilli yerel model (SW8.6: ölçülen küçükler zayıftı, büyükleri 2,2 GB ve ölçülmedi).
- Gömmenin keşif aramalarıyla üst üste koşması (C3).
- SW8.7'nin kolu kapatma kuralı; kolun katkı raporu D101'de.
- Ücretsiz katmanın anahtardan anlaşılması; DEIXIS bunu bilmiyor ve metin öyle söylüyor.
- GPU / Core ML sağlayıcısı; `onnxruntime` CPU'da koşar.
- Anahtar terim formuna ve ana ekrana İngilizce cümle alanı (cümle araştırma görünümünden yazılır, anahtar terim
  revizyonunda taşınır).
- Tauri paketi (P10).
- Windows'ta yerleşik model (karar 1: `unsupported_platform`); kilit düzeninin `msvcrt` karşılığı ayrı iş.

## Ölçülmedi

Pasaj düzeyinde yerel modelin erişim kalitesi (SW8.4'ün yanıt adımı iddiası bir tasarım niyetidir). İkinci bir alan;
256 jeton kesimi yalnız SW7 havuzunda ve 20 pozitifle sınandı. Daha yavaş bilgisayarlar, Intel Mac, Windows. Gemini'nin
ücretsiz katmanında tam bir araştırma ve gerçek 429 davranışı: SW8'in Limits'i uygulama sırasında faturasız bir anahtarla
tam bir araştırma istiyor; bu dilimde koşulmazsa **açık kabul sınırı** olarak D103'e ve satır 21'e yazılır, 429
kuralı yalnız sahte uç noktayla sınanmış olur. İndirilen tekerlek baytları. Kişinin yazdığı İngilizce
cümlenin sorudan uzaklaşması ve bunun sıralamaya etkisi. Kişinin uyarıları okuyup okumadığı. Canlı hiçbir şey.
