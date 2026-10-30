# Ders Kilidi (FocusMe) — Windows 10/11 Odaklanma Masaüstü Kabuğu

**Ders Kilidi**, çalışma sırasında oluşan dikkat dağılmalarını (Alt+Tab, yeni sekmede video açma, masaüstündeki başka uygulamalara kayma) engellemek için tasarlanmış, **Liquid Glass** görsel diline sahip yerel bir Python (PySide6) masaüstü kabuğudur.

Uygulama çalışırken Windows görev çubuğunu gizler, masaüstü ikonlarını sakin koyu bir örtüyle kapatır ve ekranın üst kısmında (`8 px` boşluklu, `44 px` yüksekliğinde) ince bir **Üst Çubuk (Top Bar)** gösterir. O gün girilen görevler tamamlanana kadar yalnızca beyaz listedeki uygulamalara ve Microsoft Edge üzerinde izin verilen sitelere erişilebilir.

---

## 1. Kurulum

### Gereksinimler
- Windows 10 veya Windows 11 (64-bit)
- Python 3.11+ (Projede `.venv` altında Python 3.13 yapılandırılmıştır)

### Sanal Ortam ve Paket Kurulumu
PowerShell üzerinde proje klasöründe aşağıdaki komutları çalıştırın:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 2. `TEST_MODE` ile İlk Deneme Adımları

İlk sürümde [app/config.py](app/config.py) içinde **`TEST_MODE = True`** varsayılan olarak açıktır.

### `TEST_MODE = True` İken Neler Değişir?
1. **10 Dakikalık Otomatik Kilit Açma (Dead-Man Switch):** Kilit en fazla **10 dakika** (`600` saniye) sürer; süre dolduğunda tüm kısıtlar kendiliğinden kalkar (`TEST_MODE = False` yapıldığında bu süre **14 saat** olur).
2. **Geliştirici/Kurtarma Araçları Muaftır:** `cmd.exe`, `powershell.exe`, `pwsh.exe`, `taskmgr.exe` ve `wt.exe` süreçleri denetleyici tarafından **kapatılmaz/öldürülmez**.
3. **Görsel Rozet:** Üst çubuğun sol tarafında sarı **`TEST MODU`** etiketi görünür.

### İlk Deneme Adımları
1. **Yönetici Olarak Başlatın:** Tam sistem kısıtlarının (`HKLM` Edge politikası, `DisableTaskMgr` ve `schtasks` zamanlanmış görev) uygulanabilmesi için PowerShell'i **Yönetici olarak (Run as Administrator)** açın ve çalıştırın:
   ```powershell
   .\.venv\Scripts\python.exe main.py
   ```
2. **Sabah Görev Girişi:**
   - **1. Bugünün Görevleri** sekmesinden en az 1 test görevi ekleyin (görev eklenmeden *"Ders Modunu Başlat"* düğmesi aktif olmaz).
   - **2. İzinli Uygulamalar & Ders Klasörü** sekmesinden bir **Ders Klasörü** seçin ve kullanmak istediğiniz `.exe` uygulamalarını beyaz listeye ekleyin.
   - **3. Edge İzinli Siteler** sekmesinden izinli alan adlarını (`gemini.google.com` vb.) kontrol edin.
   - **4. Acil Çıkış & Güvenlik** sekmesinden bir test şifresi belirleyin.
3. **Ders Modunu Başlatın:**
   - *"Ders Modunu Başlat (Masaüstünü Kilitle)"* düğmesine tıklayın.
   - Üst çubuğun ortasındaki aktif göreve tıklayarak açılır cam görev panelini (`TaskPopover`) açın, sağdaki **"Ders Klasörü"** butonundan klasör dosyalarını görüntüleyin veya `Ctrl+Alt+P` ile **Düşünce Park Alanı**nı deneyin.
   - Görevin onay kutusunu işaretlediğinizde tüm kısıtlar kalkacak ve **Tebrik / Gün Özeti** ekranı açılacaktır.
