# Lab 5: Memasang CloudWatch Agent, Alerting, dan Dashboard (65 menit, Hari 2)

**Tujuan:** Peserta memasang CloudWatch Agent sendiri pada dua kasus, yaitu **instance tunggal** (manual) dan **Auto Scaling group** (melalui Launch Template), menyimpan konfigurasi agent di SSM Parameter Store, membuat alert yang dapat ditindaklanjuti (SNS, alarm CPU, memori, target tidak sehat, dan error 5xx, serta metric filter dari log), merancang **dashboard kustom**, kemudian memicu sendiri tiga kondisi untuk membuktikan bahwa alert benar-benar berbunyi.
**Biaya:** hampir nol (satu t3.micro tambahan selama beberapa jam, alarm standar, beberapa metrik kustom, log berumur 1 hari, satu dashboard; tiga dashboard pertama per akun gratis). Detailed monitoring EC2 memberi metrik per menit dengan biaya beberapa sen.
**Status:** belum diuji pada akun AWS yang sebenarnya. Trainer melakukan dry-run, terutama instalasi CloudWatch Agent pada Amazon Linux 2023, pembacaan konfigurasi dari SSM, dan dimensi metrik pada instance tunggal dibandingkan ASG.

## Prasyarat
- Stack Lab 4 berjalan (ALB, ASG, dua instance sehat) dengan Launch Template `lt-app-<nama>` yang mengaktifkan **detailed monitoring**. Instance Lab 4 **belum memiliki CloudWatch Agent**: memori dan disk belum tersedia di CloudWatch. Itulah yang diperbaiki pada lab ini.
- Role `lab-ec2-app` (disiapkan trainer) memiliki `CloudWatchAgentServerPolicy`, yang mengizinkan agent mengirim metrik dan log serta membaca parameter SSM berawalan `AmazonCloudWatch-`.
- Key pair `key-<nama>` dan Security Group `web-sg-<nama>` dari Lab 2 (SSH dari My IP). Bila IP laptop berubah, perbarui rule My IP.
- Alamat email untuk konfirmasi langganan SNS. Berkas `loadgen.sh`, `user-data.lab4.sh`, dan variabel `ALB` di CloudShell dari Lab 4.

## Endpoint `lab-app` yang Dipakai
Daftar lengkap ada di `Lab4-HA-WebApp.md` (Referensi Endpoint).
| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/health/fail` dan `/health/ok` | Membuat dan memulihkan target `unhealthy` (alarm `tg-unhealthy`) |
| `/error` | Menghasilkan HTTP 500 dan log `ERROR` (alarm 5xx dan metric filter `AppErrors`) |
| `/cpu?seconds=&workers=` dan `/cpu/stop` | Membebani dan melepas CPU (alarm `cpu-high`) |
| `/` | Memeriksa status instance |

## Bagian A: Notifikasi (5 menit)
1. **Topik SNS.** Buka SNS, Topics, Create topic: type *Standard*, nama `ops-alerts-<nama>`. Buat *Subscription* dengan protocol Email dan alamat Anda, lalu **konfirmasi** melalui email yang masuk (periksa folder spam). Subscription berstatus *Confirmed* sebelum lanjut.

## Bagian B: Memasang CloudWatch Agent (20 menit)
2. **Buktikan bahwa data belum ada.** Buka CloudWatch, Metrics, All metrics, dan cari `mem_used_percent`. Tidak ada namespace **CWAgent**. Buka juga EC2, pilih satu instance ASG, tab *Monitoring*: CPU, jaringan, dan disk I/O ada, tetapi tidak ada memori dan ruang disk. Metrik bawaan EC2 berasal dari hypervisor, yang tidak melihat isi OS. Memori dan ruang disk hanya dapat dibaca dari dalam OS, oleh agent.
3. **Simpan konfigurasi agent di Parameter Store.** Buka Systems Manager, Parameter Store, Create parameter: nama `AmazonCloudWatch-lab-app-<nama>`, tier *Standard*, type *String*, data type *text*. Isi value dengan JSON berikut (juga ada di `06-app/cwagent/agent-config.v1.json`):
   ```json
   {
     "agent": { "metrics_collection_interval": 60, "run_as_user": "root" },
     "metrics": {
       "namespace": "CWAgent",
       "append_dimensions": { "InstanceId": "${aws:InstanceId}", "AutoScalingGroupName": "${aws:AutoScalingGroupName}" },
       "aggregation_dimensions": [["AutoScalingGroupName"]],
       "metrics_collected": {
         "mem":  { "measurement": ["mem_used_percent"] },
         "disk": { "measurement": ["used_percent"], "resources": ["/"] }
       }
     },
     "logs": {
       "logs_collected": { "files": { "collect_list": [
         { "file_path": "/var/log/lab-app.log", "log_group_name": "/lab/lab-app", "log_stream_name": "{instance_id}", "retention_in_days": 1 }
       ] } }
     }
   }
   ```
   Perhatikan tiga bagian: `metrics` (apa yang diukur dan dimensinya), `logs` (berkas mana yang dikirim), dan nilai `${aws:...}` yang diisi agent saat berjalan. Nama parameter harus berawalan `AmazonCloudWatch-`, karena hanya itu yang boleh dibaca role `lab-ec2-app`. Diskusikan: mengapa konfigurasi disimpan di satu tempat dan bukan disalin ke tiap server?

### Kasus 1: Instance tunggal (manual)
4. **Luncurkan instance.** Buat EC2 `mon-solo-<nama>`: Amazon Linux 2023, t3.micro, default VPC dengan public IP, Security Group `web-sg-<nama>`, key pair `key-<nama>`, IAM instance profile `lab-ec2-app`, dan pada *Advanced details* aktifkan **Detailed CloudWatch monitoring**. Pada **User data** tempel isi `user-data.lab4.sh` (aplikasi `lab-app`; User Data ini **tidak** memasang agent). Tunggu status check lulus, lalu buka `http://<public-ip>/` untuk memastikan aplikasi hidup.
5. **Pasang agent.** Hubungkan ke instance melalui SSH (atau EC2 Instance Connect), lalu jalankan:
   ```bash
   sudo dnf install -y amazon-cloudwatch-agent
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 \
     -c ssm:AmazonCloudWatch-lab-app-<nama> -s
   sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
   ```
   Pada perintah kedua, `fetch-config` mengambil konfigurasi dari Parameter Store, `-s` memulai (start) agent, dan `-m ec2` memberi tahu bahwa agent berjalan di EC2. Status yang diharapkan: `"status": "running"`. Periksa juga `systemctl is-enabled amazon-cloudwatch-agent` (agent harus tetap hidup setelah reboot) dan log agent: `sudo tail -20 /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log`.
