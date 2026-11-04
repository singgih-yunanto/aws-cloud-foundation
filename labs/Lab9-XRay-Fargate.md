# Lab 9: Menelusuri Request Lambat dengan X-Ray pada Task Fargate (40 menit, Hari 3)

**Tujuan:** peserta menambahkan **sidecar ADOT** (AWS Distro for OpenTelemetry collector) ke task definition, mengaktifkan tracing pada aplikasi, membangun dashboard kinerja kustom, menelusuri request `/checkout` yang lambat di X-Ray (service map, daftar trace, timeline), menemukan segmen yang paling lama, memperbaikinya lewat **deployment** yang tercatat, dan membuktikan perbaikan dari dashboard dan trace. Peserta juga menentukan apa yang perlu diminta ke vendor agar tracing dapat dipakai tim operasi.

**Biaya:** X-Ray gratis untuk 100.000 trace pertama per bulan per akun (lab ini menghasilkan beberapa ribu trace); task bertambah menjadi 0,5 vCPU / 1 GB selama lab; dashboard di atas tiga pertama per akun berbayar sekitar $3 per bulan secara prorata per jam (hapus pada akhir hari).

**Status:** belum diuji pada akun AWS yang sebenarnya (sidecar ADOT dan konfigurasi bawaannya, ekspor trace ke X-Ray dari Fargate, bentuk service map, metric filter dari `$.ms`). Trainer melakukan dry-run dan menyiapkan tangkapan layar service map dan trace sebagai cadangan.

## Prasyarat
- Lab 7 dan 8 selesai: service `svc-app-<nama>` berjalan pada revisi `v2` (2 task), ALB `alb-ecs-<nama>` melayani, `ALB=http://<DNS>` terisi di CloudShell.
- Task role `lab-ecs-task` (disiapkan trainer) memiliki `AWSXRayDaemonWriteAccess`. Trainer sudah mengatur aturan sampling lab agar seluruh request `/checkout` direkam.
- `loadgen.sh` ada di CloudShell (dari Lab 4); bila hilang, ambil dari `06-app/loadgen.sh`.

## Endpoint `lab-app` yang Dipakai

| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/checkout?u=<nama>` | Alur `validate`, `db.find orders` (simulasi: ±900 ms tanpa indeks, ±20 ms dengan indeks), `payment.call` (±320 ms), `render`; respons memuat `steps_ms` |
| `/error` | Menghasilkan trace berstatus fault (5xx) |
| `/version`, `/` | Memastikan versi dan `tracing: on` |

## Bagaimana trace sampai ke X-Ray

```
 ALB --(X-Amzn-Trace-Id)--> task Fargate (awsvpc, satu jaringan untuk semua container)
                              ├─ container app  --OTLP http 127.0.0.1:4318-->  ┐
                              └─ container adot-collector  <------------------┘  --> AWS X-Ray
                                   (memakai task role lab-ecs-task)
