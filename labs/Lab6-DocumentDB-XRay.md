# Lab 6: DocumentDB terhubung ke Aplikasi dan Analisis Titik Lambat dengan X-Ray (75 menit, Hari 2)

**Tujuan:** Bagian A: peserta mengaktifkan penerima trace pada CloudWatch Agent (mengubah konfigurasi di Parameter Store), lalu aplikasi pada ASG memakai Amazon DocumentDB (API MongoDB) tanpa kredensial di kode, dan peserta memahami perbedaan state di instance dengan state di database. Bagian B: peserta membangun dashboard kinerja kustom, menelusuri request lambat dengan X-Ray, menemukan segmen yang paling lama, memperbaiki yang bisa diperbaiki, dan membuktikan perbaikan dari trace dan dashboard.
**Biaya:** satu cluster DocumentDB (satu instance db.t3.medium, sekitar $0,1 per jam) dibuat dan dihapus oleh trainer; X-Ray gratis untuk 100.000 trace pertama per bulan per akun (lab ini menghasilkan beberapa ribu trace); dashboard kedua masih dalam tiga dashboard gratis per akun. Peserta tidak membuat DocumentDB.
**Status:** belum diuji pada akun AWS yang sebenarnya (User Data dengan paket tambahan, koneksi DocumentDB, penerima OTLP pada agent, ekspor trace, metric filter dari `$.ms`). Trainer melakukan dry-run dan menyiapkan tangkapan layar service map dan trace sebagai cadangan.

## Prasyarat
Lab 5 selesai: agent terpasang pada `mon-solo-<nama>` dan pada ASG (melalui Launch Template), parameter `AmazonCloudWatch-lab-app-<nama>` berisi konfigurasi versi 1, topik SNS dan dashboard `ops-<nama>` ada.