6. **Hasilkan sedikit log, lalu verifikasi.** `curl localhost/error` dua kali. Setelah 1 sampai 2 menit, di CloudWatch, Metrics, namespace **CWAgent**, temukan `mem_used_percent` dengan dimensi **InstanceId** milik `mon-solo-<nama>`, dan di Log groups terdapat `/lab/lab-app` dengan stream bernama instance ID Anda. Catat dimensi apa saja yang ada pada instance tunggal.

### Kasus 2: Auto Scaling group (melalui Launch Template)
7. **Mengapa tidak cukup memasang manual.** Instance ASG dapat diganti atau ditambah kapan saja (auto healing, scale-out). Agent yang dipasang manual pada dua instance saat ini **tidak akan ada** pada instance pengganti. Karena itu agent harus menjadi bagian dari **Launch Template**, sehingga setiap instance baru memasangnya sendiri saat pertama kali menyala. Inilah penyebab umum "instance ASG tidak punya data memori".
8. **Launch Template versi baru.** Buka EC2, Launch Templates, `lt-app-<nama>`, Actions, **Modify template (Create new version)** dengan *Source template version* = versi saat ini. Pada *Advanced details*, User data, **tambahkan di akhir** (setelah seluruh isi yang ada; ganti `<nama>`):
   ```bash
   dnf install -y amazon-cloudwatch-agent
   /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c ssm:AmazonCloudWatch-lab-app-<nama> -s
   ```
   (Tanpa `sudo`, karena User Data berjalan sebagai root.) Simpan, lalu **Set default version** ke versi baru. Bandingkan dengan Kasus 1: perintahnya sama, hanya dijalankan otomatis.
9. **Instance refresh.** Buka ASG `asg-app-<nama>`, tab *Instance refresh*, Start: minimum healthy percentage 50% dan instance warmup 120 detik. Instance diganti bergiliran sehingga situs tetap hidup (sekitar 8 sampai 10 menit). **Lanjutkan ke Bagian C selagi menunggu.** Instance lama tidak berubah sampai diganti, sehingga memori dan disk pada ASG baru muncul setelah refresh selesai.
10. **Verifikasi dan bandingkan** (setelah dua instance baru *InService*). Di CloudWatch, namespace CWAgent, bandingkan dimensi pada dua kasus:
    | | Instance tunggal | ASG |
    |---|---|---|
    | Dimensi yang tersedia | `InstanceId` (dan dimensi disk) | `InstanceId` + `AutoScalingGroupName`, serta agregat per `AutoScalingGroupName` |
    | Dipakai pada alarm/dashboard | `InstanceId` | `AutoScalingGroupName` (instance berganti, ASG tetap) |
    Jelaskan mengapa alarm untuk ASG sebaiknya memakai dimensi grup dan bukan instance ID. Log group `/lab/lab-app` kini memiliki satu stream per instance (tiga atau lebih bila instance tunggal dihitung).