```

Dalam mode awsvpc seluruh container satu task berbagi `localhost`, sehingga aplikasi cukup mengirim ke `127.0.0.1:4318` (alamat bawaan) dan collector meneruskan ke X-Ray memakai **task role**. Tidak ada perubahan kode aplikasi; yang berubah hanya task definition.

## Langkah
1. **Rancang perubahan (3 menit).** Buka `06-app/ecs/task-definition.v2-adot.json` (dari trainer) dan baca: container `app` dengan `TRACING=on`, container `adot-collector` dengan perintah `--config=/etc/ecs/ecs-default-config.yaml`, kedua log, dan ukuran task 0,5 vCPU / 1 GB. Diskusi: mengapa sidecar harus `essential`, dan apa yang terjadi pada tracing bila collector mati? (Task ikut dihentikan; bandingkan dengan collector yang tidak essential.)

2. **Task definition revisi baru (8 menit).** ECS, Task definitions, `td-app-<nama>`, revision terbaru (`v2`), **Create new revision**.
   - **a.** Naikkan *Task size* menjadi CPU **.5 vCPU**, Memory **1 GB**.
   - **b.** Container `app`: pada *Resource allocation limits* isi CPU **.25** dan Memory (hard limit) **.5 GB**. Tambahkan variabel `TRACING` = `on` (ubah dari `off`). Pada *Container dependencies* tambahkan `adot-collector` dengan kondisi **START**.
   - **c.** **Add container**: *Name* `adot-collector`, *Image URI* `public.ecr.aws/aws-observability/aws-otel-collector:latest`, *Essential* **Yes**, CPU **.25** dan Memory **.5 GB**. Pada *Docker configuration* isi *Command* `--config=/etc/ecs/ecs-default-config.yaml`. Logging: awslogs dengan `awslogs-group` `/ecs/adot-<nama>`, region `ap-southeast-3`, prefix `adot`, `awslogs-create-group` `true`.
   - **d.** **Create**. Jalan pintas bila kewalahan: **Create new revision with JSON**, tempel isi `task-definition.v2-adot.json` dengan `<nama>` dan `<ACCOUNT_ID>` diganti.

   **Checkpoint:** revisi baru berisi dua container, `TRACING=on`, dan task size 0,5 vCPU / 1 GB.

3. **Deploy (5 menit).** Update service `svc-app-<nama>` ke revisi baru. Selama menunggu: apa risiko deployment yang menambah ukuran task (kapasitas, biaya, kuota), dan di mana Anda melihatnya (Lab 8)?

   **Checkpoint:** setiap task menampilkan **dua container Running**; target group 2 healthy; `curl -s $ALB/ | grep -o 'tracing: [a-z]*'` menampilkan `tracing: on`. Log `/ecs/adot-<nama>` menampilkan collector mulai tanpa error `AccessDenied` (bila ada, task role belum benar).

4. **Siapkan pengukuran kinerja (6 menit).** Sebelum membuat beban, buat dua hal agar baseline tercatat.
   - **a.** **Metric filter.** CloudWatch, Log groups, `/ecs/lab-app-<nama>`, tab *Metric filters*, Create: pola `{ $.path = "/checkout" }`, metric namespace `LabApp`, nama `CheckoutLatency`, **metric value** `$.ms`, unit *Milliseconds*. (Filter hanya memproses log yang masuk **setelah** dibuat.)
   - **b.** **Dashboard `perf-<nama>`** dengan lima widget:

      | # | Jenis | Isi |
      |---|---|---|
      | 1 | **Line** | `LabApp/CheckoutLatency`, statistik **p50** dan **p95**, period 1 menit |
      | 2 | **Line** | `TargetResponseTime` ALB, statistik **p95** |
      | 3 | **Line** | `CPUUtilization` dan `MemoryUtilization` service (AWS/ECS) |
      | 4 | **Logs table** | `filter path = "/checkout" \| sort ms desc \| limit 10` pada `/ecs/lab-app-<nama>` (10 request paling lambat) |
      | 5 | **Text** | Judul, hipotesis (mis. "db.find tanpa indeks"), versi aplikasi, dan tautan ke X-Ray |

5. **Ambil baseline.** Di CloudShell: `bash loadgen.sh checkout $ALB 60 4 <nama>` (60 request, 4 paralel). Catat rata-rata dan p95 dari `loadgen.sh` sebagai **baseline sebelum perbaikan**. Respons `/checkout` memuat `steps_ms` (waktu tiap langkah). Setelah 1 sampai 2 menit, di dashboard `perf-<nama>` kurva p95 `CheckoutLatency` tinggi dan konstan.

6. **Service map (3 menit).** CloudWatch (Application Signals / X-Ray traces), *Trace map* atau *Service map*. Anda melihat node `lab-app` dan node tujuan yang diwakili span CLIENT (database tiruan dan layanan pembayaran). Nama persis node bergantung pada atribut span; catat yang Anda lihat dan latensi rata-rata tiap node. *ALB tidak muncul sebagai node*: ALB hanya menambahkan header `X-Amzn-Trace-Id` yang diteruskan aplikasi.

7. **Daftar trace dan timeline (5 menit).** Buka *Traces*, saring request lambat (filter `responsetime > 1`), urutkan berdasarkan response time, dan buka satu trace.
   - **a.** Identifikasi segmen `validate`, `db.find orders`, `payment.call`, dan `render`. Jawab: segmen mana yang paling lama dan berapa persen dari total? Mana yang di aplikasi, mana yang di database, mana yang di layanan pihak ketiga?
   - **b.** Buka dua atau tiga trace lain: konsisten? Pada *Metadata/Annotations* periksa `instance_id` (ID task): masalah ada di satu task atau semua? Bedakan rata-rata dengan p95 pada histogram.
   - **c.** Tentukan tindakan: mana yang dapat diperbaiki oleh tim aplikasi (kueri tanpa indeks), dan mana yang tidak (panggilan pihak ketiga; pilihannya timeout, retry terbatas, circuit breaker, atau asinkron)?

8. **Perbaiki lewat deployment yang tercatat (5 menit).** Di database sungguhan, perbaikannya adalah membuat indeks. Pada lab ini basis datanya tiruan per task, sehingga perbaikan **dikirim sebagai rilis**: buat revisi baru dari revisi tracing dengan variabel `MOCK_INDEXED` = `yes` dan `APP_VERSION` = `v2.2`, lalu update service. Ini sengaja: perubahan yang memengaruhi kinerja harus bisa dilacak (versi baru terlihat di log, CloudTrail, dan email EventBridge dari Lab 8).

   Ulangi langkah 5 dengan jumlah request yang sama. Bandingkan di **dua tempat**: dashboard `perf-<nama>` (p95 `CheckoutLatency` turun tajam, `TargetResponseTime` ikut turun) dan trace (segmen `db.find orders` turun drastis; `payment.call` kini menjadi segmen terlama). Dashboard menjawab *apakah membaik*; trace menjawab *bagian mana yang membaik*.

   **Checkpoint:** angka baru dibandingkan baseline dan sekurang-kurangnya satu trace sesudah perbaikan.

9. **Error dan fault (2 menit).** `for i in $(seq 10); do curl -s -o /dev/null $ALB/error; done`, lalu cari trace berstatus error pada service map (node berwarna merah/oranye). Diskusikan *error* (4xx), *fault* (5xx), dan *throttle*.

10. **Diskusi: apa yang perlu diminta ke vendor (3 menit).** Tracing tidak dapat dinyalakan oleh tim operasi saja. Susun daftar:
    - *Instrumentasi dan sidecar:* perubahan task definition dan aplikasi adalah pekerjaan vendor (change request). Apa yang Anda tulis di permintaannya (tujuan, dampak biaya, ukuran task)?
    - *Akses baca:* `AWSXrayReadOnlyAccess` atau izin spesifik `xray:GetServiceGraph`, `xray:GetTraceSummaries`, `xray:BatchGetTraces`, `xray:GetTraceGraph`.
    - *Sampling dan biaya:* aturan sampling (bawaan 1 request per detik ditambah 5%), biaya per juta trace; lab memakai aturan khusus agar semua `/checkout` terekam.
    - Mengapa OpenTelemetry dan bukan SDK/daemon X-Ray lama (sudah maintenance mode), dan mengapa log, metrik, dan trace dipakai bersama: metrik menjawab *apakah ada masalah*, log menjawab *apa yang terjadi*, trace menjawab *di mana waktunya habis*.

## Validasi
Setiap task menjalankan dua container, service map menampilkan `lab-app` dan node tujuannya, dashboard `perf-<nama>` menampilkan p95 sebelum dan sesudah perbaikan, peserta dapat menunjukkan segmen terlama pada sebuah trace, dan revisi `v2.2` terlihat pada log (field `version`) serta di CloudTrail.

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| Task berhenti segera setelah revisi baru | Sidecar `essential` gagal start (cek log `/ecs/adot-<nama>`), memori total container melebihi ukuran task, atau perintah `--config` salah |
| Log collector berisi `AccessDenied` ke X-Ray | Task role bukan `lab-ecs-task` atau tidak memiliki `AWSXRayDaemonWriteAccess` |
| Service map kosong | `TRACING` masih `off`, collector tidak berjalan, aplikasi tidak menjangkau `127.0.0.1:4318`, sampling terlalu ketat, atau data belum muncul (tunggu 1 sampai 2 menit) |
| Hanya sebagian request muncul sebagai trace | Aturan sampling default; trainer mengatur aturan sampling lab |
| Metrik `CheckoutLatency` kosong | Metric filter dibuat setelah beban, pola salah (`$.path = "/checkout"`), atau nilai bukan `$.ms`; ulangi beban |
| `db.find orders` tidak lambat sebelum perbaikan | `MOCK_INDEXED` sudah `yes` pada revisi dasar, atau `DB_MODE` bukan `mock`; periksa `/config` |
| Setelah perbaikan hanya sebagian request cepat | Deployment belum selesai; task lama belum diganti |
| Deployment tidak selesai (task `PENDING`/gagal start) | Kuota Fargate atau ukuran task tidak valid (0,5 vCPU hanya mendukung memori 1 sampai 4 GB) |

## Cleanup
Biarkan service dan dashboard sampai akhir hari. Kembalikan task definition ke revisi tanpa sidecar bila ingin menekan biaya. Pada cleanup akhir hari hapus metric filter `CheckoutLatency`, log group `/ecs/adot-<nama>`, dan dashboard `perf-<nama>`.
