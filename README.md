# ARObserver

Kurumun dışa açık web servislerini pasif kontrollerle (erişilebilirlik, TLS,
yönlendirme, güvenlik başlıkları, DNS) düzenli olarak izleyen, sonuçları
skorlayan ve bir panelde gösteren izleme servisi.

## Kurulum (Docker Compose)

1. `targets.example.yaml` dosyasını `targets.yaml` olarak kopyalayıp ilk
   kurulumda izlenecek hedefleri girin (isteğe bağlı — panelden de eklenebilir).
2. `.env.example` dosyasını `.env` olarak kopyalayıp gerekirse ayarları
   düzenleyin.
3. Ayağa kaldırın:

   ```
   docker compose up --build
   ```

4. Panel: http://localhost:8000

Kontrol kayıtları (`./data`) konteynerin dışında, proje klasöründe kalıcı
olarak saklanır; konteyner yeniden oluşturulduğunda veri kaybolmaz.

### Hedef yönetimi

`targets.yaml` yalnızca veritabanı tamamen boşken (ilk kurulum) bir kerelik
okunur. Ondan sonra tek gerçek kaynak veritabanıdır — hedefler panelden
("+ Yeni Hedef" / kart üzerindeki düzenle simgesi) eklenir, düzenlenir, silinir
veya pasife alınır. `targets.yaml`'ı sonradan değiştirmek hiçbir etki
yapmaz; dosya sadece ilk boot'ta referans alınır.

### Derin Kontrol Servisi

Hedef detay sayfasındaki "Derin Kontrol" düğmesi, ayrı bir Docker servisinde
(`deepcheck/`) çalışan Playwright tabanlı bir headless Chromium'u tetikler.
Bu servis `docker compose up --build` ile ana uygulamayla birlikte otomatik
ayağa kalkar (`deepcheck` servisi, iç ağda `http://deepcheck:8001` adresinde,
dışa port açmaz). Ana uygulamanın imajı bundan etkilenmez — Playwright ve
tarayıcı yalnızca `deepcheck` imajında bulunur.

Bu servis olmadan da ana panel normal çalışır; sadece "Derin Kontrol" düğmesi
pasif görünür ve sebebini yazar. Servisi tek başına yeniden başlatmak için:

```
docker compose up --build -d deepcheck
```

Derin kontrol sonucu hedef başına tek kayıt olarak saklanır (her çalıştırmada
üstüne yazılır, geçmiş tutulmaz) ve skora dahil edilmez.

## Ortam Değişkenleri

| Değişken | Açıklama | Varsayılan |
|---|---|---|
| `DATABASE_URL` | SQLite bağlantı adresi | `sqlite:///./data/arobserver.db` |
| `TARGETS_FILE` | Hedef tanım dosyası | `targets.yaml` |
| `DISPLAY_TIMEZONE` | Panelde gösterilen saat dilimi | `Europe/Istanbul` |
| `LOG_LEVEL` | Log seviyesi | `INFO` |
| `RETENTION_DAYS` | Kontrol kayıtlarının saklama süresi (gün) | `90` |
| `DEFAULT_CHECK_INTERVAL_MINUTES` | `targets.yaml`'da aralık belirtilmemişse varsayılan | `5` |
| `ALERT_FAIL_THRESHOLD` | Art arda kaç başarısız kontrolde uyarı açılsın | `3` |
| `CERT_EXPIRY_WARN_DAYS` | Sertifika bitişine kaç gün kala uyarı açılsın (virgülle) | `30,14,7` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO` | SMTP uyarı bildirimi (`SMTP_HOST` boşsa devre dışı) | - |
| `DEEPCHECK_SERVICE_URL` | Derin kontrol servisinin adresi | `http://deepcheck:8001` |

## Yerel Geliştirme (Docker'sız)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
