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

### Sertifika Zinciri ve Certificate Transparency

Hedef detay sayfasında, HTTPS uygulanabilirse tam sertifika zinciri (yaprak →
ara → kök) katmanlı bir liste olarak gösterilir — her sertifika için veren,
geçerlilik tarihleri, seri no, imza algoritması, anahtar tipi/uzunluğu ve
SHA-256 fingerprint. SHA-1 imza veya 2048 bitten kısa RSA anahtarı tespit
edilirse skor düşer (mevcut "TLS Sertifika Geçerliliği" kategorisinde).

Certificate Transparency (crt.sh üzerinden bilinmeyen alt alan adı keşfi)
**varsayılan olarak KAPALI**dır — `CT_LOG_CHECK_ENABLED=true` ile açılabilir.
Açıkken hedef başına günde en fazla 1 sorgu yapılır (sonuç `Target` üzerinde
önbelleklenir); kapalıyken crt.sh'a hiç istek atılmaz.

### Kimlik Doğrulama

Panel ve `/api/v1` uçları tek bir yönetici şifresiyle korunur. Şifre `.env`'de
düz metin olarak DEĞİL, bir hash olarak saklanır:

```
python -m cli.hash_password
```

Bu komut şifreyi gizlice sorar ve `ADMIN_PASSWORD_HASH`'e yapıştırılacak
hash'i basar. `STORAGE_SECRET` de ayarlanmalı (herhangi bir rastgele metin,
oturum çerezlerini imzalamak için) — aksi halde her yeniden başlatmada
oturumlar sonlanır. Her ikisi de boş bırakılırsa uygulama açılışta geçici,
rastgele bir şifre üretip loglara yazar (`docker compose logs arobserver`) —
panel asla şifresiz açılmaz.

**Önemli:** `ADMIN_PASSWORD_HASH` değeri `$` karakterleri içerir
(`pbkdf2_sha256$260000$...$...`). Docker Compose, `.env` dosyasındaki `$`
işaretini değişken referansı olarak yorumlar ve sessizce boşaltır — bu
yüzden `.env`'e yapıştırırken her `$`'ı `$$` olarak İKİLEYİN (örn.
`pbkdf2_sha256$$260000$$...$$...`). Konteyner içinde `printenv
ADMIN_PASSWORD_HASH` ile gerçek (tek `$`'lı) değerin doğru geldiğini
doğrulayabilirsiniz.

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
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram uyarı bildirimi (ikisi de boşsa devre dışı) | - |
| `DEEPCHECK_SERVICE_URL` | Derin kontrol servisinin adresi | `http://deepcheck:8001` |
| `ADMIN_PASSWORD_HASH` | Yönetici şifresinin hash'i (`python -m cli.hash_password` ile üretilir) | boşsa geçici şifre üretilir |
| `STORAGE_SECRET` | Oturum çerezlerini imzalamak için gizli anahtar | boşsa geçici üretilir (kalıcı değil) |
| `CT_LOG_CHECK_ENABLED` | Certificate Transparency (crt.sh) alt alan adı keşfi — hedef başına günde en fazla 1 sorgu | `false` |
| `USER_AGENT` | Tüm dış isteklerde (hedef kontrolü, canary, crt.sh) gönderilen User-Agent | `ARObserver/1.0 (+https://arnavutkoy.bel.tr)` |
| `CHECK_RETRY_DELAYS_SECONDS` | Erişilebilirlik kontrolü başarısız olursa deneme aralıkları (virgülle, sn) | `5,15` |
| `CANARY_URL` | Hedef erişilemediğinde yoklanan güvenilir dış adres — o da başarısızsa hata "ağ sorunu" işaretlenir (uyarı üretilmez, uptime'a katılmaz) | `https://www.google.com` |
| `SCHEDULER_JITTER_SECONDS` | Hedef kontrollerinin zamanlamasına eklenen rastgele gecikme (0-N sn, aynı anda toplu isteği önler) | `30` |

## Yerel Geliştirme (Docker'sız)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