4. **Gerçek Kullanıma Geçiş:**
   - Testleriniz bittiğinde [app/config.py](app/config.py) dosyasındaki `TEST_MODE: bool = True` değerini `False` yapabilirsiniz.

---

## 3. `recover.py` (Acil Kurtarma Aracı) Nasıl Çalıştırılır?

Uygulama beklenmedik bir şekilde kapanırsa veya tüm sistem kısıtlarını (Görev Çubuğu, `DisableTaskMgr`, `HKCU`/`HKLM` Edge politikaları ve `DersKilidiBootRecovery` zamanlanmış görevi) anında sıfırlamak isterseniz bağımsız [recover.py](recover.py) aracını çalıştırabilirsiniz:

```powershell
# Çalışan kilit süreçlerini sonlandırır ve tüm Windows ayarlarını eski haline döndürür:
.\.venv\Scripts\python.exe recover.py

# Sadece sistem ayarlarını temizlemek için (süreçleri öldürmeden):
.\.venv\Scripts\python.exe recover.py --no-kill
```

> **Not:** `recover.py` hiçbir üçüncü parti kütüphaneye veya PySide6'ya bağımlı değildir; sistemdeki herhangi bir standart Python yorumlayıcısıyla (`python recover.py`) doğrudan çalışır.

---

## 4. PyInstaller ile `.exe` Paketleme Komutu

Projede ana uygulama (`ders_kilidi.exe`), bağımsız gözcü süreç (`ders_kilidi_watchdog.exe`) ve kurtarma aracı (`recover.exe`) için Yönetici (UAC Admin) manifestli [build.spec](build.spec) dosyası hazırdır.

```powershell
# build.spec ile üç çalıştırılabilir dosyayı dist\ders_kilidi\ altında üretmek için:
.\.venv\Scripts\pyinstaller.exe build.spec --noconfirm

# Alternatif tek komutla sadece ana uygulamayı derlemek için:
.\.venv\Scripts\pyinstaller.exe --noconfirm --windowed --uac-admin --name ders_kilidi main.py
```

---

## 5. Bilinen Sınırlamalar ve Güvenlik Gerçekliği

1. **Yeniden Başlatma Bilinçli Bir Kaçış Yoludur:**
   - **Yeniden başlatma bilinçli bir kaçış yoludur.** Bilgisayar yeniden başlatıldığında, oturum açılışında çalışan `DersKilidiBootRecovery` zamanlanmış görevi (`schtasks /SC ONLOGON /RL HIGHEST`) otomatik olarak `recover --auto-boot-clean` çalıştırır ve tüm kısıtları (görev çubuğu, Edge politikaları, Görev Yöneticisi engeli ve zamanlanmış görevin kendisi) temizler. Böylece sistem hiçbir koşulda kalıcı olarak kilitli kalmaz.
2. **Yönetici (Administrator) Hesabı Sınırları:**
   - Windows güvenlik modelinde Administrator yetkisine sahip bir kullanıcıyı kendi bilgisayarında %100 aşılmaz biçimde kilitlemek imkansızdır (ör. Güvenli Mod, güç tuşuyla kapatma, `Ctrl+Alt+Del` çekirdek kesmesi). Bu uygulamanın amacı **anlık dikkat dağılmalarına karşı yüksek sürtünme (impulse barrier)** oluşturmaktır.
3. **Yönetici Yetkisi (UAC Elevation) Gereksinimi:**
   - `HKLM\Software\Policies\Microsoft\Edge` kaydı, `DisableTaskMgr` politikası, `schtasks /RL HIGHEST` görevi ve `CreateProcessWithTokenW` için gerekli olan `SeImpersonatePrivilege` ayrıcalığı uygulamanın **Yönetici (Admin)** olarak çalıştırılmasını gerektirir. Standart (yükseltilmemiş) oturumda çalıştırıldığında `HKCU` Edge politikaları ve pencere/görev çubuğu kontrolleri çalışmaya devam eder.
