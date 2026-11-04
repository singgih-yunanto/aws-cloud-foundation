# Lab 8: Memantau, Melacak Perubahan, dan Mentriase Layanan di ECS Fargate (70 menit, Hari 3)

**Tujuan:** peserta (1) melacak **perubahan**: kapan versi baru dideploy, siapa yang melakukannya, apakah dibatalkan (rollback), dan apakah versi baru lebih buruk dari yang lama; (2) memantau layanan Fargate dengan Container Insights, log, alarm, dan dashboard; (3) mentriase empat kegagalan khas container (5xx, target tidak sehat, kehabisan memori, crash); (4) memakai CLI untuk membaca status; dan (5) memetakan temuan ke izin yang dibutuhkan, lalu menulis permintaan akses yang tepat ke vendor. Di dunia nyata Anda hanya memiliki akses baca CloudWatch; lab ini dikerjakan dengan akses penuh agar semua sumber informasi dapat dilihat, tetapi di setiap temuan Anda mencatat **izin apa yang dibutuhkan untuk melihatnya**.

**Biaya:** hampir nol di luar Lab 7 (alarm standar, satu dashboard, beberapa query Logs Insights, aturan EventBridge dan email SNS).

**Status:** belum diuji pada akun AWS yang sebenarnya (peristiwa EventBridge ECS, pesan *Stopped reason* OOM, nama metrik Container Insights, tampilan CloudTrail). Trainer melakukan dry-run.

## Prasyarat
- Lab 7 Bagian A selesai dan **Bagian B sudah dibersihkan**: service `svc-app-<nama>` berjalan pada revisi 2 (image `v2`), 2 task `Running`, ALB hanya meneruskan ke `tg-ecs-<nama>`.
- Topik SNS `ops-alerts-<nama>` (Lab 5) dengan langganan email **Confirmed**.
- Di CloudShell, `ALB=http://<DNS ALB>` terisi. Ganti `<nama>` dengan nama Anda (huruf kecil).

## Endpoint `lab-app` yang Dipakai

| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/version` | Memastikan versi, revisi, dan task yang melayani |
| `/error` | HTTP 500 dan log `ERROR` |
| `/health/fail` | Membuat satu task tidak sehat di mata ALB |
| `/oom?mb=700` | Menahan memori sampai task dimatikan (batas 512 MB) |
| `/crash` | Mematikan proses container |
| `/config` | Memperlihatkan konfigurasi aktif dan batas memori |

## Bagian A: Melacak perubahan (30 menit)
Pertanyaan yang ingin dijawab tim operasi: *apakah ada versi baru, kapan, oleh siapa, apakah di-rollback, dan apakah membuat layanan lebih buruk?* Ada lima sumber jejak; Anda akan membangun dan memakai semuanya.

1. **Aturan EventBridge `ecs-deploy-<nama>` (5 menit).** ECS memancarkan peristiwa setiap kali deployment berubah; Anda meneruskannya ke email.
   - **a.** EventBridge, Rules, **Create rule**: nama `ecs-deploy-<nama>`, *Rule type* **Rule with an event pattern**. *Event source* **AWS events**, pilih *Custom pattern (JSON editor)* dan tempel (ganti `<akun>` dan `<nama>`):

      ```json
      {
        "source": ["aws.ecs"],
        "detail-type": ["ECS Deployment State Change", "ECS Service Action"],
        "resources": [{"prefix": "arn:aws:ecs:ap-southeast-3:<akun>:service/ecs-<nama>/"}]
      }
      ```

   - **b.** *Target*: **SNS topic** `ops-alerts-<nama>`. Buka *Additional settings*, **Configure input transformer**: *Input path* `{"type":"$.detail-type","event":"$.detail.eventName","svc":"$.resources[0]","reason":"$.detail.reason"}` dan *Template* `"ECS <type> | <event> | <svc> | <reason>"`. Create.

      *Mengapa transformer:* tanpa itu email berisi JSON mentah yang sulit dibaca saat dini hari.

   **Checkpoint:** aturan berstatus *Enabled* dengan satu target SNS.

2. **Rilis dengan regresi yang lolos health check (7 menit).** Buat **revision baru** `td-app-<nama>` dari revisi 2: tambahkan variabel lingkungan `APP_VERSION` = `v2.1` dan `ERROR_PCT` = `15`. Update service ke revisi baru dan tunggu *Deployments* menjadi *Completed*.
   - **a.** Di CloudShell, pastikan versi berganti: `curl -s $ALB/version; echo`. Lalu hasilkan lalu lintas: `for i in $(seq 200); do curl -s -o /dev/null -w '%{http_code}\n' $ALB/; done | sort | uniq -c` (sekitar 15% berstatus 500).
   - **b.** **Checkpoint:** email `ECS Deployment State Change | SERVICE_DEPLOYMENT_IN_PROGRESS` dan `SERVICE_DEPLOYMENT_COMPLETED` masuk. Perhatikan bahwa ECS menyatakan deployment **berhasil** padahal 15% request gagal: health check ALB hanya menguji `/health`.

3. **Buktikan dari log bahwa versi baru lebih buruk (6 menit).** CloudWatch, Logs Insights, pilih log group `/ecs/lab-app-<nama>`, rentang 30 menit. Aplikasi menulis log JSON dengan field `version`, `status`, `ms`, `path`, `instance`.
   - **a.** Total request per versi:

      ```
      filter msg = "request"
      | stats count(*) as total by version
      ```

   - **b.** Error per versi:

      ```
      filter msg = "request" and status >= 500
      | stats count(*) as errors by version
      ```

      Hitung laju error tiap versi (errors / total). Versi `v2` mendekati 0%, `v2.1` sekitar 15%.
   - **c.** Kapan perubahan terjadi? Jalankan:

      ```
      filter msg = "request"
      | stats count(*) as n by version, bin(1m)
      | sort @timestamp asc
      ```

      Titik pergantian versi adalah **penanda deployment**; cocokkan dengan waktu email EventBridge.

   **Checkpoint:** Anda memiliki angka laju error per versi dan menit pergantiannya. *Catatan akses:* langkah ini hanya perlu `logs:StartQuery` dan `logs:GetQueryResults`, yang termasuk akses baca CloudWatch.

4. **Rollback manual (4 menit).** Update service ke **revisi 2** (versi `v2`). Tunggu *Completed*, lalu ulangi 100 request dan Logs Insights 3b. **Checkpoint:** error baru berhenti bertambah, email deployment masuk, dan `/version` menampilkan `v2`. Diskusi: rollback manual tidak otomatis; siapa yang memutuskannya di tim vendor, dan siapa yang memberi tahu Anda?

5. **Rilis yang gagal start dan rollback otomatis (4 menit).** Buat revision baru dengan image **`v-bad`** (start, tetapi `/health` selalu 503). Update service ke revisi itu. Amati *Deployments*, *Events*, dan target group (target baru `unhealthy`).

   **Checkpoint:** setelah beberapa menit circuit breaker menandai deployment *Failed* dan kembali ke revisi sebelumnya; email `SERVICE_DEPLOYMENT_FAILED` masuk dengan *reason* yang menyebut circuit breaker. Jawab: kapan circuit breaker menyelamatkan Anda, dan kapan tidak (langkah 2)?

6. **Siapa yang melakukannya? CloudTrail (4 menit).** CloudTrail, **Event history**, *Lookup attribute* **Event name** = `UpdateService`. Buka satu peristiwa dan baca: waktu, *User name* (siapa), *Source IP*, dan *Request parameters* (`taskDefinition` revisi baru). Ulangi untuk `RegisterTaskDefinition` (dalam *Request parameters* terlihat image dan variabel lingkungan yang berubah) dan `CreateService`.

   *Catatan:* peristiwa muncul beberapa menit setelah kejadian. CloudTrail menjawab *siapa dan kapan*; EventBridge menjawab *apa yang terjadi pada deployment itu*; log aplikasi menjawab *dampaknya*.

7. **Susun garis waktu perubahan (kerja mandiri, hasil dibahas di kelas).** Buat tabel dari langkah 2 sampai 5 dengan kolom: waktu, peristiwa (deploy, rollback), revisi/versi, pelaku, dampak, dan **sumber bukti** beserta **izin yang dibutuhkan**:

   | Sumber bukti | Menjawab | Izin minimal |
   |---|---|---|
   | Log aplikasi dengan field `version` (Logs Insights) | Dampak per versi, penanda deployment | Baca CloudWatch Logs (termasuk read-only CloudWatch) |
   | Email EventBridge | Deployment mulai/selesai/gagal | Tidak perlu akses; penerima email |
   | Tab *Deployments* dan *Events* service, `describe-services` | Status deployment, revisi aktif | `ecs:Describe*`, `ecs:List*` |
   | CloudTrail Event history | Siapa, kapan, apa yang diubah | `cloudtrail:LookupEvents` |
   | AWS Config (disebut saja) | Riwayat konfigurasi service/task definition | `config:Get*`, `config:Select*` |

   Sumber mana yang **sudah Anda miliki** di lingkungan vendor, dan mana yang perlu diminta (dasar langkah 17)?

## Bagian B: Memantau dengan Container Insights, alarm, dan dashboard (15 menit)
8. **Lihat Container Insights.** CloudWatch, **Insights**, **Container Insights**, pilih *ECS Clusters* dan `ecs-<nama>` (atau CloudWatch, Metrics, Classic metrics, namespace **ECS/ContainerInsights**). Telusuri tingkat cluster, service, dan task: CPU dan memori terpakai terhadap yang dicadangkan, jumlah task berjalan, dan jaringan. **Checkpoint:** Anda menemukan `RunningTaskCount` = 2 untuk `svc-app-<nama>`.

   *Dua sumber metrik:* `AWS/ECS` (CPUUtilization, MemoryUtilization per service, gratis, tanpa Container Insights) dan `ECS/ContainerInsights` (jumlah task, CPU/memori terpakai absolut, jaringan; berbayar). Perhatikan perbedaan dimensi: `ClusterName` dan `ServiceName`.

9. **Lima alarm (pola sama dengan Lab 5).** Alarm pertama memakai langkah lengkap, selebihnya tabel nilai. Semua mengirim ke topik `ops-alerts-<nama>`.
   - **a.** **Alarm `ecs-cpu-high-<nama>`:** CloudWatch, Alarms, Create alarm, Select metric, **ECS**, **ClusterName, ServiceName**, `CPUUtilization` milik `svc-app-<nama>`. *Statistic* Average, *Period* 1 minute, *Threshold* **Greater** than **70**, *Datapoints to alarm* **2 out of 3**, *Missing data* **Treat missing data as missing**. Notifikasi *In alarm* ke `ops-alerts-<nama>`. Nama `ecs-cpu-high-<nama>`.
   - **b.** Alarm lain:

      | Nama | Namespace dan metrik | Dimensi | Kondisi | Missing data |
      |---|---|---|---|---|
      | `ecs-mem-high-<nama>` | AWS/ECS `MemoryUtilization` | ClusterName, ServiceName | Average > 80, 2 of 3 | missing |
      | `ecs-tasks-low-<nama>` | ECS/ContainerInsights `RunningTaskCount` | ClusterName, ServiceName | Minimum < 2, 2 of 2 | **breaching** |
      | `ecs-unhealthy-<nama>` | AWS/ApplicationELB `UnHealthyHostCount` | TargetGroup + LoadBalancer | Maximum >= 1, 2 of 3 | notBreaching |
      | `ecs-5xx-<nama>` | AWS/ApplicationELB `HTTPCode_Target_5XX_Count` | LoadBalancer | Sum >= 5 dalam 1 menit, 1 of 1 | **notBreaching** |

      *Mengapa missing data berbeda-beda:* `RunningTaskCount` yang hilang berarti service bermasalah, jadi dianggap pelanggaran; jumlah 5xx yang tidak ada saat tidak ada error berarti sehat.

   **Checkpoint:** lima alarm berstatus OK atau Insufficient data (beberapa menit).

10. **Dashboard `ecs-ops-<nama>`.** CloudWatch, Dashboards, Create dashboard. Tambahkan enam widget:

    | # | Jenis | Isi |
    |---|---|---|
    | 1 | **Text** (Markdown) | Judul, nama service, tautan ke runbook, dan nomor kontak vendor |
    | 2 | **Line** | `RunningTaskCount` dan `DesiredTaskCount` (ECS/ContainerInsights) |
    | 3 | **Line** | `CPUUtilization` dan `MemoryUtilization` service (AWS/ECS) |
    | 4 | **Number** | `HealthyHostCount` dan `UnHealthyHostCount` (target group) |
    | 5 | **Logs table / Bar** | `filter msg = "request" \| stats count(*) as n by version, bin(1m)` pada log group service (penanda deployment) |
    | 6 | **Alarm status** | kelima alarm `ecs-` |

    Simpan. **Checkpoint:** pada widget 5 terlihat pergantian versi `v2`, `v2.1`, `v2`, dan `v-bad` yang Anda lakukan di Bagian A.

## Bagian C: Triase empat kegagalan khas (15 menit)
Bayangkan Anda hanya melihat alarm dan dashboard. Untuk tiap drill: picu, lihat alarm/dashboard yang bereaksi, lalu cari **penyebab** (di mana penyebab itu tertulis, dan izin apa yang perlu).

11. **5xx.** `for i in $(seq 40); do curl -s -o /dev/null $ALB/error; done`. Alarm `ecs-5xx-<nama>` berbunyi. Cari penyebab di Logs Insights: `filter level = "ERROR" | stats count(*) by msg, version`. Catat: 5xx berasal dari aplikasi (`HTTPCode_Target_5XX`), bukan dari ALB (`HTTPCode_ELB_5XX`).

12. **Target tidak sehat.** Jalankan `curl $ALB/health/fail` sampai Anda menemukan ID task yang menjawab (`/version` menunjukkan ID task; ulangi bila perlu). Dalam 1 sampai 2 menit target itu `unhealthy`, ALB berhenti mengirim lalu lintas, dan ECS mengganti task.
    - **a.** Alarm `ecs-unhealthy-<nama>` berbunyi. Di ECS, tab *Tasks* filter *Stopped*: baca *Stopped reason* (`Task failed ELB health checks in (target-group ...)`).
    - **b.** Pertanyaan: mengapa alarm bisa kembali OK sendiri? Apa yang terlihat di `RunningTaskCount` selama penggantian?

13. **Kehabisan memori.** `curl "$ALB/oom?mb=700"` (batas task 512 MB). Beberapa detik kemudian container dimatikan.
    - **a.** Di Container Insights/dashboard lihat `MemoryUtilization` naik tajam lalu jatuh (task diganti). Alarm `ecs-mem-high-<nama>` mungkin sempat berbunyi.
    - **b.** Di tab *Stopped* baca *Stopped reason*: `Essential container in task exited` dan, pada detail container, *Exit code* **137** dengan pesan `OutOfMemoryError: Container killed due to memory usage`.
    - **c.** Catat di mana bukti ini ada. **Log aplikasi tidak memuat penyebabnya** (proses dimatikan dari luar); bukti ada di metadata task di ECS. Berarti tanpa izin `ecs:DescribeTasks`, Anda hanya melihat gejala (memori naik lalu task hilang) dari CloudWatch.

14. **Crash berulang.** `for i in 1 2 3; do curl -s $ALB/crash; echo; sleep 5; done`. Task keluar dengan exit code 1 dan diganti; `RunningTaskCount` turun-naik, `DesiredTaskCount` tetap 2. Baca log aplikasi terakhir sebelum mati: `filter msg = "proses dimatikan sengaja lewat /crash"`. Bedakan **gejala** (task sering hilang) dari **penyebab** (proses keluar).

    **Checkpoint:** untuk keempat drill Anda dapat menyebut: alarm yang bereaksi, sumber penyebab (log, metrik, atau metadata task), dan apakah cukup akses baca CloudWatch.

## Bagian D: CLI dan permintaan akses ke vendor (10 menit)
15. **CLI dari CloudShell (read-only).** Ganti `<nama>`; jalankan satu per satu dan baca hasilnya:

    ```bash
    aws ecs list-services --cluster ecs-<nama>
    aws ecs describe-services --cluster ecs-<nama> --services svc-app-<nama> \
      --query 'services[0].{desired:desiredCount,running:runningCount,taskDef:taskDefinition,deployments:deployments[].{status:status,rollout:rolloutState,td:taskDefinition,running:runningCount,created:createdAt}}'
    aws ecs list-tasks --cluster ecs-<nama> --desired-status STOPPED --max-items 5
    aws ecs describe-tasks --cluster ecs-<nama> --tasks <ARN-task-STOPPED> \
      --query 'tasks[0].{stop:stoppedReason,code:stopCode,containers:containers[].{name:name,exit:exitCode,reason:reason}}'
    aws logs tail /ecs/lab-app-<nama> --since 15m --filter-pattern ERROR
    aws cloudwatch describe-alarms --alarm-name-prefix ecs- --query 'MetricAlarms[].[AlarmName,StateValue]' --output table
    aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=UpdateService --max-results 5
    ```

    Mana dari perintah di atas yang akan **gagal** dengan `AccessDenied` bila identitas Anda hanya memiliki `CloudWatchReadOnlyAccess`? (Periksa dengan: *IAM policy simulator* atau tanyakan trainer.)

16. **Matriks akses.** Isi tabel ini dari pengalaman Bagian A sampai C:

    | Pertanyaan operasi | Sumber | Izin | Cukup read-only CloudWatch? |
    |---|---|---|---|
    | Apakah layanan sehat sekarang? | ? | ? | ? |
    | Versi mana yang sedang berjalan? | ? | ? | ? |
    | Mengapa task berhenti (OOM, health check, crash)? | ? | ? | ? |
    | Siapa yang men-deploy dan kapan? | ? | ? | ? |
    | Apa isi task definition yang berubah? | ? | ? | ? |
    | Apakah dampak rilis baru buruk? | ? | ? | ? |

17. **Draf permintaan akses ke vendor.** Tulis satu permintaan (maksimal setengah halaman) dengan format berikut, berdasarkan kolom "tidak cukup" pada matriks:

    ```text
    Judul        : Permintaan akses baca ECS untuk pemantauan operasional
    Alasan       : (insiden/pertanyaan operasi yang tidak bisa dijawab hanya dengan CloudWatch)
    Izin diminta : ecs:DescribeServices, ecs:DescribeTasks, ecs:ListTasks, ecs:DescribeTaskDefinition,
                   cloudtrail:LookupEvents  (sebutkan persis, bukan "ReadOnlyAccess")
    Cakupan      : cluster/service tertentu (ARN), bukan seluruh akun
    Durasi       : permanen / sementara sampai (tanggal), ditinjau ulang tiap (periode)
    Tidak diminta: ecs:ExecuteCommand, ecs:UpdateService, iam:*, akses ke secret
    Mitigasi     : akses hanya baca; audit lewat CloudTrail
    ```

    Diskusi: izin mana yang wajar diminta dan mana yang vendor kemungkinan tolak? Apa alternatif bila ditolak (laporan terjadwal dari vendor, dashboard bersama, data lewat log yang kita kuasai)?

## Pertanyaan Operasi
1. Rilis dinyatakan sukses oleh ECS tetapi pelanggan mengeluh. Urutkan langkah Anda dari data yang sudah Anda punya (CloudWatch) sampai data yang perlu diminta.

2. Alarm apa yang paling cepat memberi tahu rilis yang buruk, dan mengapa health check ALB bukan jawabannya?

3. Apa informasi minimum yang Anda minta dari vendor setiap kali ada deployment (pemberitahuan terjadwal)?

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| Email EventBridge tidak masuk | Aturan belum *Enabled*, pola `resources` salah (akun atau nama cluster), topik SNS tidak mengizinkan EventBridge (periksa *Access policy* topik), atau langganan email belum Confirmed |
| Logs Insights kosong | Log group salah, rentang waktu terlalu sempit, atau `awslogs` belum mengirim (periksa execution role) |
| Metrik Container Insights tidak ada | Container Insights tidak aktif pada cluster (Update cluster), atau baru beberapa menit; metrik `AWS/ECS` tetap ada |
| `/oom` tidak mematikan task | Batas memori task lebih besar dari `mb`; naikkan `mb` atau periksa `/config` bagian `memory` |
| Task mati karena OOM tetapi tidak ada email | Peristiwa task tidak ada pada aturan ini (hanya Deployment State Change dan Service Action); gunakan alarm `ecs-tasks-low` dan `ecs-mem-high` |
| CloudTrail tidak menampilkan `UpdateService` | Event history terlambat 5 sampai 15 menit atau filter Region salah (pastikan Jakarta) |
| `ecs-tasks-low` selalu `Insufficient data` | Container Insights belum menerima data atau dimensi salah (ClusterName dan ServiceName harus keduanya) |

## Cleanup
Biarkan service, alarm, dashboard, dan aturan EventBridge untuk Lab 9. Hapus `/oom` yang masih menahan memori dengan memulai ulang task bila perlu. Pada akhir hari: alarm `ecs-*`, dashboard `ecs-ops-<nama>`, aturan `ecs-deploy-<nama>`, dan log group `/ecs/lab-app-<nama>`.
