# SW uygulaması: ana dosya

SW1–SW17'nin ürüne işlenmesi bu dosyadan yürür. Her sohbet (plan, uygulama, inceleme) önce burayı okur: sırada ne var, hangi dilim dosyası ve hangi prompt kullanılacak, hangi karar bekliyor. Kararların kendisi [search-workflow-review-2026-09-18.md](search-workflow-review-2026-09-18.md)'dedir; dilimlerin kapsamı, kabul koşulları ve tüm dilimler için geçerli kurallar [sw-implementation-plan.md](sw-implementation-plan.md)'dedir. Bu dosya yeni tasarım taşımaz; doğruluk kaynağı kod ve testlerdir.

## Bir tur

1. **Plan** (Fable, plan sohbeti): sıradaki dilimin dosyası ve promptu yazılır; satır `dosya hazır` olur.
2. **Uygulama** (yeni sohbet, Opus, efor medium): ilk ileti yalnızca `docs/product/sw-sliceNN-prompt.md dosyasını uygula.` olur. Satırını `uygulanıyor` yapar; iş bitip testler yeşil olunca satırı `uygulandı, inceleme bekliyor` yapar, açık kalanı yazar, tek commit olarak işler ve `main`'e iter. Yarım kalan iş commit'lenmez.
3. **İnceleme** (yeni sohbet, Fable · high; uygulayandan farklı model). Her dilim incelenir, ama aynı ağırlıkta değil (sahibin kararı, 20 Eylül 2026):
   - **tam:** dilim biter bitmez, tek başına. Uygulayan sohbetin commit'i dilim dosyasına karşı okunur, testler koşulur, dosyada ve testlerde olmayan durumlar aranır (tekrarlanan çağrı, kalıcı silme, mevcut seçim ve sürüm mantığıyla etkileşim), bulgular ayrı bir düzeltme commit'iyle işlenir. Yanlış kararın sessizce kanıtı bozduğu dilimler böyledir: 02, 03, 09, 12, 16 ve açılırsa 23. Dilim 01 temel olduğu için tam incelendi.
   - **toplu:** iki üç dilim birlikte, doğal bir durakta, tek oturumda; dilimlerin birbirine oturuşuna da bakılır. Üst üste kurulan omurga dilimleri (09 → 10 → 12) biriktirilmez: 10, 12 başlamadan önce incelenir.
   - **her dilimde, sahip:** uygulayan sohbetin son iletisindeki "yazıldığı gibi yapılamayan yerler" ve "yapmadıklarım" listesine ve test sayısına beş dakikalık bakış. Listede şüpheli bir şey varsa dilim toplu yerine tam incelenir.
   - Dilim ancak incelemesi bitince `kapandı` olur; toplu bekleyen dilim `uygulandı, inceleme bekliyor` kalır ama sonraki dilimin başlamasını engellemez. Her inceleme aşağıdaki **Yapılan incelemeler** kaydına bir satır yazar; satır silinmez.
4. **Ölçüm en sonda, toplu yapılır** (dilim 24: kuantum yeniden, yeni bir soru, Elicit raporlarıyla karşılaştırma). Dilimler ölçüm için durmaz; ölçülmemiş parça "ölçülmedi" diye kaydedilir. İstisnalar: dilim 06'nın bilinen kusuru ve dilim 13'ün duman testi.

Plan ve inceleme turları her dilimde Fable · high ile yapılır; tablodaki sütun yalnızca uygulayan sohbeti gösterir. **medium:** tasarımı dilim dosyasında bitmiş, mekanik işler. **high:** uygulayanın köşe durumlarında kendi yargısını kullanması gereken dilimler (karar kuralları, `selections` türetmesi, sürüm birleştirme, sözleşme + yöntem paketi + akışın birlikte değiştiği yerler). Duman testi ve ölçüm kampanyası Fable'da koşar, çünkü protokolü dondurmak ve sonucu yorumlamak muhakeme işidir; uzun koşan ölçüm betiği arka plan ajanına (Sonnet) verilebilir. Bir dilimin son iletisinde "yazıldığı gibi yapılamayan yerler" listesi uzunsa sonraki benzer dilimin eforu bir kademe yükseltilir.

Durumlar: `plan` (yalnızca ana planda) · `dosya hazır` · `uygulanıyor` · `uygulandı, inceleme bekliyor` · `kapandı` · `sahip kararı bekliyor`.

## Dilimler

