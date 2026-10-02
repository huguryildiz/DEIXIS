# Görev: P9 H9, onaylandıktan sonra yeni korpusta tek gerçek-model rapor ölçümü

**Durum:** TASLAK, yürütme yetkisi yok. 3 Ekim 2026, hazırlama ağacı `/Users/huguryildiz/Documents/GitHub/DEIXIS-h9plan`, detached `a4deebfd511993335dda4992e6e39151f40e3644`. Bu yol ve commit gelecekteki ölçüm ağacı değildir. Onaylı ürün/dondurma commit'ine sabit ağacı ana oturum sağlar; yürütücü ağacı değiştirmez.

Önce `AGENTS.md`, `CLAUDE.md`, `docs/README.md`, `docs/layout.md`, `docs/product/p9-hardening-plan.md` §4 R01, §5 H9, §6, §7 H9 kuralları 1-7 ve §9 S2/S10'u oku. D124/D126/D128/D129/D141, üç `p6-slice1-report-expectations*.md` dosyası ve üç `p6-slice1-report-results*.md` kaydı bağlamdır; eski korpusları veya çiftleri kullanma. Hazırlık taslağı [p9-h9-freeze-draft.md](p9-h9-freeze-draft.md); yetki veren kayıt, bu taslağın yerini alan onaylı `docs/product/p9r-report-freeze.md` ve sahibin açık talimatıdır.

**Git durumunu değiştiren komut yok:** add, commit, stash, checkout, reset, branch, worktree, push yok. Ürün, yöntem, doğrulayıcı, şema, adapter, frontend, migration ve ölçüm kiti değişmez. Düzeltme yapma; bulguyu yaz. Başka worktree'ye, port 8765'e veya `~/Library/Application Support/DEIXIS` dizinine okuma dahil dokunma. Yalnız gelecekte K05'te ayrıca verilmiş açık sahip istisnası varsa canlı `codex-home` alt dizini Codex adapterı için kullanılabilir; bu taslak görevinde istisna yoktur. İstisna canlı kütüphaneye veya port 8765'e erişim vermez. Gerçek kütüphane yedeği alma. İzole yeni veri dizini ve boş ayrı port kullan; bilinmeyen port sahibini durdurma. Ham kanıt özel ve izlenmemiş kalır. Bu istem H10, lineage, kill-search veya edit ölçümünü yetkilendirmez.

## 1. Yalnız bütün başlangıç kapıları geçerse başla

1. Sahip K01-K12'yi açıkça kapatmış, H9 hazırlığını ve kapılardan sonra tek raporu yetkilendirmiş olmalı. Önerilen varsayılanlar veya bu dosyanın varlığı onay değildir. Sonnet dahil her gerçek çağrının kesin bağlantı/model/eforu ve bütçesi adlandırılmış olmalı.
2. H8 güncel kapanışı ve ilgili kabul kaydı ana oturumca doğrulanmış olmalı. Bu taslak ağacındaki D168 satırını tek başına kapanış yetkisi sayma. Gereken kapanış/inceleme eksikse `H9 başlamadı: <eksik kapı>` yaz, model veya sağlayıcı çağrısı yapma.
3. Konu, soru, seçim/dışlama, kuyruk kararını veren, yedi sütun, toplam hazırlık denemesi, bütçeler, K05 sunucu ortamı ve P19 tanımı/sorgusu/sayma kuralı/hash'i ilk keşiften önce belge commit'inde donmuş ve `gpt-6.1-sol` incelemesinden geçmiş olmalı. K02, Q1-Q3 yanında sahibin kendi alanından dışlama listesi dışındaki soruya da izin verir (plan S10). Tur sayısı ve son düzeltmelerin incelemesi kayıtlı olmalı. İnceleme kotası yoksa bekle; başka model koyma.
4. D129 kaynak yolu, ürün atalık/fark denetimi, kit hash'leri ve runtime `skill_package_hash` onaylı freeze ile eşleşmeli. Freeze taslağı §6 komutlarını onaylı değerlerle çalıştır; yerel test ortamı eksikse kurulum varsayma, eksikliği yaz. Test ve izole modelsiz sağlık sonuçlarını protokole geçir. Kişisel `.env` veya keychain'i kuru kontrol için yükleme.
5. Eski konu/korpus kimlik envanteri §2 kuralıyla yeterli olmalı; eksikliği sahibin kabul etmediği durumda dur. Canlı kütüphaneyi okuyarak tamamlama. Ölçüm klasörü/veri dizini yeni, boş ve gerçek yola çözümlenmiş olmalı; canlı dizine sembolik/sabit bağlantı olmamalı. Başka model işinin aynı kotayı tüketip tüketmediği belli değilse ana oturumdan bilgi bekle.

