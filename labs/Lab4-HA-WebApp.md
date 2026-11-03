# Lab 4: Highly Available Web App dengan ALB dan Auto Scaling (70 menit, Hari 2)

**Tujuan:** Peserta membangun load balancer lebih dahulu dengan dua instance manual, membandingkan round robin, least outstanding requests, dan sticky session, kemudian menambahkan Auto Scaling Group untuk self-healing dan scale-out saat beban tinggi.
**Biaya:** ALB sekitar $0,025 per jam ditambah dua sampai empat instance t3.micro (sementara waktu enam instance saat transisi ke ASG). Resource lab ini **dihapus pada akhir Hari 2** (setelah Lab 6). Peserta bekerja sendiri-sendiri; nama resource diberi akhiran nama peserta.
**Status:** belum diuji pada akun AWS yang sebenarnya. Trainer melakukan dry-run, terutama pada User Data (`06-app/user-data.lab4.sh`).

## Urutan Lab
1. Setup ALB (dengan dua instance manual) 2. Simulasi round robin 3. Simulasi least outstanding requests 4. Simulasi sticky 5. Setup ASG (desired 2, maksimum 4) 6. Terminate satu instance dan amati auto healing kembali ke 2 7. Simulasi beban tinggi dan auto scaling.

## Arsitektur
Internet, ALB (default VPC, dua subnet pada dua AZ), Target Group, dan instance EC2 dari Launch Template. Setiap instance menjalankan `lab-app` (folder `06-app`), yaitu aplikasi kecil yang dapat dibuat lambat, dibebani CPU-nya, atau dibuat error. Pada Bagian C, instance manual digantikan oleh Auto Scaling Group.

## Prasyarat
- Default VPC dengan default subnet pada minimal dua AZ (sudah dipakai di Lab 2).
- IAM role `lab-ec2-app` (instance profile; disiapkan trainer). Role ini memberi izin CloudWatch Agent (termasuk membaca konfigurasi dari SSM Parameter Store), X-Ray, dan Secrets Manager yang dipakai pada Lab 5 dan 6.
- Berkas dari trainer: `user-data.lab4.sh` dan `loadgen.sh`. Jalankan `loadgen.sh` dari **AWS CloudShell** (Actions, Upload file), karena CloudShell sudah memiliki bash, curl, dan awk.
- Service-linked role untuk ELB dan Auto Scaling sudah dibuat trainer.

## Referensi Endpoint `lab-app`
Setiap instance menjalankan aplikasi yang sama. Panggil endpoint melalui `$ALB` (DNS name ALB) atau langsung ke instance. Setiap respons membawa header `X-Instance-Id`.