## Bagian C: Alarm dan log (15 menit)
11. **Alarm CPU.** Buat alarm pada `CPUUtilization` (dimensi AutoScalingGroupName = `asg-app-<nama>`), statistik Average, period 1 menit, kondisi *Greater than 70*, dan **datapoints to alarm 2 out of 3**. Treat missing data: *Treat missing data as missing*. Aksi: *In alarm* dan *OK* ke topik `ops-alerts-<nama>`. Tuliskan **Alarm description** yang berisi langkah pertama triage (misalnya "Periksa tab Activity ASG dan /cpu"). Beri nama `cpu-high-<nama>`.
12. **Uji jalur notifikasi tanpa menunggu kondisi nyata.** Di CloudShell: `aws cloudwatch set-alarm-state --alarm-name cpu-high-<nama> --state-value ALARM --state-reason "uji"`. Pastikan email diterima, lalu kembalikan ke `OK`. Diskusikan: alarm yang tidak pernah diuji ujungnya sering ternyata tidak sampai ke siapa pun.
13. **Alarm memori** (hanya mungkin berkat agent). Namespace CWAgent, metrik `mem_used_percent` dengan dimensi `AutoScalingGroupName` = `asg-app-<nama>`, statistik Average, period 1 menit, *Greater than 80*, **2 out of 3**, aksi ke topik yang sama. Nama `mem-high-<nama>`. Bila metrik ini belum ada karena refresh belum selesai, buat alarm setelah langkah 10. Diskusikan: mengapa memori yang naik terus tanpa turun (kebocoran) lebih berbahaya dibanding lonjakan sesaat, dan alarm apa yang cocok untuknya?
14. **Alarm target tidak sehat.** Metrik `UnHealthyHostCount` (namespace AWS/ApplicationELB, dimensi TargetGroup dan LoadBalancer), statistik Maximum, period 1 menit, *Greater/Equal 1*, **2 out of 2**. Aksi ke topik yang sama. Nama `tg-unhealthy-<nama>`.
15. **Alarm error 5xx.** Metrik `HTTPCode_Target_5XX_Count` (AWS/ApplicationELB, dimensi LoadBalancer; error 5xx yang dikirim aplikasi, seperti `/error`) dan bandingkan dengan `HTTPCode_ELB_5XX_Count` (error buatan ALB sendiri, misalnya 503 saat tidak ada target sehat), statistik Sum, period 1 menit, *Greater/Equal 5*, treat missing data: **Not breaching**. Nama `alb-5xx-<nama>`.
16. **Log dan metric filter.** Buka CloudWatch, Log groups, `/lab/lab-app`, lalu buka satu stream (log berasal dari agent yang Anda pasang). Setiap baris adalah JSON dengan `level`, `path`, `status`, dan `ms`.
    a. Pada log group, tab *Metric filters*, Create: pola `{ $.level = "ERROR" }`, metric namespace `LabApp`, nama `AppErrors`, nilai 1. Buat alarm pada metrik itu (Sum, period 1 menit, *Greater/Equal 3*, treat missing data: Not breaching) dengan nama `app-errors-<nama>`.
    b. **Logs Insights**: pilih log group, jalankan `fields @timestamp, level, path, status, ms | filter level = "ERROR" | sort @timestamp desc | limit 20`, kemudian `stats count() as n, avg(ms) as rata, pct(ms, 95) as p95 by path`. Metrik menjawab *apakah ada masalah*, log menjawab *apa yang terjadi*.