| # | Dilim | Tür | Uygulayan model · efor | İnceleme | Durum | Dosya · prompt | Commit / D | Açık kalan |
|---|---|---|---|---|---|---|---|---|
| 01 | Protokol kaydı ve belirlenimcilik | Kur | Opus · medium | tam · yapıldı | kapandı | [dilim](sw-slice01-protocol-and-determinism.md) · [prompt](sw-slice01-prompt.md) | `b09e9a9` + inceleme düzeltmesi · D70 | Protokol gövdesinin ölçüt/blok/sinyal alanları `None`; `attached` araştırmada protokol kaydı yok (sahip kararı); uygulama-geneli varsayılan gözden geçirici gövdeye çözülmüyor (`build_protocol` deposuz); `code_version` commit başına değişmiyor (dilim 24 öncesi); FTS eşitliği yalnızca ikinci anahtarla sabit, ölçülmedi; `search_workflow` yalnızca saklanıyor. Slice SQL'inden sapma: `protocol_records_no_delete` tetikleyicisine 0010'daki kalıcı-silme istisnası eklendi. |
| 02 | Aşama kararlarının saklanması | Kur | Opus · high | tam · yapıldı | kapandı | [dilim](sw-slice02-stage-decisions.md) · [prompt](sw-slice02-prompt.md) | `081a566` + inceleme düzeltmesi · D71 | Hiçbir akış adımı bu tabloları yazmıyor (yazanlar dilim 05, 07, 09, 12, 16); neden kodları yalnızca SW11'in çalışma adları, derleme işareti / kod kapısı / K3 bütçe kodları yok; `criterion_not_met` `selections`'ta `excluded` görünüyor, ayrımı hiçbir görünüm göstermiyor; sürümler çeliştiğinde iş `pending` kalıyor ve hiçbir yerde gösterilmiyor; `apps/web/src/api.ts` `origin` tipi `code_rule`'u tanımıyor, ilk yazan dilimde genişletilmeli; SW9.5 konu özellikleri ve geniş dışa aktarım yapılmadı. Slice'tan sapma: `purge_sources` (D65), kaynak düzeyinde yetki tablosu olmadığı için karar silme tetikleyicisini araştırma purge yetkisiyle açıyor. İncelemede düzeltildi: `undo_human` geri getirdiği karara güncel revizyonu damgalıyordu (eskimiş karar taze görünüyordu); `work_outcome` aynı sonuçlu sürümlerden ilk yazılanı adlandırıyordu, şimdi işin başı, yoksa en küçük kimlik. Yoruma açık nokta: insan kararı en yenisi alınırken eşit zaman damgasında yazma sırası belirliyor. |
| 03 | Kayıt türü ve sürüm birleştirme | Kur | Opus · high | tam | kapandı | [dilim](sw-slice03-record-kind-and-version-links.md) · [prompt](sw-slice03-prompt.md) | `2c8c95e` + inceleme düzeltmesi · D72 | 127 çift incelemede okundu: 4 birleşme doğru görünüyor; 23 `extended_version` çiftinin çoğu bildiri + dergi değil, iki DOI altında kayıtlı tek makale (iki iş kalıyor, iki kez taranacak; dilim 05 / 20). `pairs.csv` `.local/sw-slice03-pairs-2026-09-20/`'de, çiftlerin 85'i Zenodo/figshare yatırımı olduğu için `artifact` + `artifact` çıkıp hiç bağlantı almıyor, 4 çift birleşiyor. Dış bağlantılar (SW6.4) dilim 05'te; ek ürün ve bildirimler aday listesinde kalıyor (dilim 09); `probable_version` insan kuyruğuna dilim 16'da giriyor; `extended_version` çiftinin tek sayılması hiçbir yerde yok (dilim 20); bağlantılar, geri alma ve "may duplicate" işareti arayüzde yok; işin başı hâlâ D48'in dar ön baskı testiyle seçiliyor; iki yayımlanmış kayıt aynı ön baskıyı isterse ilk işlenen alır (sıraya bağlı, belirlenimcilik kümesinde yok); eşikler tek konuda elle seçildi, DOI'siz kayıtlar ve ürün içi ölçüm yok (dilim 24). Slice'tan sapmalar: `undo_json` slice'ın adlandırmadığı `keep_work_id`'yi de taşıyor (yoksa hangi işe taşındığı bulunamıyor); `notice_type` normalleştirilmiş değil ham başlığı okuyor (iki nokta normalleştirmede kayboluyor); `_keep_and_drop` "published kaydın işi"ni iş düzeyinde okuyor (yayımlanmış kaydı barındıran iş); sınıflandırılacak her çiftin özeti okunuyor, yalnızca başlık eşiğini geçenlerin değil. |
| 04a | Kodla sözcük dağarcığı ve kavram blokları (çıkarma, sayım sınaması, blok sorgusu, `sw` keşfine bağlama) | Kur (ölçülmedi) | Opus · high | toplu | kapandı | [dilim](sw-slice04a-code-vocabulary.md) · [prompt](sw-slice04a-prompt.md) | `7f06333` + inceleme düzeltmesi · D73 | Plandaki dilim 04 ikiye bölündü. Sayfalama ve `sw` okuma bütçesi dilim 04c'ye yazıldı. Kuru çalıştırma: kuantum sorusunun 2. ve 3. cümlesindeki 8 ifade (`treatment`, `supporting`, `state`, `verified`, `full text`, `model feature`) bloklara giriyor, paket sorusunda `by simulation` iddia sayılıyor — atama kuralı soruyu tek parça okuyor, düzeltme `key_terms` ya da dilim 08. Sapmalar: sınama sırası `setting` sonra `task` (Extraction soru içi sırayı taşımıyor); düşen ifadenin sözcükleri sınanmıyor; soru kalıbı her cümlenin başında atılıyor; `key_terms` verilmeyen revizyon öncekini taşıyor (temizleme yok); `code_version` blok derleyicisini adlandırıyor. Yapılmadı: sayım istekleri `provider_requests` sayacına girmiyor; `views.research_view` `sw` koşusunda `plan` alanını `None` bırakıyor (arayüzde sözcük dağarcığı görünmüyor, dilim 08); duraklatma nedenleri arayüzde ham metin. |
| 04b | Veriden genişleme (yazar anahtar sözcükleri, başlık n-gramları; SW2.4) ve terim başına verim kaydı | Kur (ölçülmedi) | Opus · medium | toplu | plan | | | Önkoşul 04a. Sağlayıcı kaydına anahtar sözcük alanı ister. |
| 04c | `sw` aramasında sayfalama ve okuma bütçesi | Kur | Opus · medium | toplu | plan | | | Önkoşul 04a; dilim 07'nin önkoşulu. Tarama kesimi (`max_candidates`) dilim 09'a kadar durur. |
| 04d | Blok atamasını modele sordur, kararı kodda tut (SW17) | Kur | Opus · high | tam | dosya hazır | [dilim](sw-slice04d-model-block-labelling.md) · [prompt](sw-slice04d-prompt.md) | | Önkoşul 04a; 04b ve 04c'den bağımsız. Ölçüldü: `.local/sw-block-labelling-2026-09-21/` — 8 soru, 28 ifade, kural 19/28, `deepseek-flash` 28/28, üç koşuda tam kararlı, çağrı başına ~2,3 sn / ~870 jeton. Kuralın edat vetosu bilerek kaldırıldı (öneriye sapma: veto düzeltilen iki vakayı da geri bozuyordu). `skill_package_hash` bu dilimde değişir. Ölçülmeyenler: tek gerçek iddia vakası, tek koşunun yeterliliği, İngilizce olmayan ve bozuk sorular, model hatası yolu. |
| 05 | Derleme işareti, eksik özet, sürüm bağlantıları | Kur | Opus · medium | toplu | plan | | | |
| 06 | Ölçüt, parçaları ve ipucu ifadeleri önerisi | Kur (ölçülmedi) | Fable · high (istem düzeltmesi), Opus · medium (kod) | toplu | plan (önce SW15.1 kusuru düzeltilir) | | | |
| 07 | Kayıt düzeyinde sıralama | Kur | Opus · high | toplu | plan | | | |
| 08 | Protokol onay adımı (arayüz) | Kur | Opus · medium | toplu | plan | | | |
| 09 | Özet taraması v2 | Kur | Opus · high | tam | sahip kararı bekliyor (K3) | | | |
| 10 | Arka planda tam metin getirme | Kur | Opus · high | toplu | plan | | | |
| 11 | Ölçüt pasajları | Kur | Opus · medium | toplu | plan | | | |
| 12 | Tam metin kararı | Kur | Opus · high | tam | plan | | | |
| 13 | Uçtan uca duman testi | Duman | Fable · high | — | plan | | | |
| 14 | Kaynak yönlendirme | Kur (ölçülmedi) | Opus · medium | toplu | plan | | | |
| 15 | Atıf zinciri | Kur | Opus · high | toplu | plan | | | |
| 16 | İnsan kuyruğu (arka uç) | Kur | Opus · high | tam | plan | | | |
| 17 | İnsan kuyruğu (arayüz) | Kur | Opus · medium | toplu | plan | | | |
| 18 | PDF bekleyenler ve kullanıcının eklediği PDF | Kur | Opus · medium | toplu | plan | | | |
| 19 | Prob seti, kol ve sinyal tabloları, durma kuralı | Kur | Opus · high | toplu | plan | | | |
| 20 | Akış sayıları, denetim örneği, ezme sayısı, PRISMA-S dışa aktarımı | Kur | Opus · medium | toplu | plan | | | |
| 21 | Yerleşik yerel gömme | Kur | Opus · medium | toplu | plan | | | |
| 22 | arXiv LaTeX kaynağından okuma | Kur (ölçülmedi) | Opus · high | toplu | plan | | | |
| 23 | Kullanıcının onayladığı kod kapısı | Kur (isteğe bağlı) | Opus · high | tam | plan | | | |
| 24 | Varsayılanı değiştir ve kapat | | plan | Fable · high | — | | | |