| Endpoint | Fungsi | Contoh dan hasil | Dipakai pada |
|---|---|---|---|
| `/` | Halaman status: instance, AZ, jumlah request, *in-flight* (request yang sedang berjalan), uptime, status health, tracing, `degrade`, status **beban CPU** (aktif atau tidak, sisa waktu) dan load average, ditambah **tabel seluruh endpoint ini** (fungsi dan contoh) sehingga daftar ini juga dapat dibaca langsung dari browser | `curl $ALB/` | Langkah 6, 11 (lihat in-flight) |
| `/id` | Satu baris teks `instance-id az`; dipakai `loadgen.sh` untuk menghitung sebaran per instance | `curl $ALB/id` menghasilkan `i-0abc... ap-southeast-3a` | Seluruh simulasi, langkah 6 sampai 22 |
| `/health` | Endpoint health check ALB. Menjawab `200 ok`, atau `503 unhealthy` setelah `/health/fail`. Tidak terpengaruh `/degrade` | Path health check di Target Group | Langkah 4 dan Lab 5 |
| `/health/fail` | Membuat `/health` menjawab 503 pada instance yang melayani panggilan ini, sehingga target menjadi `unhealthy` (simulasi aplikasi rusak) | `curl $ALB/health/fail` (ulangi bila perlu agar mengenai instance yang diinginkan) | Lab 5 |
| `/health/ok` | Memulihkan `/health` menjadi 200 | `curl $ALB/health/ok` | Lab 5 |
| `/slow?ms=10000` | **Long request**: menahan request selama `ms` milidetik (bawaan 10000, maksimum 60000) lalu menjawab. Request tetap dihitung *outstanding* selama menunggu | `curl "$ALB/slow?ms=10000"` menjawab setelah 10 detik | Langkah 11 |
| `/degrade?ms=10000&only=<instance-id>` | Membuat **satu instance lambat**: setiap request (kecuali health check) ditambah `ms` milidetik (bawaan 10000, maksimum 30000). Parameter `only` memastikan hanya instance tersebut yang terkena; instance lain menjawab 409 | `bash loadgen.sh degrade $ALB <instance-id> 10000` | Langkah 8 sampai 12 |
| `/degrade/off?only=<instance-id>` | Memulihkan instance dari mode lambat | `bash loadgen.sh recover $ALB <instance-id>` | Langkah 12 |
| `/cpu?seconds=300&workers=2` | **Beban CPU tinggi**: memulai `workers` proses yang membakar CPU selama `seconds` detik (bawaan 300, maksimum 900) pada instance yang melayani panggilan | `bash loadgen.sh cpu $ALB 6 300` memanggilnya enam kali | Langkah 21 dan Lab 5 |
| `/cpu/stop` | Menghentikan semua proses beban CPU pada instance yang melayani panggilan | `curl $ALB/cpu/stop` (ulangi agar mengenai semua instance) | Langkah 23 |
| `/session` | Penghitung sesi di **memori instance** dengan cookie `labsess`. Respons memuat `session`, `hits_on_this_instance`, dan `instance`. Tanpa sticky, hitungan kembali ke 1 saat pindah instance | `bash loadgen.sh session $ALB 10` | Langkah 13 sampai 14 |
| `/error` | Menjawab **HTTP 500** dan menulis log `ERROR` (simulasi error aplikasi) | `curl -i $ALB/error` | Lab 5 (alarm 5xx dan metric filter) |
| `/notes?u=<nama>` | GET menampilkan 20 catatan terbaru, POST menyimpan satu catatan (`&text=...`) di DocumentDB | `curl -X POST "$ALB/notes?u=<nama>&text=halo"` | Lab 6 Bagian A |
| `/checkout?u=<nama>` | Simulasi transaksi bertahap: `validate`, `db.find` pada koleksi `orders`, `payment.call` (±300 ms), dan `render`. Respons memuat `steps_ms` (waktu tiap langkah) | `bash loadgen.sh checkout $ALB 40 4 <nama>` | Lab 6 Bagian B |
| `/admin/index?u=<nama>` | Membuat indeks `customer_id` pada koleksi `orders` (memperbaiki query lambat); `/admin/index/drop` menghapusnya | `curl "$ALB/admin/index?u=<nama>"` | Lab 6 Bagian B |
| `/customers` | Membaca 10 baris `customers_masked` dari PostgreSQL on-prem melalui VPN | `curl http://<ip-publik>/customers` | Lab 8 |

Pada Lab 4 hanya `/`, `/id`, `/health`, `/slow`, `/degrade`, `/cpu`, `/cpu/stop`, dan `/session` yang dipakai. Endpoint lain dipakai pada lab berikutnya dan didaftarkan di sini agar peserta mengenalnya sejak awal.

### Mode `loadgen.sh`
| Mode | Perintah | Fungsi |
|---|---|---|
| `fast` | `bash loadgen.sh fast $ALB 40 10` | 40 request ke `/id` dengan 10 paralel; menampilkan sebaran per instance serta latensi rata-rata, p95, dan maksimum |
| `degrade` / `recover` | `bash loadgen.sh degrade $ALB <instance-id> 10000` | Memanggil `/degrade` berulang (hingga 40 kali) sampai instance yang dituju yang menjawab |
| `slow` | `bash loadgen.sh slow $ALB 4 10000` | 4 long request paralel ke `/slow` |
| `cpu` | `bash loadgen.sh cpu $ALB 6 300` | 6 panggilan `/cpu` selama 300 detik masing-masing |
| `session` | `bash loadgen.sh session $ALB 10` | 10 request ke `/session` tanpa cookie, lalu 10 dengan cookie jar; menghitung per instance |
| `checkout` | `bash loadgen.sh checkout $ALB 40 4 <nama>` | 40 request ke `/checkout`; menampilkan rata-rata, p95, dan maksimum (Lab 6) |