## 2. Hazırlık, en çok onaylı sayıda deneme

Gerçek sunucu başlamadan önce K05'in kesin sunucu ortamını `protocol.md`'ye yaz: `DEIXIS_DATA_DIR` yeni izole dizin, `DEIXIS_HOST=127.0.0.1`, `DEIXIS_PORT` boş ve 8765 dışında kesin port; `DEIXIS_CODEX_HOME` sahibin önceden hazırladığı ayrı, oturum açılmış home. Boş veri dizininin varsayılan `data_dir/codex-home` yolu giriş sağlamaz; P16 run 3'ün canlı home seçimini kopyalama. Canlı `codex-home` yalnız K05'teki ayrı açık sahip istisnasıyla kullanılabilir; credential kopyalama veya login başlatma yetkisi yoktur.

`config.py` ile doğrulanan ayarların hepsini açıkça yaz ve süreç ortamında ayarla: `DEIXIS_PROTOCOL_APPROVAL=ask`, `DEIXIS_FULLTEXT_FETCH=auto`, `DEIXIS_FULLTEXT_ADJUDICATION=auto`, `DEIXIS_CITATION_CHAINING=auto`, `DEIXIS_SEARCH_QUERY=model`, `DEIXIS_ARXIV_SOURCE=off`, `DEIXIS_QUERY_STRATEGY=legacy`, `DEIXIS_MODEL_CONCURRENCY=6`. Bunlar yalnız onayda kabul edilirse uygulanacak yükleme varsayılanlarıdır; onaylı alternatif değerler keşiften önce donar. `DEIXIS_CONTACT_EMAIL` ayarlı/ayarsız durumu ve Codex yürütülebilirini belirleyen kesin `PATH` de kaydedilir. Sağlayıcı anahtarları için ad, ayarlı/ayarsız durum ve kaynak (`environment` / `dotenv` / `keychain`) kaydı gerekir; değerleri yazma. Varsayılan sahipçe sağlanan süreç ortamıdır; kullanılan `OPENALEX_API_KEY`, `S2_API_KEY`, `NCBI_API_KEY`, `IEEE_API_KEY`, `SCOPUS_API_KEY`, `CORE_API_KEY`, `SERPAPI_API_KEY` ayrı belirtilir. Launcher eksik ortam değişkenlerini depo `.env` dosyasından, sonra anahtarları `DEIXIS` keychain servisinden yükler; bu kaynakları kullanmak K05'te açıkça adlandırılmalıdır. Codex girişi API anahtarı varlığından çıkarılmaz. Eksik/farklı ortamda başka home, anahtar veya model deneme.

Onaylı ölçüm ağacının kökünde kesin başlatma komutu aşağıdadır; protokolde port ve yollar yer tutucu olmadan kaydedilir. Bunu yalnız başlangıç kapıları geçtikten sonra çalıştır; modelsiz §6.2 sağlık bloğunu gerçek sunucunun başlangıç kaydı sayma:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend:. .venv/bin/python -m deixis serve \
  --port "$DEIXIS_PORT" --no-browser
