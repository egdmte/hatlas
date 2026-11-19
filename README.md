# Hatlas

**Türkiye’deki toplu taşıma hatları, durakları ve açık verileri tek bir yerde.**
Canlı: **https://hatlas.avartech.net** · Topluluk: [r/hatlas](https://www.reddit.com/r/hatlas/)

Hatlas, şehirlerin GTFS akışlarını tek bir haritada toplar, her akışı kontrol eder (süresi dolmuş mu, hat çizimleri
kopuk mu, sefer saati var mı) ve verileri indirilebilir hâle getirir. Durak adları, erişilebilirlik bilgileri, yol
çalışmaları ve değişen güzergâhlar gönüllüler tarafından eklenir: hesap gerekmez, bir öneri farklı internet
bağlantılarından üç kişi “doğru” dediğinde ve en az bir gün oylamada kaldıktan sonra yayınlanır.

*English: Hatlas is an atlas of Turkey’s public transport data: every city’s GTFS feed on one map, with health checks,
downloads and volunteer fixes (stop names, accessibility, works, changed routes) confirmed by other visitors.*

## Kaynaklar ve lisanslar

| Ne | Lisans |
| --- | --- |
| Bu depodaki kod | [GNU AGPL-3.0](LICENSE) |
| Gönüllü katkıları (öneriler, düzeltmeler) | CC BY-SA 4.0 |
| Şehir akışları | [kk-gtfs](https://github.com/Egezenn/kk-gtfs) (KentKart verisinden, CC0); İstanbul için İBB Açık Veri Portalı. Belediye ve işletmeci verileri kendi lisanslarına tabidir. |
| Harita | [OpenFreeMap](https://openfreemap.org) · © OpenMapTiles · © OpenStreetMap katkıcıları |
| Harita kütüphanesi | [MapLibre GL JS](https://maplibre.org) (BSD-3, `vendor/maplibre/`) |
| Yazı tipi | Inter (SIL OFL, `fonts/Inter-OFL.txt`) |

## Neler var

```
index.html, sehir|isletme|hat|durak.html   harita ve şehir / işletmeci / hat / durak sayfaları
katalog.html, sorunlar.html, dogrula.html  veri kataloğu, bilinen sorunlar, “Bu doğru mu?” oylaması
copy/tr.toml       sitedeki bütün metinler (tek dosya)
js/                sayfaların betikleri (çerçevesiz, derleme yok); js/copy.js üretilir
css/pages.src.css  Tailwind kaynağı → css/pages.css
data/              üretilmiş veri: catalog.json, hatlar (GeoJSON), duraklar, sefer saatleri, stopnames.json
api/               gönüllü önerileri için küçük API (Python standart kütüphanesi + SQLite) ve testleri
tools/             veri derleme, günlük güncelleme, metin aracı, yerel sunucu
```

## Yerelde çalıştırma

Python 3.11+ ve (yalnızca CSS’i yeniden derlemek için) Node gerekir.

```
py -3 api/hatlas_api.py        # öneri API’si, 127.0.0.1:3200 (veri: api/dev-data/)
py -3 tools/serve.py 8765      # site, http://localhost:8765 (/api/* isteklerini API’ye iletir)
py -3 api/test_api.py          # API testleri
```

Metinleri değiştirmek için `copy/tr.toml` dosyasını düzenleyip `npm run copy` çalıştırın; araç metni sayfalara ve
`js/copy.js` dosyasına yazar, yanlış bir anahtar ya da yazım hatası olursa hiçbir şeyi değiştirmeden durur.
Stilleri derlemek için: `npm run css` (Tailwind CLI, `playground/node_modules` içinden).

Veriyi yeniden üretmek için `tools/build_catalog.py` kk-gtfs ve İBB akışlarını okur; `tools/update_feeds.py` her gün
kaynakları kontrol edip yalnızca bir şey değiştiğinde yeniden derler.

## Katkı ve iletişim

Verideki hataları sitenin kendisinden bildirebilirsiniz (her durak ve hat sayfasında “Eksik veya hatalı bir bilgi mi
var?”). Kod için issue ve pull request’ler açıktır. Soru ve öneriler için: [r/hatlas](https://www.reddit.com/r/hatlas/),
[u/egedemete](https://www.reddit.com/user/egedemete/), iletisim@avartech.net, egemen.pers@gmail.com.

Hatlas bir Avar projesidir; belediyeler ve işletmecilerle bir bağlantısı yoktur.