## Bagian A: Setup ALB
1. **Security Group** (default VPC). Buat `alb-sg-<nama>` (inbound HTTP 80 dari `0.0.0.0/0`) dan `web-sg-app-<nama>` (inbound HTTP 80 **hanya dari `alb-sg-<nama>`**).
2. **Launch Template** `lt-app-<nama>`: AMI Amazon Linux 2023, t3.micro, Security Group `web-sg-app-<nama>`, tanpa key pair, IAM instance profile `lab-ec2-app`. Pada *Advanced details*, aktifkan **Detailed CloudWatch monitoring** (metrik per menit, sehingga scaling dan alarm Lab 5 lebih cepat), lalu pada **User data** tempel isi `user-data.lab4.sh` (jangan mengubah bagian KONFIGURASI). User Data ini hanya memasang aplikasi; **CloudWatch Agent tidak dipasang di sini** dan menjadi bagian Lab 5.
3. **Dua instance manual.** Dari Launch Template, pilih Actions, **Launch instance from template** dua kali, dan pilih subnet pada **dua AZ yang berbeda**. Beri nama `app-manual-1-<nama>` dan `app-manual-2-<nama>`. Instance ini belum dikelola Auto Scaling; dengan begitu peserta melihat dahulu apa yang dikerjakan ALB tanpa ASG.
4. **Target Group** `tg-app-<nama>`: type Instances, HTTP:80, health check path **`/health`**. Pada *Advanced health check settings* atur interval 10 detik, healthy threshold 2, dan unhealthy threshold 2. Daftarkan (register) kedua instance manual sebagai target.
5. **ALB** `alb-app-<nama>`: internet-facing, default VPC, **dua subnet pada dua AZ**, `alb-sg-<nama>`, listener HTTP:80 ke Target Group.
6. Tunggu hingga kedua target berstatus *healthy* (sekitar 3 sampai 5 menit karena User Data memasang paket). Buka DNS name ALB, lalu `/` dan `/id` beberapa kali: ID instance dan AZ bergantian. Bila target `unhealthy`, baca bagian Pemecahan Masalah.
7. **Siapkan beban.** Di CloudShell: `export ALB=<DNS name ALB>`, kemudian `bash loadgen.sh fast $ALB 40 10`. Catat sebaran per instance dan latensi (baseline).

## Bagian B: Simulasi routing dan sticky
### B1. Simulasi round robin
8. Ambil ID kedua instance dari `/id`. Pilih salah satu sebagai "node lambat", lalu jalankan `bash loadgen.sh degrade $ALB <instance-id> 10000`. Setiap request pada instance itu kini tertahan **10 detik** (analogi: satu node bermasalah karena disk lambat atau noisy neighbor). Health check `/health` tidak terpengaruh, jadi ALB tetap menganggapnya sehat.
9. Pada algoritma default (**round robin**), jalankan `bash loadgen.sh fast $ALB 40 10`. Perhatikan: sebaran tetap sekitar 50/50 dan latensi rata-rata tinggi (sekitar separuh request menunggu 10 detik), karena ALB tetap mengirim separuh request ke node lambat. Catat hasilnya.

### B2. Simulasi least outstanding requests
10. Buka Target Group, tab Attributes, Edit, ubah **Load balancing algorithm** menjadi **Least outstanding requests**. Ulangi langkah 9. Node lambat kini menerima jauh lebih sedikit request dan latensi rata-rata turun, karena request baru dikirim ke target dengan jumlah request yang masih berjalan paling sedikit.
11. **Long request.** Pada terminal CloudShell kedua jalankan `bash loadgen.sh slow $ALB 4 10000`, lalu pada terminal pertama buka `/` beberapa kali dan lihat nilai *in-flight* pada setiap instance. Diskusikan: request yang lama tetap dihitung *outstanding* sampai selesai, itulah sebabnya LOR cocok bagi request yang durasinya bervariasi.
12. Pulihkan node lambat: `bash loadgen.sh recover $ALB <instance-id>`. Diskusi: kapan memilih round robin, LOR, atau weighted random? (Weighted random tidak dapat dikombinasikan dengan sticky; slow start tidak dapat dikombinasikan dengan LOR.)

### B3. Simulasi sticky session
13. Jalankan `bash loadgen.sh session $ALB 10`. Tanpa sticky, request dengan cookie yang sama tetap tersebar ke kedua instance, sehingga penghitung `hits_on_this_instance` terus "kembali ke 1".
14. Pada Target Group, Attributes, Edit, aktifkan **Stickiness** dengan type *Load balancer generated cookie* dan durasi 5 menit. Ulangi langkah 13: request dengan cookie jar kini terkunci pada satu instance dan penghitung bertambah.
15. **Diskusi sticky** (lihat `05-learn/M10-Scaling-Monitoring`): sticky menutupi aplikasi yang menyimpan state di memori. Risikonya adalah beban tidak merata (terutama setelah scale-out karena klien lama tidak berpindah ke instance baru), sesi hilang saat instance diganti, dan kombinasi dengan weighted random tidak didukung. Alternatifnya adalah menyimpan sesi di luar instance (ElastiCache, DynamoDB, atau database).
16. **Matikan stickiness** kembali (agar beban tersebar merata pada bagian berikutnya).

