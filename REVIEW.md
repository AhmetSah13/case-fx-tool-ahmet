# Production İncelemesi

## Bulgular

### 1. Farklı tarihler için yanlış kur kullanılabilir

**Problem nedir?**

Cache key içinde sadece para birimleri var, tarih yok (28–30. satırlar).
Bu yüzden bir tarih için alınan kur, aynı para birimleriyle başka bir tarih
sorulduğunda tekrar kullanılabilir.

Ayrıca kod upstream'den gelen gerçek `date` bilgisini kullanmıyor. Kur hangi
tarihe ait olursa olsun istenen tarihle birlikte dönüyor (44. satır).

İstenen kur bulunamazsa geçmiş tarihli bir sorguda bile `/latest` endpoint'ine
fallback yapılması da aynı problemi büyütüyor (36–40. satırlar).

**Müşteriye etkisi**

Bir kullanıcı geçmiş tarihli bir fatura veya ödeme için kur sorduğunda sistem
başka bir günün kurunu döndürebilir. Daha önemlisi, bu kurun yanlış tarihe ait
olduğu response'tan anlaşılmayabilir.

Bunu en kritik hata olarak görüyorum. Çünkü sistem hata vermek yerine normal
görünen bir HTTP 200 cevabı ile yanlış finansal bilgi verebilir.

**Nasıl test ederdim?**

Fake upstream üzerinde aynı para birimleri için iki farklı tarihe iki farklı kur
tanımlardım. İki tarihi sırayla sorgulayıp doğru kurların ve upstream'in gerçek
tarihlerinin döndüğünü kontrol ederdim.

Hafta sonu için de cuma gününe ait kur döndüren bir senaryo hazırlayıp
`rate_date` değerinin cuma olduğunu doğrulardım.

---

### 2. Upstream hataları başarılı bir sonuç gibi dönüyor

**Problem nedir?**

Kodun sonundaki geniş `except` bloğu hataları yakalayıp:

`rate: 0.0`

ve

`result: 0.0`

döndürüyor (71–81. satırlar).

Bu normal bir return olduğu için FastAPI HTTP 200 döndürüyor.

Upstream status code da ayrıca kontrol edilmiyor. Timeout, bağlantı problemi, HTTP 500 veya bozuk bir response gibi farklı hata durumlarının tamamı geniş except bloğu nedeniyle aynı şekilde başarılı görünen 0 değerli bir cevaba dönüşebiliyor.

**Müşteriye etkisi**

Servis aslında kuru alamamış olsa bile çağıran sistem bunu başarılı bir işlem
olarak görebilir.

Örneğin bir AI agent kullanıcıya "şu anda kuru alamıyorum" demek yerine
`0` değerini gerçek bir sonuç gibi gösterebilir.

**Nasıl test ederdim?**

Fake upstream ile timeout, HTTP 500, non-JSON response ve eksik rate alanı
senaryolarını test ederdim.

Bu durumlarda HTTP 200 yerine kontrollü bir hata ve non-2xx status beklerdim.

---

### 3. Case'te istenen API contract tam uygulanmamış

**Problem nedir?**

Upstream adresi kodun içine yazılmış (18. satır). Bu yüzden
`FX_UPSTREAM_BASE` değişkeni kullanılmıyor.

Endpoint tarafında da beklenen query parametreleri `from` ve `date` iken
kodda `from_` ve `on` kullanılıyor (48–49. satırlar).

Success response içinde `asked_date` alanı da yok.

**Müşteriye etkisi**

Doğru görünümlü bir request gönderilmesine rağmen kod farklı default değerlerle
çalışabilir. Bu da yanlış para birimi veya yanlış tarihle hesap yapılmasına
neden olabilir.

`FX_UPSTREAM_BASE` kullanılmadığı için test sırasında servisi fake upstream'e
yönlendirmek de mümkün olmaz.

**Nasıl test ederdim?**

Önce OpenAPI üzerinden gerçek query parametrelerini kontrol ederdim.

Daha sonra `FX_UPSTREAM_BASE` ile fake bir upstream tanımlayıp
`from=USD&date=2024-01-10` isteği gönderirdim. Kodun gerçekten hangi host,
para birimi ve tarih ile upstream'e gittiğini kontrol ederdim.

---

### 4. Kur hesaplanmadan önce yuvarlanıyor

**Problem nedir?**

`amount` değeri `float` olarak alınıyor ve upstream'den gelen kur çarpma
işleminden önce iki ondalık basamağa yuvarlanıyor (48 ve 60–61. satırlar).

Örneğin kur `1.2349`, amount `1000` ise doğru sonuç `1234.90` olmalı.

Mevcut kod önce kuru `1.23` yaptığı için sonuç `1230.00` oluyor.

Ayrıca zero, negative, NaN, Infinity ve same-currency gibi input'lar için
açık bir davranış tanımlanmamış.

**Müşteriye etkisi**

Özellikle büyük miktarlarda erken yuvarlama sonucu değiştirebilir. Response
normal bir finansal sonuç gibi göründüğü için kullanıcı bu hatayı kolayca fark
edemez.

**Nasıl test ederdim?**

Fake upstream'den `1.2349` kur döndürüp `1000` amount ile sonucu kontrol
ederdim. Ayrıca zero, negative, NaN, Infinity ve same-currency isteklerini ayrı
ayrı denerdim.

## Production'a çıkmadan önce ilk neyi düzeltirdim?

İlk olarak 1. problemi düzeltirdim.

Cache key'e tarihi ekler, rate ile birlikte upstream'in gerçek tarihini de
saklardım. Geçmiş tarihli bir sorguda `/latest` fallback kullanılmasını da
kaldırırdım.

Bunu ilk sıraya koymamın nedeni, mevcut kodun müşteriye hem yanlış kur hem de
yanlış tarih verebilmesi ve bunu normal bir HTTP 200 cevabı içinde yapması.

Daha sonra upstream hatalarının `0` değerli başarılı response'lara dönüşmesini
düzeltirdim.

## İlk bakışta sorun gibi görünen ama kabul edilebilir bir nokta

Process-local dictionary kullanılması tek başına problem değil.

Küçük ve tek process çalışan bir servis için memory cache yeterli olabilir.
Buradaki asıl hata Redis kullanılmaması değil; cache key içinde tarihin
olmaması ve gerçek `rate_date` bilgisinin saklanmaması.

Bu yüzden cache sistemini tamamen değiştirmek yerine önce cache'lenen bilginin
doğruluğunu düzeltirdim.