```

Onaylı soru ve sütunları kelimesi kelimesine kur. Yeni `sw` araştırması, onaylı keşif ayarları, üründeki mevcut seçim/kuyruk yolu. Otomatik dışlama, bekleyen PDF ve okuma derinliği ayrı kayıtlar olarak kalır. Freeze §1.2'deki sınırlı kuyruk incelemesinin gerekçelerini, karar vereni ve okuyan türünü sakla. K03 varsayılanında karar sahibindir; model kararına ayrıca açık onay verilmişse bu satırları ayrı say ve sonuçta D96/D101 uyarınca ürünün sakladığı "person"/insan etiketinin o satırlar için yanlış olduğunu yaz. İnsan doğrulaması veya kişinin doğruladığı probe kaydı deme. Yedi sütunun `text` seçimi, D124'ün ilk iki `choice` sütunundan farklıdır; gerekçesi freeze §1.3'te dondurulur.

Her denemede bulunan/tekil/taranan/dahil/incelenen sayıları, provider hataları, seçim nedenleri, değişen kaynak kümeleri ve model oturumları kaydedilir. Hazırlık defteri, rapor ve okur defterinden ayrıdır. Sayaç keşif, tam metin okuma, doldurma, onarım ve yeniden gönderimlerin hepsini kapsar. Önerilen değerler yalnız onayda kabul edilmişse uygulanır: iki deneme birlikte 300 oturum/240 dk, her doldurma 60/60. İkinci deneme aynı veri dizininde yeni bir `sw` araştırmasıdır; aynı soru ve ayarlarla yürür, ilk denemenin kayıtları korunur. Sayaçları sıfırlamaz.

Başarısız satırın yerine kaynak koyma yalnız önceden donmuş sıralama ve kalan hazırlık hakkıyla yapılır. Hücre elle doldurulmaz, kaynak başarısızlığı silinmez. Hazırlıkta kota/yük duruşu o denemeyi bitirir; aynı denemeyi kota için sürdürme. Kalan deneme yalnız birleşik 300 oturum/240 dk içinde ve ana oturum bağlantının geri geldiğini tarihli kayda geçirdikten sonra kullanılabilir; beklerken saat durmaz. Hazırlık tavanı veya haklar dolarsa `korpus hazırlanamadı`, başlatılan rapor 0, okur yok, R1-R11 ve P19 `ölçülmedi: rapor başlamadı` kaydıyla kapan; rapor endpoint'ini deneme.

## 3. İlk rapor isteğinden önce ikinci kapı

1. Ürün `report_ready.ready=true`, 6-10 ayrı metinli eser ve yedi dolu etkin sütun göstermeli (sahibin onayladığı asgari sayı geçerlidir). `continue_with_failed` kullanılmaz. Korpus bağımsızlığı normalize DOI, sağlayıcı/eser kimliği, sürüm ilişkisi ve yüklenmiş dosya hash'iyle denetlenir; belirsiz kaynak/dimensions ayrı yazılır.
2. Kaynak kümesi, tablo kimliği, sıralı satır/sütun/güncel hücre revizyon/değer/kanıt hash'leri ve readiness yanıtını tarihli `protocol.md`'ye kaydet. Eski rapor/snapshot veya yabancı aktif koşu, `started` oturum bulunmadığını doğrula; kayıtları “temizlemek” için silme.
3. Yeni R9 çiftlerini freeze §4.4'ün değişmez kuralıyla Denklem sütunundan çıkar. `pairs.json` ve köken dosyası/hash'lerini hazırla; boşsa gerekçeyi yaz. D126/D128'in yedi çiftini kopyalama. Yeni çiftlerin ekleri ana oturumca nihai freeze belgesine ve belge commit'ine konmalı.
4. Nihai ürün, runtime hash, şema/yöntem manifesti, kit, okuyucular/tohumlar, bütçe ve durma kuralı ile korpus/tablo/R9 eklerini kapsayan `gpt-6.1-sol` incelemesi hazır demiş olmalı. Yürütücü Git komutu ile commit atmaz; ana oturumun kaydını bekler. Bu, ilk onayda belirtilmiş yürütme kapısıdır.
5. Nihai freeze commit'inde kaynak/fark/hash kuru kontrolünü yeniden çalıştır. Gözlemci hash'ini ve rapor yürütücüsünün döndüğünü kaydeden mekanizmayı doğrula; yalnız `running` sayısı veya health yeterli değildir. Onaylı tavanları ve sınırlı kapanış beklemesini gözlemciye aktar. Bu kayıtlar olmadan POST yapma.

## 4. Bir rapor koşusu, müdahalesiz

Tek `POST /api/researches/{research_id}/reports` gövdesi `{"table_id": "<yeni tablo kimliği>", "continue_with_failed": false}`. Gerçek run/report kimliklerini ve POST zamanını kaydet. `codex/gpt-5.6-luna/medium` yalnız onaylanan seçim buysa kullanılır. İstek reddedilirse bu seri içinde farklı yol/ayar deneme; 0 başlatılan rapor kaydı yap.

Her 15 s poll'da koşunun saklı adım/oturum hatalarını, bölüm doğrulamalarını ve `review.reason` alanını oku. D128'de `running` görünen koşunun IV adımı `failed` idi. Kök nedenler tamamen `client_timeout` ise, hak ve tavanlar varsa aynı koşuyu 10 dk sonra bir kez sürdür; başka/karışık hata, ikinci timeout, kota/yük, sayaç hatası, bütçe dolması veya model/araç ihlali ölçümü durdurur. Otomatik sınırlı schema/rate-limit yeniden gönderimlerini ayrı oturum say; dışarıdan kota resume'u yapma.

Durma nedeni saptanınca hâlâ çalışan koşuyu yalnız ölçümü sonlandırmak için kendi API'sinden iptal et; durmuş/terminal kaydı koru. Ürün, yöntem, şema, beklenti, hücre, kaynak, bölüm veya plan değişmez. Sonuç beğenilmedi diye ikinci rapor yok. Yürütücü dönüş kaydı ve sıfır `started` oturum birlikte doğrulanmadan nihai snapshot alma. 120 s kapanış gözlemi sonunda doğrulanamazsa nihai durum iddiası kurma; R1/R7/P19'u kayıt anındaki durum olarak yaz, kalan uçuşları listele. Uçuşta tavan aşılması varsa sayısını yaz.

## 5. Snapshot, okuma ve skor

Kit D124-D128'deki sürümde sabit kalır. `H9_BASE` yalnız izole sunucunun loopback URL'si, `H9_DATA` onun yeni veri dizini, `H9_EVIDENCE` izlenmeyen `.local/p9r-<tarih>/` klasörü; kimlikler bu koşunun gerçek kimlikleri olmalı. Aşağıdaki komutlar yalnız bu değerler dolu ve nihai kapı geçmişse çalışır:

```sh
PYTHONPATH=backend:. .venv/bin/python scripts/p6_eval/measure_report.py snapshot \
  --base "$H9_BASE" --research "$H9_RESEARCH_ID" --report "$H9_REPORT_ID" \
  --db "$H9_DATA/library.sqlite" --out "$H9_EVIDENCE/report" \
  --seed 20261003 --sample 30 --pairs "$H9_EVIDENCE/pairs.json"