## Bagian C: Auto Scaling
### C1. Setup ASG
17. **Auto Scaling Group** `asg-app-<nama>`: Launch Template `lt-app-<nama>`, default VPC dengan dua subnet (dua AZ), kaitkan dengan Target Group yang sama, aktifkan **ELB health check** dengan grace period 120 detik. Atur **desired 2, minimum 2, maksimum 4**. Kebijakan scaling: pilih **Target tracking scaling policy** (bukan *No scaling policies*), metrik *Average CPU utilization*, target 50%, instance warmup 120 detik. Pada langkah *Monitoring*, centang **Enable group metrics collection within CloudWatch**.
   **17a. Verifikasi ASG sebelum diberi beban** (jangan dilewati; penyebab paling sering scale-out tidak terjadi):
   - ASG, tab **Automatic scaling**: harus ada *Target tracking policy* dengan target 50. Bila kosong, tambahkan lewat *Create dynamic scaling policy*.
   - ASG, tab **Details**, bagian *Launch template*: versi yang dipakai adalah versi yang memiliki **Detailed CloudWatch monitoring** aktif. Pada instance ASG, tab **Monitoring** di EC2 menampilkan grafik per 1 menit. Bila Anda mengubah Launch Template setelah instance diluncurkan, instance lama tidak ikut berubah.
   - ASG, tab **Monitoring**, sub-tab *Auto Scaling* dan *EC2*: grafik muncul **2 sampai 10 menit** setelah instance berjalan. *No data* pada beberapa menit pertama itu normal; sub-tab *Auto Scaling* kosong selamanya bila group metrics collection belum diaktifkan.
   - Metrik **CPU** (dan jaringan serta disk I/O) tersedia tanpa agent, sedangkan **memori dan ruang disk tidak ada** karena CloudWatch Agent belum dipasang. Ini disengaja: Anda memasangnya sendiri pada Lab 5, pada instance tunggal dan pada ASG.
18. Target Group kini berisi empat target (dua manual, dua dari ASG). Setelah kedua instance ASG berstatus *healthy*, **deregister dan terminate** kedua instance manual. Alasannya: ASG hanya mengelola instance yang diluncurkannya, sehingga instance manual tidak akan diganti bila gagal. Tinggal dua instance yang dikelola ASG.

### C2. Terminate satu instance dan auto healing
19. Pada terminal kedua jalankan perulangan yang memantau situs: `while true; do curl -s -o /dev/null -w "%{http_code} " $ALB/id; sleep 2; done`. Terminate **satu** instance milik ASG (EC2 console).
20. Amati: situs tetap menjawab melalui instance lain, target yang dihentikan berstatus *draining*, tab *Activity* ASG menunjukkan peluncuran instance pengganti, dan **jumlah instance kembali ke 2** (sekitar 3 sampai 5 menit sampai pengganti healthy). Catat waktu yang dibutuhkan dan hubungkan dengan grace period health check.

### C3. Beban tinggi dan auto scaling
21. Jalankan `bash loadgen.sh cpu $ALB 6 300`. Hasilnya mencantumkan instance mana saja yang terkena beban; **pastikan kedua instance muncul** (bila hanya satu, ulangi perintah). Buka halaman `/` pada tiap instance (atau lihat grafik CPU instance): tertulis *Beban CPU: AKTIF* dan load average naik. Beban berlangsung 5 menit.
22. Pantau **CPUUtilization** (CloudWatch, per Auto Scaling group) dan tab *Activity* ASG. Target tracking membuat dua alarm `TargetTracking-<asg>-AlarmHigh/AlarmLow` (CloudWatch, Alarms); **AlarmHigh** perlu rata-rata CPU di atas target selama **3 datapoint berturut-turut**: sekitar 3 sampai 5 menit dengan detailed monitoring (1 menit) dan sampai 15 menit tanpa detailed monitoring (5 menit). Karena beban hanya 5 menit, detailed monitoring wajib agar sempat terdeteksi; bila ragu, jalankan ulang `cpu` dengan `600` detik. Setelah alarm aktif, **desired capacity naik** hingga paling banyak 4 dan instance baru bergabung ke Target Group. Jalankan `bash loadgen.sh fast $ALB 40 10` dan perhatikan sebaran kini melibatkan instance yang baru.
23. Hentikan beban: `curl $ALB/cpu/stop` (ulangi beberapa kali agar mengenai semua instance). Catat bahwa scale-in berjalan jauh lebih lambat daripada scale-out (target tracking menunggu CPU rendah cukup lama); jangan menunggu sampai selesai, lanjutkan ke Lab 5.
24. Gambarkan alur trafik dan alur health check, kemudian jawab: *alert apa yang seharusnya berbunyi pada setiap kegagalan di atas?* (dikerjakan di Lab 5).