## Endpoint `lab-app` yang Dipakai
Daftar lengkap ada di `Lab4-HA-WebApp.md` (Referensi Endpoint).
| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/notes?u=<nama>` | GET membaca dan POST menyimpan catatan di DocumentDB (Bagian A); membuktikan data berada di database, bukan di memori instance |
| `/checkout?u=<nama>` | Alur `validate`, `db.find`, `payment.call`, `render` yang dianalisis di X-Ray; `steps_ms` pada respons menunjukkan waktu tiap langkah (Bagian B) |
| `/admin/index?u=<nama>` dan `/admin/index/drop?u=<nama>` | Membuat dan menghapus indeks `customer_id` untuk membuktikan perbaikan dan mengulang percobaan |
| `/` | Memastikan `tracing: on` setelah instance refresh |

## Persiapan Trainer (dilakukan sebelum kelas)
- Buat cluster DocumentDB `lab-docdb` di **default VPC** (satu instance, db.t3.medium, TLS aktif). Security Group `docdb-sg` mengizinkan port 27017 dari CIDR default VPC (`172.31.0.0/16`). Cluster tidak dapat diakses dari internet.
- Simpan kredensial di Secrets Manager dengan nama `lab/docdb`, berisi `{"username","password","host","port"}` (host berisi cluster endpoint). Jangan menulis nilai ini di materi atau repo.
- Role `lab-ec2-app` memiliki `secretsmanager:GetSecretValue` terbatas pada secret itu serta `AWSXRayDaemonWriteAccess` dan `CloudWatchAgentServerPolicy`.
- Isi koleksi `orders` untuk setiap peserta tanpa indeks dengan `06-app/seed-orders.py` (sekitar 50.000 dokumen per peserta). **Targetkan kueri `/checkout` tanpa indeks memerlukan sekitar satu detik atau lebih**; sesuaikan `--docs` saat dry-run.
- Pastikan fitur trace aktif sesuai catatan di `04-setup/Instructor-Setup-Checklist.md` (CloudWatch Agent menerima OTLP, aturan sampling lab merekam seluruh request `/checkout`, Transaction Search bila dipakai). Konfigurasi OTLP kini dipasang peserta sendiri pada langkah 3 lewat `06-app/cwagent/agent-config.v2-traces.json`.
- Peserta dapat melihat metrik `AWS/DocDB` (izin baca CloudWatch) untuk dashboard Bagian B.

## Bagian A: Agent, DocumentDB, dan aplikasi (38 menit)
1. **Kenali cluster.** Trainer menunjukkan halaman cluster `lab-docdb`: cluster endpoint dan reader endpoint, replica set, Multi-AZ, backup, parameter TLS. Diskusikan: bagian mana yang dikelola AWS dan bagian mana yang tetap menjadi tanggung jawab Anda (data, akses, kueri, indeks).
2. **Cara aplikasi mendapat kredensial.** Buka IAM, Roles, `lab-ec2-app`, dan baca policy JSON-nya. Buka Secrets Manager dan lihat bahwa secret `lab/docdb` ada (peserta tidak membaca isinya). Aplikasi mengambil secret saat berjalan, sehingga tidak ada kata sandi di kode, User Data, atau Launch Template.
3. **Aktifkan penerima trace pada agent (8 menit).** Agent yang Anda pasang di Lab 5 hanya mengirim metrik dan log. Untuk menerima trace dari aplikasi (OpenTelemetry), tambahkan penerima OTLP pada konfigurasi.
   a. Buka Systems Manager, Parameter Store, `AmazonCloudWatch-lab-app-<nama>`, **Edit**. Tambahkan blok `traces` sebagai anggota terakhir objek JSON (perhatikan koma pada penutup `logs` sebelumnya; hasil lengkap ada di `06-app/cwagent/agent-config.v2-traces.json`):
      ```json
        },
        "traces": { "traces_collected": { "otlp": { "http_endpoint": "127.0.0.1:4318" } } }
      }
      ```
      Simpan. Parameter kini memiliki **versi 2** (lihat tab *History*); versi 1 tetap tersimpan dan dapat dikembalikan bila konfigurasi baru salah.
   b. Pada `mon-solo-<nama>` (SSH), minta agent membaca ulang konfigurasi dan buktikan penerima aktif:
      ```bash
      sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c ssm:AmazonCloudWatch-lab-app-<nama> -s
      sudo ss -ltn | grep 4318
      ```
      Port 4318 mendengarkan di `127.0.0.1`. Hanya aplikasi di mesin yang sama yang dapat mengirim trace ke sana.
   c. **Instance ASG belum berubah.** Parameter diubah, tetapi agent hanya membaca konfigurasi saat `fetch-config` dijalankan atau saat instance baru menyala. Instance ASG akan menerima konfigurasi baru lewat instance refresh pada langkah 5. Pada armada besar, trainer menunjukkan cara lain secara teori: SSM Run Command atau State Manager (dokumen `AmazonCloudWatch-ManageAgent`).
4. **Launch Template versi baru.** Buka Launch Template `lt-app-<nama>`, Actions, Modify template (Create new version) dengan *Source template version* = **versi Lab 5** (yang sudah memuat dua perintah agent di akhir User Data). Pada User data, ubah **hanya tiga nilai** di bagian KONFIGURASI: `TRACING=on`, `EXTRAS=yes`, `DB_MODE=docdb`. Jangan menghapus bagian agent di akhir. (Hasilnya setara `user-data.lab6.sh` ditambah dua perintah agent.) Jadikan versi ini default.
5. **Instance refresh.** Pada ASG, tab *Instance refresh*, Start: minimum healthy percentage 50% dan instance warmup 120 detik. Instance diganti bergiliran sehingga situs tetap hidup (sekitar 8 sampai 10 menit). Instance baru memasang paket tambahan, membaca **parameter versi 2** saat agent mulai, sehingga langsung menerima trace. Sambil menunggu, jawab: apa bedanya refresh dengan menghentikan semua instance sekaligus, dan metrik apa yang akan Anda pantau selama deployment?
6. **Uji aplikasi.** Setelah dua instance baru sehat, di CloudShell: `curl -X POST "$ALB/notes?u=<nama>&text=halo-1"` beberapa kali dengan teks berbeda, kemudian `curl "$ALB/notes?u=<nama>"`. Perhatikan bahwa `served_by` berganti-ganti tetapi **semua catatan terlihat dari instance mana pun**, berbeda dengan penghitung `/session` di Lab 4 yang hilang saat berpindah instance. Inilah yang dimaksud dengan state di luar instance (stateless).
7. Terminate satu instance, tunggu pengganti sehat, dan baca kembali `/notes`: data tetap ada. Pengganti juga otomatis memasang agent dengan konfigurasi terbaru, karena semuanya ada di Launch Template dan Parameter Store.
8. **Diskusi Atlas** (5 menit; rincian pada sesi Database dan `05-learn/DocumentDB-Atlas`): jika data berada di MongoDB Atlas yang berjalan di atas AWS dan dibeli lewat AWS Marketplace, bagian mana dari aplikasi ini yang berubah? Hanya connection string dan jalur jaringan (IP access list, peering, atau PrivateLink), serta cara kredensial didapat (user database atau AWS IAM role). Marketplace hanya mengubah **penagihan** (biaya Atlas muncul di tagihan AWS), bukan identitas atau akses ke cluster. Tanyakan: siapa yang memegang langganan Marketplace dan siapa yang memegang organization Atlas di tim Anda, dan di mana Anda melihat rincian biayanya?

## Bagian B: Dashboard kinerja dan analisis titik lambat dengan X-Ray (37 menit)
9. **Siapkan pengukuran kinerja (7 menit).** Sebelum membuat beban, buat dua hal agar data baseline tercatat.
   a. **Metric filter.** CloudWatch, Log groups, `/lab/lab-app`, tab *Metric filters*, Create: pola `{ $.path = "/checkout" }`, metric namespace `LabApp`, nama `CheckoutLatency`, **metric value** `$.ms`, unit *Milliseconds*. Setiap request `/checkout` kini menghasilkan satu titik data latensi dari log. (Filter hanya memproses log yang masuk **setelah** dibuat.)
   b. **Dashboard `perf-<nama>`.** Buat dashboard baru dengan lima widget:
      | # | Jenis | Isi |
      |---|---|---|
      | 1 | **Line** | `LabApp/CheckoutLatency` dengan dua baris: statistik **p50** dan **p95**, period 1 menit |
      | 2 | **Line** | `TargetResponseTime` ALB, statistik **p95** (ApplicationELB, LoadBalancer) |
      | 3 | **Line** | Metrik DocumentDB (`AWS/DocDB`, `DBInstanceIdentifier` = instance `lab-docdb`): `CPUUtilization`, `DatabaseConnections` |
      | 4 | **Logs table** | Query: `filter path = "/checkout" \| sort ms desc \| limit 10` pada `/lab/lab-app` (10 request paling lambat) |
      | 5 | **Text** | Judul, ringkasan hipotesis (mis. "db.find tanpa indeks"), dan tautan ke konsol X-Ray (CloudWatch, Application Signals / X-Ray traces) |
      Simpan. Widget belum menampilkan data sampai Anda menjalankan beban.
10. **Pastikan tracing aktif dan ambil baseline.** Buka `$ALB/` dan periksa tulisan `tracing: on`. Jalankan beban: `bash loadgen.sh checkout $ALB 60 4 <nama>` dan catat rata-rata serta p95 dari `loadgen.sh` sebagai **baseline sebelum perbaikan**. Respons `/checkout` juga memuat `steps_ms` (waktu tiap langkah) sebagai pembanding terhadap trace. Setelah 1 sampai 2 menit, lihat dashboard `perf-<nama>`: kurva `CheckoutLatency` p95 tinggi dan konstan.
11. **Service map.** Buka CloudWatch (atau X-Ray) dan pilih *Service map* / *Traces*. Anda melihat node `lab-app`, node database (`mongodb`), dan node layanan pembayaran eksternal. Catat latensi rata-rata tiap node. *ALB tidak muncul sebagai node*: ALB hanya menambahkan header `X-Amzn-Trace-Id` yang diteruskan aplikasi.
12. **Daftar trace.** Buka daftar *Traces*, saring request lambat (filter `responsetime > 1` atau `http.route = "/checkout"`), urutkan berdasarkan response time, dan buka satu trace.
13. **Baca timeline.** Identifikasi setiap segmen: `validate`, `db.find orders`, `payment.call`, dan `render`. Jawab: segmen mana yang paling lama? Berapa persen dari total waktu? Mana yang berada di dalam aplikasi, mana yang di database, dan mana yang di layanan pihak ketiga?
14. **Bandingkan.** Buka dua atau tiga trace lain dan lihat apakah polanya konsisten. Periksa anotasi atau atribut `instance_id`: apakah masalah hanya ada di satu instance atau di semuanya? Lihat distribusi response time (histogram) dan bedakan rata-rata dengan p95.
15. **Tentukan tindakan.** Mana yang dapat diperbaiki oleh tim Anda (kueri tanpa indeks pada `customer_id`), dan mana yang tidak (waktu panggilan pihak ketiga; pilihannya hanya timeout, retry terbatas, circuit breaker, atau dibuat asinkron)?
16. **Perbaiki dan buktikan.** Jalankan `curl "$ALB/admin/index?u=<nama>"` untuk membuat indeks. Ulangi langkah 10 dengan jumlah request yang sama. Bandingkan di **dua tempat**: dashboard `perf-<nama>` (kurva p95 `CheckoutLatency` turun tajam; `TargetResponseTime` ikut turun) dan trace (segmen `db.find orders` turun drastis, sedangkan `payment.call` tidak berubah dan kini menjadi segmen terlama). Catat rata-rata dan p95 baru. Dashboard menjawab *apakah membaik*; trace menjawab *bagian mana yang membaik*. Untuk mengulang percobaan, jalankan `curl "$ALB/admin/index/drop?u=<nama>"`.
17. **Error dan fault.** Jalankan `for i in $(seq 10); do curl -s -o /dev/null $ALB/error; done`, lalu cari trace berstatus error pada service map (node berwarna merah/oranye). Diskusikan perbedaan *error* (4xx), *fault* (5xx), dan *throttle*.
18. **Diskusi** (lihat `05-learn/Monitoring-Alerting`): metrik menjawab *apakah ada masalah*, log menjawab *apa yang terjadi*, trace menjawab *di mana waktunya habis*. Bahas sampling (aturan default merekam 1 request per detik ditambah 5%; lab memakai aturan khusus agar semua `/checkout` terekam), biaya trace (per juta trace direkam), anotasi dibandingkan metadata, dan mengapa instrumentasi memakai OpenTelemetry (SDK dan daemon X-Ray lama sudah masuk maintenance mode). Satu agent kini melayani metrik, log, dan trace dari konfigurasi yang sama di Parameter Store.

## Bagian C: Demo trainer DynamoDB (5 menit, pada sesi Database)
Trainer membuat tabel `Students-demo` (partition key `StudentId`, On-demand), menambahkan beberapa item dengan atribut berbeda, menjalankan Query dan Scan, serta menunjukkan GSI. Bandingkan dengan DocumentDB: DynamoDB bersifat serverless dan memakai IAM (tanpa kata sandi), sedangkan DocumentDB kompatibel dengan driver MongoDB tetapi berjalan di cluster dalam VPC. Hapus tabel setelah demo.

## Validasi
Port 4318 mendengarkan pada instance tunggal setelah parameter versi 2, `/notes` mengembalikan data yang sama dari kedua instance, service map menampilkan node database dan layanan eksternal, dashboard `perf-<nama>` menampilkan p95 sebelum dan sesudah indeks, peserta dapat menunjukkan segmen terlama pada sebuah trace, dan trace setelah pembuatan indeks membuktikan bahwa segmen `db.find` turun.

## Pemecahan Masalah
| Gejala | Penyebab dan solusi |
|---|---|
| Instance refresh gagal atau target `unhealthy` | User Data gagal (cek `/var/log/lab-app-userdata.log`), paket tidak terpasang, atau role tidak dapat membaca secret; ASG akan menahan refresh |
| `/notes` mengembalikan 500 atau timeout | `docdb-sg` tidak mengizinkan 27017 dari VPC, secret salah, atau CA bundle tidak terunduh (`/opt/lab-app/global-bundle.pem`); lihat log aplikasi |
| `AccessDenied` pada Secrets Manager | `lab-ec2-app` belum memiliki `secretsmanager:GetSecretValue` untuk `lab/docdb` |
| Port 4318 tidak mendengarkan | Parameter masih versi 1 atau JSON tidak valid (`amazon-cloudwatch-agent.log`), atau `fetch-config` belum dijalankan ulang pada instance itu. Kembalikan ke versi 1 bila perlu |
| Instance ASG tidak mengirim trace padahal instance tunggal bisa | Instance belum diganti oleh refresh (masih konfigurasi lama), atau versi Launch Template tidak memuat dua perintah agent di akhir User Data |
| Service map kosong | Tracing belum aktif (`tracing: off`), penerima OTLP belum aktif (lihat baris port 4318), role tanpa `AWSXRayDaemonWriteAccess`, atau data belum muncul (tunggu 1 sampai 2 menit) |
| Hanya sebagian request muncul sebagai trace | Aturan sampling default; trainer mengatur aturan sampling lab |
| Metrik `CheckoutLatency` kosong | Metric filter dibuat setelah beban dijalankan, pola salah (`$.path = "/checkout"`), atau nilai bukan `$.ms`; ulangi beban |
| Widget DocumentDB kosong | `DBInstanceIdentifier` salah (gunakan nama instance, bukan nama cluster) atau Region tidak sama |
| `db.find` tidak lambat sebelum indeks | Dokumen terlalu sedikit; trainer menambah `--docs` pada `seed-orders.py` |
| Peserta saling menimpa data | Gunakan parameter `u=<nama>` yang berbeda untuk setiap peserta |

## Cleanup
Trainer menghapus cluster DocumentDB (tanpa final snapshot), secret `lab/docdb`, dan tabel DynamoDB demo. Peserta menghapus stack Lab 4 dan 5 sesuai urutan pada bagian Cleanup di `Lab4-HA-WebApp.md` dan `Lab5-Monitoring-Alerting.md` (termasuk instance `mon-solo-<nama>` dan parameter `AmazonCloudWatch-lab-app-<nama>`), serta metric filter `CheckoutLatency`. Dashboard `ops-<nama>` dan `perf-<nama>` boleh disimpan.