## Bagian D: Dashboard kustom (10 menit)
Dashboard yang baik menjawab pertanyaan operasi pada satu layar: *sehat atau tidak, di mana, dan sejak kapan*. Anda merancangnya sendiri.
17. **Buat dashboard.** CloudWatch, Dashboards, Create dashboard: nama `ops-<nama>`. Tambahkan widget satu per satu (Add widget):
    | # | Jenis widget | Isi | Alasan |
    |---|---|---|---|
    | 1 | **Text** (markdown) | Judul, nama sistem, siapa yang dihubungi, dan tautan runbook, misalnya `# lab-app (<nama>)` dan `Eskalasi: ...` | Orang yang dibangunkan pukul 03.00 perlu konteks |
    | 2 | **Number** | `HealthyHostCount` dan `UnHealthyHostCount` (ApplicationELB, TargetGroup dan LoadBalancer) | Jawaban cepat: berapa target sehat |
    | 3 | **Line** | `CPUUtilization` ASG `asg-app-<nama>` **dan** `CPUUtilization` instance `mon-solo-<nama>` pada satu grafik | Membandingkan grup dengan instance tunggal |
    | 4 | **Line** | `mem_used_percent` (ASG). Pada *Graph options*, tambahkan **horizontal annotation** pada nilai 80 berlabel "ambang mem-high" | Ambang terlihat langsung pada grafik |
    | 5 | **Line** dengan **metric math** | `RequestCount` (m1, Sum) dan `HTTPCode_Target_5XX_Count` (m2, Sum); tambahkan ekspresi `100 * m2 / m1` berlabel "5xx %" dan sembunyikan m1 dan m2 bila ingin | Persentase error lebih bermakna daripada jumlah mentah |
    | 6 | **Gauge** | `disk_used_percent` (pilih satu instance), rentang 0 sampai 100 | Kapasitas disk |
    | 7 | **Alarm status** | Pilih seluruh alarm `-<nama>` | Ringkasan semua alert |
    | 8 | **Logs table** | Log group `/lab/lab-app`, query `stats count() as n, avg(ms) as rata, pct(ms, 95) as p95 by path \| sort p95 desc` | Endpoint mana yang paling lambat |
18. **Atur ulang tata letak.** Seret widget agar status ringkas (text, number, alarm status) berada di baris atas dan detail di bawah. Aturan: tampilkan yang menentukan keputusan di atas. Atur *time range* 1 jam dan **auto refresh** 1 menit, lalu **Save dashboard**.
19. **Ubah lewat JSON.** Buka Actions, **View/edit source**. Temukan widget CPU dan ubah `"title"` atau `"period"` langsung di JSON, lalu simpan. Dashboard adalah dokumen JSON, sehingga dapat disalin ke dashboard lain atau disimpan di repositori. Opsional di CloudShell: `aws cloudwatch get-dashboard --dashboard-name ops-<nama> --query DashboardBody --output text > ops.json`.
20. **Uji dashboard.** Jalankan `curl $ALB/error` beberapa kali dan perhatikan widget 5 dan 8 berubah. Diskusikan: widget mana yang akan Anda hapus karena tidak membantu keputusan, dan metrik apa yang masih kurang (misalnya `TargetResponseTime` p95 sesuai node lambat Lab 4)?

## Bagian E: Picu dan amati (sendiri, 8 menit)
21. Picu tiga kondisi satu per satu dan pastikan alarm yang sesuai berubah ke ALARM dan email diterima. Amati juga dashboard Anda.
    | Pemicu | Alert yang diharapkan | Apa yang diamati |
    |---|---|---|
    | `curl $ALB/health/fail` berulang hingga mengenai satu instance | `tg-unhealthy` | Target Group, tab Targets, kolom *Health status details*; widget 2 |
    | `for i in $(seq 20); do curl -s -o /dev/null $ALB/error; done` | `alb-5xx`, `app-errors` | Logs Insights per `path` dan `status`; widget 5 |
    | `bash loadgen.sh cpu $ALB 6 300` | `cpu-high` | Widget CPU dan tab Activity ASG |
22. **Pemulihan.** `curl $ALB/health/ok` (ulangi agar mengenai instance yang tepat), `curl $ALB/cpu/stop` (ulangi), lalu pastikan alarm kembali ke OK.
23. **Diskusi desain alert** (5 menit): apakah alert ini *actionable*? Gunakan severity berbeda (siapa yang dibangunkan pukul 03.00 dan siapa yang cukup membaca esok pagi?), *M out of N datapoints* dan *treat missing data* agar tidak berkedip, dan *composite alarm* untuk mengurangi kebisingan. Tujuan akhir alert (email, chat, pager) dibahas sebagai teori (AWS Chatbot atau Lambda ke webhook).

**Opsional:** buat aturan EventBridge untuk kejadian ASG *EC2 Instance Terminate Successful* dengan target SNS, lalu terminate satu instance dan amati notifikasinya.