## Validasi
Dua instance pada dua AZ melayani trafik lewat ALB, perbedaan sebaran antara round robin dan LOR terlihat pada node lambat, sticky mengunci sesi ke satu instance, instance ASG yang dihentikan diganti otomatis hingga kembali 2, dan desired capacity naik saat CPU tinggi.

## Pemecahan Masalah
| Gejala | Penyebab dan solusi |
|---|---|
| Target `unhealthy` | `web-sg-app` tidak mengizinkan trafik dari `alb-sg`, aplikasi belum berjalan (periksa `/var/log/lab-app-userdata.log` dan `systemctl status lab-app`), atau path health check bukan `/health` |
| ALB menampilkan 503 | Tidak ada target yang sehat |
| Tidak dapat memilih dua subnet | Kedua subnet harus berada di AZ yang berbeda |
| `loadgen.sh degrade` gagal setelah 40 percobaan | ID instance salah ketik, atau instance tersebut tidak sehat |
| `fast` sangat lama saat round robin | Wajar: separuh request menunggu 10 detik. Kurangi jumlah (`fast $ALB 20 10`) |
| Sebaran LOR tampak sama dengan round robin | Beban terlalu kecil atau pendek; naikkan paralelisme dan pastikan node lambat aktif (`/` menampilkan `degrade: 10000 ms`) |
| Sticky tidak bekerja | Klien tidak mengirim cookie (gunakan cookie jar pada `loadgen.sh session`), atau durasi terlalu pendek |
| ASG gagal meluncurkan instance | Periksa kuota, izin IAM (`iam:PassRole` untuk `lab-ec2-app`), serta AMI dan subnet pada tab Activity |
| Instance pengganti tidak muncul | Cek tab Activity; periksa health check type ELB dan grace period; instance manual tidak dikelola ASG |
| Scaling tidak terjadi setelah `/cpu` | Periksa berurutan: (1) ASG tab *Automatic scaling* memiliki target tracking policy; (2) alarm `TargetTracking-<asg>-AlarmHigh` ada dan statusnya bukan `INSUFFICIENT_DATA` (CloudWatch, Alarms); (3) beban benar-benar aktif di **semua** instance (halaman `/` menampilkan *Beban CPU: AKTIF*; grafik CPU instance mendekati 100%); (4) rata-rata CPU grup di atas 50% selama 3 datapoint berturut-turut (detailed monitoring), karena beban 2 menit atau satu instance saja tidak cukup (rata-rata grup dibagi dua instance); (5) maksimum belum tercapai dan tidak ada cooldown/warmup yang berjalan; (6) tab *Activity* tidak berisi galat peluncuran |
| Monitoring ASG atau instance *No data* | Instance baru butuh 2 sampai 10 menit; metrik per menit hanya bila Launch Template (versi yang dipakai ASG) mengaktifkan *Detailed CloudWatch monitoring*; sub-tab *Auto Scaling* kosong bila *group metrics collection* belum diaktifkan; pastikan rentang waktu grafik cukup (3 jam) dan Region benar. Cek dari CloudShell: `aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization --dimensions Name=AutoScalingGroupName,Value=<asg> --start-time $(date -u -d '-15 min' +%FT%TZ) --end-time $(date -u +%FT%TZ) --period 60 --statistics Average` dan `aws ec2 describe-instances --query 'Reservations[].Instances[].[InstanceId,Monitoring.State]'` (harus `enabled`) |
| Muncul pesan `Access denied` pada `iam:CreateServiceLinkedRole` | Trainer membuat service-linked role untuk ELB dan Auto Scaling satu kali |

## Cleanup
Resource lab ini **tetap dipertahankan** sampai Lab 5 dan Lab 6 selesai (keduanya memakai stack ini). Penghapusan dilakukan pada akhir Hari 2 dengan urutan: 1. ASG (instance ikut terhapus). 2. ALB. 3. Target Group. 4. Launch Template. 5. Security Group. 6. Alarm, dashboard, metric filter, instance `mon-solo-<nama>`, dan parameter SSM `AmazonCloudWatch-lab-app-<nama>` (Lab 5 dan 6). Topik SNS dan log group `/lab/lab-app` dipertahankan sampai Lab 10. **Trainer memeriksa EC2 Instances, Load Balancers, Volumes, dan Elastic IP pada Region yang dipakai sebelum peserta pulang.**