## Yapılan incelemeler

Her inceleme bir satır: ne bulundu, nasıl kapandı. Bulgu yoksa "bulgu yok" yazılır. Kayıt, hangi tür dilimde incelemenin işe yaradığını gösterir; model ve efor seçimi buna göre gözden geçirilir. "İnceleyen" sütununa gerçekten kullanılan model ve efor yazılır, planlanan değil.

| Tarih | Dilim | Tür | İnceleyen | Bulgu | Düzeltme |
|---|---|---|---|---|---|
| 2026-09-20 | 01 | tam | Fable (plan sohbeti; efor kaydedilmedi) | Aynı kapsam revizyonunda ikinci keşif koşusu, model başka bir plan verince `internal_error` ile çöküyordu (değişen protokol gerekçe istiyor, akış vermiyordu); görünüm eski koşuya yeni protokolün özetini gösteriyordu. Kaynak: dilim dosyasında eksik durum, kod hatası değil. Ayrıca plandaki test komutu iki testi toplamıyordu (`PYTHONPATH=backend` yerine `backend:.`). Uygulayanın yerinde sapması: protokol kaydının silme tetikleyicisine kalıcı silme istisnası. | `8f9535c` |
| 2026-09-20 | 02 | tam | Fable · medium | `undo_human` geri getirdiği kararı güncel kapsam revizyonu ve protokol özetiyle damgalıyordu, böylece eskimiş bir karar taze görünüyordu; `work_outcome`, kazanan sonucu birden çok sürüm taşıdığında ilk karar verileni adlandırıyordu (sıraya bağlı), artık işin başını, yoksa en küçük kimliği adlandırıyor. | `8f88582` |
| 2026-09-20 | 03 | tam | Fable · high (plan sohbeti) | Korumanın reddettiği birleştirme (`work_already_has_published`) kayıt her yeniden bulunduğunda açık satırı `superseded` kapatıp aynısını yeniden yazıyordu: saklanacak hüküm açık satırla karşılaştırılmadan önce belirlenmiyordu. Tekrarlanan çağrı durumu; dilim dosyası soruyu soruyordu ama koruma yolu için test yoktu. Karar tablosu dosyaya uygun; `legacy` yolu değişmemiş. 127 çiftte yanlış birleşme yok. | `5f54a52` |
| 2026-09-21 | 04a | tek başına (tabloda toplu; sahip bitince istedi) | Fable · high (plan sohbeti) | İki bulgu. (1) `vocabulary_empty` ya da `vocabulary_too_broad` ile duran koşu sürdürülünce saklı çıktı yolu duraklatma denetimini atlıyor, koşu sorgusuz `completed` oluyor ya da reddedilen geniş sorguyu arıyordu; tekrarlanan çağrı durumu, testi yoktu. (2) Dil kuralı (dilim dosyasının kendi hatası, uygulayanın değil): işlev sözcüğü payı 0,2 eşiği, 11 sözcükte 2 işlev sözcüğü olan düz bir İngilizce soruyu ve her anahtar sözcük listesini `other` sayıp `key_terms_needed` ile durduruyordu. Sözcük listelerinde alan terimi yok; `legacy` yolu aynı. | `2ac5330` |

## Sahip kararları

Öneriler ana planın §5'indedir.

| Karar | Konu | Durum |
|---|---|---|
| K1 | Eski ve yeni akışın birlikte yaşaması (araştırma başına bayrak) | kabul edildi, önerildiği gibi (2026-09-20); bayrak D70 ile geldi |
| K2 | Yeni aşama kararlarının `selections` ile ilişkisi | kabul edildi, önerildiği gibi (2026-09-20); dilim 02 uygular |
| K3 | Özet aşamasında model çağrı bütçesi | bekliyor |
| K4 | Ölçüm modeli (`deepseek-flash`, efor `high`) | bekliyor |
| K5 | Kampanyanın yeni sorusu (öneri: tıp ya da yaşam bilimi) | dilim 24'te sahip seçer |
