# lab-app: aplikasi untuk lab Hari 2 dan 3

Aplikasi web kecil (Python 3, satu file) yang dipakai pada Lab 4 (ALB dan ASG), Lab 5 (Monitoring), Lab 6 (DocumentDB dan X-Ray), serta Lab 8 (Hybrid). Aplikasi ini sengaja dibuat agar dapat **memicu** kondisi yang biasa dijumpai dalam operasi: request panjang, CPU tinggi, error 5xx, instance tidak sehat, dan query lambat.

> **Status:** diuji secara lokal pada mode `DB_MODE=mock` (endpoint, `loadgen.sh`, ukuran User Data). **Belum diuji di AWS**: instalasi paket pada Amazon Linux 2023, CloudWatch Agent, ekspor trace, DocumentDB, dan PostgreSQL on-prem. Lakukan dry-run (lihat `04-setup/Instructor-Setup-Checklist.md`).

## Berkas
| Berkas | Fungsi |
|---|---|
| `lab-app.py` | Aplikasi. Hanya library standar untuk fitur inti; `boto3`, `pymongo`, `psycopg2`, dan OpenTelemetry bersifat opsional. |
| `user-data.template.sh` | Templat User Data (instalasi dan systemd). **Tanpa CloudWatch Agent**: peserta memasangnya pada Lab 5 (instance tunggal) dan Lab 6 (ASG). |
| `cwagent/` | Konfigurasi agent (`agent-config.v1.json`, `agent-config.v2-traces.json`) dan potongan User Data untuk ASG; lihat `cwagent/README.md`. |
| `build-userdata.py` | Menggabungkan templat dan aplikasi (gzip + base64 karena batas User Data 16 KB). Jalankan `python build-userdata.py` setelah mengubah `lab-app.py`. |
| `user-data.lab4.sh` | Hasil build untuk **Lab 4** (dan instance tunggal Lab 5): tanpa library tambahan, `TRACING=off`. |
| `user-data.lab6.sh` | Hasil build untuk **Lab 6 dan 8**: library tambahan, `TRACING=on`, `DB_MODE=docdb`. Pada Lab 6, peserta mengubah tiga nilai KONFIGURASI pada versi Launch Template yang dipakai ASG dan menambahkan dua perintah agent (`cwagent/userdata-agent-snippet.sh`) di akhir User Data. |
| `loadgen.sh` | Generator beban (bash, curl, xargs). |
| `seed-orders.py` | Trainer mengisi koleksi `orders` di DocumentDB (tanpa indeks). |

## Endpoint
| Endpoint | Fungsi | Dipakai untuk |
|---|---|---|
| `/` | Halaman: instance, AZ, jumlah request, in-flight | Melihat instance mana yang melayani |
| `/id` | Teks satu baris `instance-id az` | Penghitungan sebaran di `loadgen.sh` |
| `/health` | 200, atau 503 setelah `/health/fail` | Health check ALB; `/health/ok` memulihkan |
| `/slow?ms=10000` | Tidur sebanyak `ms` (bawaan 10 detik, maks 60000) | **Long request**: menahan satu request tetap *outstanding*; terlihat pada in-flight di `/` |
| `/degrade?ms=10000&only=<instance-id>` | Menambah `ms` (bawaan 10 detik) pada setiap request di SATU instance (`/degrade/off` memulihkan) | Simulasi node lambat untuk demo **least outstanding requests** |
| `/cpu?seconds=300&workers=2` | Membakar CPU di proses terpisah (bawaan 300 detik); status tampil di `/` (Beban CPU); `/cpu/stop` menghentikan | Memicu **scale-out** dan alarm CPU |
| `/session` | Penghitung sesi di memori + cookie `labsess` | Demo **sticky session** |
| `/error` | HTTP 500 + log `ERROR` | Alarm 5xx, metric filter |
| `/notes?u=nama` | GET daftar, POST simpan dokumen (`?text=` atau JSON) di DocumentDB | Lab 6 Bagian A |
| `/checkout?u=nama` | Alur: `validate`, `db.find` (query pada `orders`), `payment.call` (±300 ms), `render`; respons memuat waktu tiap langkah | Lab 6 Bagian B (X-Ray) |
| `/admin/index?u=nama` | Membuat indeks `customer_id` (`/admin/index/drop` menghapus) | Perbaikan titik lambat |
| `/customers` | Membaca `customers_masked` dari PostgreSQL on-prem | Lab 8 |

Halaman `/` menampilkan status instance dan tabel yang sama (endpoint, fungsi, contoh); daftarnya ada di variabel `ENDPOINTS` pada `lab-app.py`, jadi ubah di sana lalu jalankan `python build-userdata.py`. Setiap respons membawa header `X-Instance-Id`. Log JSON ditulis ke `/var/log/lab-app.log`.

## Variabel (bagian KONFIGURASI di User Data)
`TRACING` (on/off), `EXTRAS` (yes/no), `DB_MODE` (docdb/mock), `DOCDB_SECRET`, `PG_SECRET`, `REGION`. Secret DocumentDB: `{"username","password","host","port"}`. Secret PostgreSQL: `{"username","password","host","port","dbname"}`. Kredensial **tidak** ditulis di kode atau User Data; instance mengambilnya lewat IAM role `lab-ec2-app`.

## Uji lokal
```bash
cd 06-app
PORT=8081 DB_MODE=mock LOG_FILE=/tmp/lab-app.log python lab-app.py &
bash loadgen.sh fast http://127.0.0.1:8081 20 5
curl "http://127.0.0.1:8081/checkout"     # db_find ±900 ms (mock: tanpa indeks)
curl "http://127.0.0.1:8081/admin/index"  # lalu /checkout lagi: db_find ±20 ms
```
Di luar EC2, startup memerlukan sekitar 2 detik karena pencarian metadata instance.

## Skenario demo
1. **Least outstanding requests:** `./loadgen.sh degrade <ALB> <instance-id> 10000` membuat satu instance lambat (10 detik per request). Jalankan `./loadgen.sh fast <ALB> 40 10` pada round robin (sebaran sekitar 50/50, latensi rata-rata tinggi), ubah target group menjadi `least_outstanding_requests`, lalu ulangi (instance lambat menerima lebih sedikit request, latensi turun). Pulihkan dengan `recover`.
2. **Sticky:** `./loadgen.sh session <ALB> 10` sebelum dan sesudah stickiness diaktifkan.
3. **Autoscale:** `./loadgen.sh cpu <ALB> 6 300`, pantau CPU ASG dan aktivitas ASG.
4. **Alert:** `curl <ALB>/error`, `curl <ALB>/health/fail`, `./loadgen.sh cpu`.
5. **Titik lambat:** `./loadgen.sh checkout <ALB> 60 4 nama`, analisis di X-Ray, lalu `curl "<ALB>/admin/index?u=nama"` dan ulangi.
