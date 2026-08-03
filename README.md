# ARObserver

Kurumun dışa açık web servislerini pasif kontrollerle (erişilebilirlik, TLS,
yönlendirme, güvenlik başlıkları, DNS) düzenli olarak izleyen, sonuçları
skorlayan ve bir panelde gösteren izleme servisi.

## Kurulum (Docker Compose)

1. `targets.example.yaml` dosyasını `targets.yaml` olarak kopyalayıp izlenecek
   hedefleri girin.
2. `.env.example` dosyasını `.env` olarak kopyalayıp gerekirse ayarları
   düzenleyin.
3. Ayağa kaldırın:

   ```
   docker compose up --build
   ```

4. Panel: http://localhost:8000

Kontrol kayıtları (`./data`) ve hedef listesi (`targets.yaml`) konteynerin
dışında, proje klasöründe kalıcı olarak saklanır; konteyner yeniden
oluşturulduğunda veri kaybolmaz.

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

## Yerel Geliştirme (Docker'sız)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