```

Tohum onayda farklı seçildiyse ilk keşiften önce dondurulmuş değeri kullan; çıktıya bakarak değiştirme. Durmuş raporda aynı komuta `--stopped "$H9_STOP_REASON"` ekle; okur başlatmadan `score` çalıştır. Rapor hiç başlamadıysa bu komutları sahte report kimliğiyle çalıştırma; bütün R-satırlarına ve P19'a `ölçülmedi: rapor başlamadı` yaz.

P19 her başlatılan raporda a-e olarak yazılır. Freeze §4.2.1'in keşiften önce donmuş sorgusunu yalnız izole veride `mode=ro` ve `PRAGMA query_only=ON` ile uygula; sorgu/sayma kuralı/hash'i `protocol.md`'de, gerçek rapor kimliği ve çıktı hash'i sonuç kaydında olmalı. (a) İlk çıktısında `anchor_not_in_cell_evidence` olan `report_section` adımları; (b) `step_inputs.user_message` içinde `Cell anchor repair pairs:` taşıyan, oturumlu farklı onarım girdileri; (c) bunlardan doğrulaması `ok=true`, ilgili kodu kalmamış ve bölümü `valid` olanlar; (d) onarım sonrası aynı kodla hâlâ `failed` bölümler, sayı ve kimlikleri; (e) onarımda çıkarılan ve bölümün `insufficient_evidence` kaydının `context` veya `reason` metninde tam `claim_key` ile görünür bırakılan iddialar, sayı ve kimlikleri. Oturumsuz `message_too_large`, `anchor_not_in_passage` ve diğer kodlar ayrı sayılır; diğer kodlar D129'un hücre çapa yönergesini almaz. Eksik doğrulama, ayrıştırılamayan çıktı ve uçuşta kalan deneme sıfır sayılmaz. Kit ve kit çıktıları değişmez; yarım raporda da sayılar ve bölüm listeleri korunur. Aralık/eşik veya oran yorumu yoktur. (c) D129'un nedensel etkisi değildir; çapa onarımı anlam desteği sağlamaz, R2 ayrı okunur. (e) saklı bölüm kaydının görünürlüğünü ölçer; mevcut Markdown dışa aktarımı her durumda gösterim garantisi vermez.

Tamamlanmış raporda önce onaylı ilk okur `review.md`'nin bütün zorunlu alanlarını doldurur. Sonra aşağıdaki sıra uygulanır:

```sh
PYTHONPATH=backend:. .venv/bin/python scripts/p6_eval/measure_report.py second \
  --out "$H9_EVIDENCE/report"