**Demo trainer (5 menit):** alert biaya. Tunjukkan Budget dari Lab 1 dan Cost Anomaly Detection. Billing alarm CloudWatch hanya ada di Region us-east-1 sehingga tidak dikerjakan peserta. Trainer juga menunjukkan cara memperbarui konfigurasi agent di banyak instance tanpa SSH (SSM Run Command atau State Manager dengan dokumen `AmazonCloudWatch-ManageAgent`) sebagai teori.

## Pertanyaan Operasi
- Alert apa yang berbunyi bila satu AZ mati? Berapa lama sampai Anda tahu, dan siapa yang menerimanya?
- Alert apa yang *tidak* ada tetapi seharusnya ada (misalnya latensi, disk, atau kegagalan tunnel pada Lab 8)?
- Bagaimana membedakan masalah aplikasi, instance, dan jaringan hanya dari metrik?
- Bagaimana Anda memastikan setiap server baru otomatis dimonitor, dan siapa yang tahu bila agent mati?

## Validasi
Agent berjalan pada `mon-solo-<nama>` dan pada kedua instance ASG baru, `mem_used_percent` terlihat untuk keduanya (dimensi berbeda), email uji dan email alarm diterima, alarm utama berstatus OK saat stack sehat, dashboard `ops-<nama>` menampilkan delapan widget (termasuk annotation, metric math, dan alarm status), dan ketiga kondisi yang dipicu menghasilkan alert dan kembali ke OK setelah dipulihkan.

## Pemecahan Masalah
| Gejala | Penyebab dan solusi |
|---|---|
| Email tidak diterima | Subscription masih *Pending confirmation*, email masuk ke spam, atau alamat salah |
| `dnf install` gagal atau lama | Instance tidak punya jalur internet (public IP/Security Group outbound), atau repositori belum siap; ulangi setelah satu menit |
| `fetch-config` gagal atau `AccessDenied` pada `ssm:GetParameter` | Nama parameter tidak berawalan `AmazonCloudWatch-`, nama berbeda dengan yang diketik (`<nama>`), atau instance tidak memakai role `lab-ec2-app` |
| Status agent `stopped` / log agent berisi error JSON | Konfigurasi di parameter tidak valid (tanda kurung, koma, atau tanda kutip hilang); periksa `/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log`, perbaiki parameter, jalankan `fetch-config` lagi |
| Metrik `CWAgent` tidak ada | Agent belum berjalan (`sudo systemctl status amazon-cloudwatch-agent`), tunggu 1 sampai 2 menit, atau role tanpa `CloudWatchAgentServerPolicy` |
| Instance ASG baru tidak punya agent | Versi Launch Template baru belum menjadi *default*, atau instance refresh belum selesai; instance lama tetap tanpa agent. Periksa `/var/log/lab-app-userdata.log` dan `/var/log/cloud-init-output.log` |
| Metrik instance tunggal tidak memiliki dimensi grup | Normal: `AutoScalingGroupName` hanya ada pada instance anggota ASG. Gunakan `InstanceId` |
| Alarm `INSUFFICIENT_DATA` | Belum ada datapoint (tunggu 2 sampai 3 menit), nama dimensi atau namespace salah, atau metrik per menit belum aktif (detailed monitoring) |
| Log group `/lab/lab-app` kosong | Agent belum memuat konfigurasi, atau aplikasi belum menulis log (`curl $ALB/` sekali) |
| Alarm tidak kembali ke OK | Periode evaluasi belum lewat, atau beban masih berjalan (`/cpu/stop`) |
| Alarm 5xx tidak berbunyi | `/error` menghasilkan 500 dari aplikasi, yang dicatat ALB sebagai `HTTPCode_Target_5XX_Count`; `HTTPCode_ELB_5XX_Count` hanya untuk error yang dibuat ALB sendiri (502/503/504) |
| Widget dashboard kosong | Dimensi salah, rentang waktu terlalu pendek, atau metrik belum ada; periksa di *All metrics* lebih dulu |

## Cleanup
Pertahankan sampai Lab 6: instance `mon-solo-<nama>`, parameter `AmazonCloudWatch-lab-app-<nama>` (Lab 6 menambah penerima trace), dashboard, dan topik SNS. Pada akhir Hari 2 hapus alarm (`cpu-high`, `mem-high`, `tg-unhealthy`, `alb-5xx`, `app-errors`), metric filter, instance `mon-solo-<nama>`, dan parameter; dashboard boleh disimpan (gratis, tiga pertama). **Pertahankan topik SNS `ops-alerts-<nama>` dan subscription-nya** karena dipakai pada Lab 8 (Hari 3); topik itu dihapus pada Lab 10. Log group `/lab/lab-app` boleh dibiarkan (retensi 1 hari) dan dihapus pada Lab 10.
