# Teknik Notlar

## Bu çözümde verdiğim kararlar

Bu case'te uygulamayı tek bir `app.py` dosyasında tutmayı tercih ettim. İstersem
controller, service veya client gibi ayrı katmanlar oluşturabilirdim; ancak tek
endpoint ve yaklaşık 2,5 saatlik bir kapsam için bunun gereksiz yere dosya ve
katman sayısını artıracağını düşündüm. Uygulama büyüyüp yeni endpoint'ler
eklenseydi bu ayrımı yapmak daha anlamlı olurdu.

Kur dönüşümünde benim için önemli noktalardan biri, kullanıcının istediği tarih
ile gerçekten kullanılan kur tarihini birbirine karıştırmamaktı. Hafta sonu
veya tatil günlerinde Frankfurter önceki çalışma gününün yayımlanmış kurunu
döndürebiliyor. Bu yüzden `asked_date` ile istenen tarihi, `rate_date` ile kurun
gerçekte ait olduğu tarihi ayrı ayrı dönüyorum.

Geçmiş tarihli bir istek için `/latest` fallback kullanmıyorum. Çalışan bir cevap
döndürmek uğruna başka bir tarihin kurunu doğruymuş gibi göstermeyi daha riskli
buluyorum. Aynı nedenle gelecekteki tarihleri, ECB verisinin başlangıcından
önceki tarihleri ve istenen tarihten daha ileri bir `rate_date` döndüren
cevapları kabul etmiyorum.

Para hesabında `float` yerine `Decimal` kullandım. Upstream'den gelen kuru
önceden yuvarlamadan amount ile çarpıyorum ve yalnızca final sonucu iki ondalık
basamağa `ROUND_HALF_UP` ile yuvarlıyorum. Özellikle büyük tutarlarda kuru
hesaplamadan önce yuvarlamanın sonucu değiştirmesini istemedim.

Cache tarafında conversion sonucunu değil, doğrulanmış `(rate, rate_date)`
bilgisini saklıyorum. Cache key içinde upstream adresi, para birimi çifti ve
istenen tarih var; `amount` yok. Çünkü aynı gün için 100 EUR ve 500 EUR
sorulduğunda değişen şey kur değil, yalnızca yapılan hesap. Hatalı veya
doğrulanamamış upstream cevaplarını da cache'lemiyorum.

Timeout, bağlantı problemi, upstream HTTP hatası veya bozuk response gibi
durumlarda `0` kur veya `0` sonuç döndürmek yerine kontrollü bir hata vermeyi
tercih ettim. Buradaki temel yaklaşımım, hiç sonuç verememenin yanlış ama
güvenilir görünen bir sonuç vermekten daha güvenli olmasıydı.

## Bilerek kapsam dışında bıraktıklarım

Redis, database, retry mekanizması, ek endpoint'ler veya daha fazla mimari
katman eklemedim. Bunların gerçek production sistemlerinde kullanılabileceği
yerler var; ancak bu case'te istenen problemi daha doğru çözmek yerine kapsamı
büyüteceklerini düşündüm.

Bu case için uygulama belleğindeki cache'i yeterli gördüm. İstenen şey, aynı kur
sorgusunda upstream'e gereksiz yere tekrar gitmemekti. Bunun için ayrıca Redis
veya başka bir cache servisi eklemek gereksiz karmaşıklık oluştururdu.

## Daha fazla zamanım olsaydı

İlk olarak structured logging eklerdim. Özellikle upstream timeout, bağlantı
problemi ve geçersiz response gibi durumların müşteriye teknik detay göstermeden
loglanması production'da sorunları takip etmeyi kolaylaştırırdı.

Cache için de bir sınır ve expiry süresi belirlerdim. Örneğin aynı günün ECB
kuru henüz yayımlanmadan yapılan bir istekte Frankfurter önceki çalışma gününün
kurunu döndürebilir. `rate_date` sayesinde bunu yanlış tarihe aitmiş gibi
göstermiyoruz; fakat bu değer cache'de kaldığında güncel kur yayımlandıktan
sonra da kullanılmaya devam edebilir. Production'da aynı günün verisi için daha
kısa bir cache süresi kullanmayı düşünürdüm.

Bunlardan sonra yanıt süresi, hata türleri ve cache kullanım oranı gibi temel
metrikleri eklemek mantıklı olurdu. Ürün tarafında ihtiyaç oluşursa desteklenen
para birimlerini de upstream üzerinden ayrıca kontrol ederdim.

## AI'ı nasıl kullandım

Case boyunca Codex kullandım. Brief ve repository'yi inceleyip requirement'ları
netleştirmede, implementasyon taslaklarında, edge-case senaryolarını düşünmede
ve testleri hazırlamada yardımcı oldu.

Çalışmayı tek seferde AI'a bırakmak yerine küçük ve anlamlı paketlere böldüm.
Her paketten sonra oluşan değişiklikleri ve diff'i kontrol ettim,
requirement'larla karşılaştırdım ve davranışı testlerle doğruladıktan sonra
commit attım. Bazı noktalarda AI'ın söylediği sonucu dosyanın kendisinden,
terminal çıktısından veya çalışan servis üzerinden ayrıca kontrol ettim.

Bu yüzden AI'ı kodun doğru olduğunun kanıtı olarak değil, geliştirme ve kontrol
sürecini hızlandıran bir araç olarak kullandım.

## Kontrol sırasında yakaladığım bir problem

İlk implementasyonlardan birinde `Decimal` olan response alanları JSON'da sayı
yerine string olarak dönüyordu. İçerideki hesap doğru olmasına rağmen API
contract açısından `amount`, `rate` ve `result` alanlarının sayı olarak dönmesi
gerekiyordu.

Kontrol sırasında bunu fark ettim. JSON response oluşturma kısmını düzelttikten
sonra conversion'ı tekrar çalıştırıp dönen değerlerin tiplerini yeniden kontrol
ettim.

Burada şunu fark ettim: içeride hesabın doğru yapılması, dışarıya doğru API
cevabı verdiğimiz anlamına gelmiyor. Bu yüzden AI'ın ürettiği kodda yalnızca
çalışıp çalışmadığına değil, dışarıdan gerçekten nasıl davrandığına da bakmak
gerekiyor.