```

İkinci okura yalnız kör paket ver; ilk kararları, beklentileri ve kontrol listesini gösterme. Her sayfa için en çok 5 kontrol, seçme tohumu `20261003`, karıştırma tohumu `20261004`. İkinci okuma bittikten sonra:

```sh
PYTHONPATH=backend:. .venv/bin/python scripts/p6_eval/measure_report.py score \
  --out "$H9_EVIDENCE/report"
```

`--crossref` ve `--seeded` kullanma: yeni metadata ağı veya P15 yardımcı sonucu H9'un R10'ı değildir. R5/R11 ilk okumalarının tamlığını ayrıca denetle. Eksik/çift işaret veya okunamayan metin için kit ret yolunu aşma. Nested token toplamları kitte yoksa saklı oturumdan ayrı, salt okunur hesapla; eksik usage'ı sıfır sayma, kit çıktısını yeniden yazma. Her model okumasını kayıtlı değerlendirme diye etiketle.

## Dosyalar ve çıkış

Yürütme sonrası izinli ürün belgeleri: planın `docs/product/p9r-report-results.md` dosyası (yeni), nihai freeze belgesine yalnız tarihli gerçekleşmiş kayıt ekleri (donmuş kurallar değişmez), `docs/decisions.md` (K01-K12 ve sonuç kararı; yazım anında sonraki boş karar numarası), `docs/product/p9-acceptance-record.md` (R01 ve bilinen sınır için tek satır), `STATUS.md` (durum güncellemesi). Freeze §6.1 fark denetimi `docs/product/*.md` yanında `docs/decisions.md` ve `STATUS.md` yollarını da kesin izinli listeye alır; ürün sabitlemesi `pyproject.toml` ve `uv.lock` dosyalarını kapsar. Bu gelecekteki kapsam mevcut taslak görevinin iki dosyalık iznini genişletmez. Gözlemci ve ham kanıt `.local/p9r-*/`, runtime veri geçici uygulama-veri dizininde; izlenen script/test değişikliği yok. Commit/push/publish yok.

Sonuç belgesi önce sonucu ve koşulluluğu söyler; her R-satırında değer, payda, örnek/tohum, okuyan ve durum vardır. P19 ayrı yardımcı a-e sayıları ve bölüm/iddia listeleridir, R01 başarı eşiği olmaz. Eşikler freeze §4.2'den gelir; R11 için ≤10 kaynakta **0 kesilme**, eski kısa sonuç tablolarındaki %20 değil. Rapor durduysa yalnız R1, R7 ve P19 korunur; R10 her durumda ölçülmedi. Kapanış doğrulanmamışsa P19 da kayıt anındaki sayım diye etiketlenir. Sert satır R2/R3/R4a aralık dışındaysa ilk cümlede ve kullanım sınırında görünür. R01 özetini bütünlük/okuma eksikliği varken koşulsuz geçti yapma.

Karar kaydı başarı ve başarısızlığı aynı açıklıkla taşır; hazırlık başarısızlığını da içerir. Sayılar bulunan/tekil/taranan/dahil/incelenen/modele verilen/atıf yapılan olarak ayrılır. Sonuç yalnız “geliştirme sonrası yeni korpus, tek koşu, tek rapor modeli, rapora hazır tablo koşuluna bağlı” diye sunulur. Genel kalite, yenilik, matematiksel doğruluk, D129'un nedensel etkisi, hız/maliyet veya hata oranı yazılmaz. H8 kapanışı H9'u beklemez.

Doğrulama: başlangıç ve son kaynak/hash eşitliği, kit testleri ve kuru health kaydı; dondurma belge bağlantıları/komutları; `git diff --check` ve son `git status --short`. Rapor yürütme sonucu bir bilimsel doğrulama diye adlandırılmaz. Son raporda koşu/oturum sayıları, ölçülemeyenler, sapmalar, yalnız başlatılan süreçlerin kapanışı, canlı servisin hiç yeniden başlatılmadığı ve değişikliklerin uncommitted kaldığı açıkça yazılır.
