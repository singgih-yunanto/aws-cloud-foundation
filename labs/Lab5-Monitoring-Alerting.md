# Lab 5: Metrik, Alarm, dan Dashboard dengan CloudWatch Agent (isi 45 menit, slot 65 menit, Hari 2)

**Tujuan:** Peserta melihat metrik bawaan, memasang CloudWatch Agent pada satu instance, menyimpan konfigurasinya di SSM Parameter Store, membuat alarm yang dapat ditindaklanjuti (SNS, CPU, memori, target tidak sehat, dan error 5xx), membuat **dashboard kustom**, lalu memicu kondisi untuk membuktikan alert berbunyi. Pemasangan agent pada ASG (melalui Launch Template) dikerjakan pada Lab 6.
**Biaya:** hampir nol (satu t3.micro tambahan selama beberapa jam, alarm standar, beberapa metrik kustom, log berumur 1 hari, satu dashboard; tiga dashboard pertama per akun gratis).
**Status:** belum diuji pada akun AWS yang sebenarnya. Trainer melakukan dry-run, terutama instalasi CloudWatch Agent pada Amazon Linux 2023 dan pembacaan konfigurasi dari SSM. Nama menu dan tombol di bawah mengikuti konsol AWS saat ini; bila tampilannya berbeda, cari menu dengan nama yang mirip. Slot 65 menit memberi cadangan untuk kendala role dan jaringan.

## Prasyarat
- Stack Lab 4 berjalan (ALB, ASG, dua instance sehat). Instance ASG **belum memiliki CloudWatch Agent**.
- Role **`lab-ec2-app`** (disiapkan trainer) dengan `CloudWatchAgentServerPolicy`, yang mengizinkan agent mengirim metrik dan log serta membaca parameter SSM berawalan `AmazonCloudWatch-`.
- Key pair `key-<nama>` dan Security Group `web-sg-<nama>` dari Lab 2 (SSH dari My IP). Bila IP laptop berubah, perbarui rule My IP.
- Alamat email untuk konfirmasi langganan SNS. Berkas `loadgen.sh`, `user-data.lab4.sh`, dan variabel `ALB` di CloudShell dari Lab 4.
- **Region:** pada setiap halaman konsol, periksa pojok kanan atas bertuliskan **Asia Pacific (Jakarta) ap-southeast-3**. Resource, metrik, dan alarm di Region lain tidak terlihat.

## Endpoint `lab-app` yang Dipakai
Daftar lengkap ada di `Lab4-HA-WebApp.md` (Referensi Endpoint).
| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/health/fail` dan `/health/ok` | Membuat dan memulihkan target `unhealthy` (alarm `tg-unhealthy`) |
| `/error` | Menghasilkan HTTP 500 dan log `ERROR` (alarm 5xx) |
| `/cpu?seconds=&workers=` dan `/cpu/stop` | Membebani dan melepas CPU (alarm `cpu-high`) |
| `/` | Memeriksa status instance |

## Bagian A: Notifikasi (5 menit)
1. **Topik SNS.**
   a. Buka **Simple Notification Service**, menu **Topics**, tombol **Create topic**. Pilih type **Standard**, isi *Name* `ops-alerts-<nama>`, biarkan sisanya, klik **Create topic**.
   b. Pada halaman topik, tab *Subscriptions*, klik **Create subscription**. *Protocol*: **Email**. *Endpoint*: alamat email Anda. Klik **Create subscription**. Status awal *Pending confirmation*.
   c. Buka email dari AWS Notifications (subjek *AWS Notification - Subscription Confirmation*; periksa folder spam), klik **Confirm subscription**.
   d. Kembali ke konsol, klik tombol refresh pada tab *Subscriptions*. **Checkpoint:** status menjadi **Confirmed**. Jangan lanjut sebelum Confirmed, karena alarm tidak dapat mengirim email ke langganan yang belum dikonfirmasi.

## Bagian B: Melihat metrik bawaan (5 menit)
2. **Metrik bawaan dan yang tidak ada.**
   a. Buka **EC2**, **Instances**, pilih satu instance ASG, tab **Monitoring**. CPU, jaringan, dan disk I/O ada (per 1 menit karena detailed monitoring), tetapi tidak ada memori dan ruang disk.
   b. Buka **CloudWatch**, menu **Metrics**, **Classic metrics** (bernama *All metrics* di tampilan konsol yang lebih lama; jangan pilih *Explorer*). Tab **Browse** menampilkan kartu namespace. Klik **EC2**, lalu **By Auto Scaling Group**, dan temukan `CPUUtilization` milik `asg-app-<nama>`. Klik kartu **ApplicationELB** dan lihat `RequestCount` dan `HealthyHostCount`.
   c. Pada kotak pencarian ketik `mem_used_percent`. **Checkpoint:** hasilnya kosong; tidak ada namespace **CWAgent**.
   Metrik bawaan EC2 berasal dari hypervisor, yang tidak melihat isi OS. Memori dan ruang disk hanya dapat dibaca dari dalam OS, oleh agent. Pada bagian berikut Anda memasangnya pada satu instance.

## Bagian C: Memasang CloudWatch Agent pada satu instance (15 menit)
3. **Simpan konfigurasi agent di Parameter Store.**
   a. Buka **Systems Manager**, menu **Parameter Store** (di grup *Application Management*), klik **Create parameter**.
   b. *Name*: `AmazonCloudWatch-lab-app-<nama>` (awalan `AmazonCloudWatch-` wajib; ganti `<nama>` dengan nama Anda tanpa tanda `<>`). *Tier*: **Standard**. *Type*: **String**. *Data type*: **text**.
   c. Pada *Value*, tempel JSON berikut (juga ada di `06-app/cwagent/agent-config.v1.json`):
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
   d. Klik **Create parameter**. **Checkpoint:** parameter muncul di daftar dengan *Version* 1.
   Perhatikan tiga bagian JSON: `metrics` (apa yang diukur dan dimensinya), `logs` (berkas mana yang dikirim), dan nilai `${aws:...}` yang diisi agent saat berjalan. Diskusikan: mengapa konfigurasi disimpan di satu tempat dan bukan disalin ke tiap server?
4. **Luncurkan instance `mon-solo-<nama>`.** EC2, **Instances**, **Launch instances**, lalu isi:
   a. *Name*: `mon-solo-<nama>`. *AMI*: **Amazon Linux 2023** (Free tier eligible). *Instance type*: **t3.micro**. *Key pair*: `key-<nama>`.
   b. *Network settings*, klik **Edit**: *VPC* default, satu subnet default, *Auto-assign public IP*: **Enable**. *Firewall*: **Select existing security group**, pilih `web-sg-<nama>`.
   c. Buka **Advanced details** (gulir ke bawah). *IAM instance profile*: **`lab-ec2-app`** (pilih tepat nama ini, bukan role lain yang mirip). *Detailed CloudWatch monitoring*: **Enable**. Pada **User data**, tempel seluruh isi `user-data.lab4.sh` (aplikasi `lab-app`; User Data ini **tidak** memasang agent).
   d. Klik **Launch instance**. Tunggu kolom *Status check* menjadi **2/2 checks passed**.
   e. **Checkpoint:** salin *Public IPv4 address*, buka `http://<public-ip>/` di browser (gunakan http, bukan https). Halaman status `lab-app` tampil. Bila tidak, tunggu 1 menit lalu muat ulang.
5. **Masuk ke instance dan periksa role.**
   a. Hubungkan ke instance. Cara SSH dari terminal laptop (seperti Lab 2): `ssh -i key-<nama>.pem ec2-user@<public-ip>`. Cara lain tanpa SSH lokal: pilih instance, klik **Connect**, tab **EC2 Instance Connect**, klik **Connect**.
   b. Periksa bahwa instance memiliki role:
      ```bash
      aws sts get-caller-identity
      ```
      **Checkpoint:** keluaran memuat `assumed-role/lab-ec2-app/i-...`. **Nama role harus tepat `lab-ec2-app`**; role lain yang mirip (misalnya `AmazonSSMManagedInstanceCore`) tidak punya izin mengirim metrik dan log. Bila muncul `Unable to locate credentials` atau nama role lain, perbaiki: EC2, pilih instance, **Actions**, **Security**, **Modify IAM role**, pilih `lab-ec2-app`, **Update IAM role**, tunggu sekitar 30 detik, lalu ulangi perintah.
6. **Pasang dan jalankan agent.** Di sesi SSH tadi:
   a. Pasang paket:
      ```bash
      sudo dnf install -y amazon-cloudwatch-agent
      ```
      **Checkpoint:** baris akhir `Complete!`.
   b. Muat konfigurasi dari Parameter Store dan jalankan agent (satu perintah; ganti `<nama>`):
      ```bash
      sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 \
        -c ssm:AmazonCloudWatch-lab-app-<nama> -s
      ```
      `fetch-config` mengambil konfigurasi dari Parameter Store, `-s` memulai (start) agent, dan `-m ec2` memberi tahu bahwa agent berjalan di EC2. **Checkpoint:** keluaran berisi pesan bahwa validasi konfigurasi berhasil (*Configuration validation succeeded*), dan tidak ada baris `E!`.
   c. Periksa status:
      ```bash
      sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
      ```
      **Checkpoint:** `"status": "running"` dan `"configstatus": "configured"`.
   d. Pastikan agent tetap hidup setelah reboot dan lihat lognya:
      ```bash
      systemctl is-enabled amazon-cloudwatch-agent
      sudo tail -20 /opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log
      ```
      Keluaran pertama harus `enabled`. Bila log berisi baris `E!`, lihat tabel Pemecahan Masalah.
7. **Hasilkan sedikit log, lalu lihat metrik dan log baru.**
   a. Di sesi SSH: `curl localhost/error` dua kali, lalu `curl localhost/` sekali. Tunggu 1 sampai 2 menit.
   b. CloudWatch, **Metrics**, **Classic metrics**, tab **Browse**. Klik kartu **CWAgent** di antara kartu namespace lain (ApplicationELB, EC2, dan seterusnya; tidak ada bagian terpisah untuk namespace kustom). Bila kartu CWAgent belum ada, agent belum mengirim data: periksa `amazon-cloudwatch-agent-ctl -a status` dan log agent, lalu tunggu 1 sampai 2 menit dan muat ulang.
   c. Klik grup dimensi **InstanceId**, lalu centang `mem_used_percent` milik instance `mon-solo-<nama>` (cocokkan *InstanceId*). **Checkpoint:** grafik muncul dengan nilai antara sekitar 10% dan 40%. Lihat juga `disk_used_percent` pada grup dimensi disk.
   d. CloudWatch, **Logs**, **Log groups**: ada `/lab/lab-app`; buka dan temukan stream yang namanya sama dengan instance ID Anda. Baris log berformat JSON (`level`, `path`, `status`, `ms`).
   e. Catat dimensi yang tersedia pada instance ini (`InstanceId`; tidak ada `AutoScalingGroupName` karena instance ini bukan anggota ASG). Pada Lab 6 Anda memasang agent yang sama pada ASG, dan dimensinya berbeda.

## Bagian D: Alarm (12 menit)
Alarm pertama dibuat dengan langkah lengkap. Alarm berikutnya memakai pola yang sama dan hanya nilainya yang berbeda.

8. **Alarm CPU `cpu-high-<nama>` (langkah lengkap).**
   a. CloudWatch, **Alarms**, **All alarms**, **Create alarm**, **Select metric**.
   b. Pilih **EC2**, lalu **By Auto Scaling Group**, centang baris `asg-app-<nama>` dengan metrik **CPUUtilization**, klik **Select metric**.
   c. *Specify metric and conditions*: *Statistic* **Average**, *Period* **1 minute**, *Threshold type* **Static**, *Whenever CPUUtilization is* **Greater**, *than* **70**.
   d. Buka **Additional configuration**: *Datapoints to alarm* **2 out of 3**, *Missing data treatment* **Treat missing data as missing**. Klik **Next**.
   e. *Configure actions*: *Alarm state trigger* **In alarm**, **Select an existing SNS topic**, pilih `ops-alerts-<nama>`. Klik **Add notification**, ulangi untuk state **OK** dengan topik yang sama. Klik **Next**.
   f. *Alarm name* `cpu-high-<nama>`. *Alarm description*: langkah pertama triage, misalnya `Periksa tab Activity ASG dan endpoint /cpu`. Klik **Next**, lalu **Create alarm**.
   g. **Checkpoint:** alarm tampil di daftar; status awal `Insufficient data`, lalu `OK` setelah beberapa menit.
9. **Uji jalur notifikasi tanpa menunggu kondisi nyata.**
   a. Buka **AWS CloudShell** (ikon terminal di bilah atas konsol). Pastikan Region yang sama.
   b. Jalankan:
      ```bash
      aws cloudwatch set-alarm-state --alarm-name cpu-high-<nama> --state-value ALARM --state-reason "uji"
      ```
   c. **Checkpoint:** email alarm diterima dalam 1 menit dan status alarm di konsol menjadi `In alarm`. Kembalikan: ulangi perintah dengan `--state-value OK`. Diskusikan: alarm yang tidak pernah diuji ujungnya sering ternyata tidak sampai ke siapa pun.
10. **Alarm memori `mem-high-<nama>`** (hanya mungkin berkat agent). Ikuti pola langkah 8 dengan nilai berikut: metrik dari namespace **CWAgent**, grup dimensi **InstanceId**, `mem_used_percent` milik `mon-solo-<nama>`; *Statistic* Average; *Period* 1 minute; *Greater than* **80**; *Datapoints* **2 out of 3**; missing data *as missing*; aksi *In alarm* dan *OK* ke `ops-alerts-<nama>`. Diskusikan: mengapa memori yang naik terus tanpa turun (kebocoran) lebih berbahaya dibanding lonjakan sesaat, dan alarm apa yang cocok untuknya?
11. **Alarm target tidak sehat `tg-unhealthy-<nama>`.** Pola langkah 8. Metrik: namespace **ApplicationELB**, grup dimensi **Per AppELB, per TG Metrics**, baris `UnHealthyHostCount` untuk Target Group `tg-app-<nama>` dan ALB Anda. *Statistic* **Maximum**, *Period* 1 minute, *Greater/Equal* **1**, *Datapoints* **2 out of 2**, aksi ke topik yang sama.
12. **Alarm error 5xx `alb-5xx-<nama>`.** Pola langkah 8. Metrik: namespace **ApplicationELB**, grup dimensi **Per AppELB Metrics**, `HTTPCode_Target_5XX_Count` (error 5xx yang dikirim aplikasi, seperti `/error`). Bandingkan dengan `HTTPCode_ELB_5XX_Count` (error buatan ALB sendiri, misalnya 503 saat tidak ada target sehat). *Statistic* **Sum**, *Period* 1 minute, *Greater/Equal* **5**, *Datapoints* 1 out of 1, *Missing data treatment* **Treat missing data as good (not breaching)**, aksi ke topik yang sama.

## Bagian E: Dashboard kustom (10 menit)
Dashboard yang baik menjawab pertanyaan operasi pada satu layar: *sehat atau tidak, di mana, dan sejak kapan*. Anda merancangnya sendiri.

13. **Buat dashboard dan tambahkan widget.** CloudWatch, **Dashboards**, **Create dashboard**, nama `ops-<nama>`, **Create dashboard**. Jendela *Add widget* terbuka. Tambahkan widget berikut satu per satu; setelah memilih jenis, klik **Next** atau **Create widget** sesuai wizard, lalu **Add widget** lagi untuk berikutnya:
    | # | Jenis widget | Isi | Alasan |
    |---|---|---|---|
    | 1 | **Text** | Markdown: `# lab-app (<nama>)` lalu baris `Eskalasi: ...` dan `Runbook: ...` | Orang yang dibangunkan pukul 03.00 perlu konteks |
    | 2 | **Number** | Tab *Metrics*, **ApplicationELB**, *Per AppELB, per TG Metrics*: `HealthyHostCount` dan `UnHealthyHostCount` | Jawaban cepat: berapa target sehat |
    | 3 | **Line** | `CPUUtilization` ASG `asg-app-<nama>` **dan** `CPUUtilization` instance `mon-solo-<nama>` pada satu grafik (EC2, *By Auto Scaling Group* dan *Per-Instance Metrics*) | Membandingkan grup dengan instance tunggal |
    | 4 | **Line** | CWAgent, grup **InstanceId**, `mem_used_percent` milik `mon-solo-<nama>`. Pada tab *Options* (atau *Graph options*), **Horizontal annotations**, **Add horizontal annotation**: nilai 80, label "ambang mem-high" | Ambang terlihat langsung pada grafik |
    | 5 | **Line** dengan **metric math** | Tambahkan `RequestCount` (id `m1`, Sum) dan `HTTPCode_Target_5XX_Count` (id `m2`, Sum) dari *Per AppELB Metrics*. Pada tab *Graphed metrics*, **Add math**, **Start with empty expression**, isi `100 * m2 / m1`, *Label* `5xx %`. Hilangkan centang pada m1 dan m2 bila ingin | Persentase error lebih bermakna daripada jumlah mentah |
    | 6 | **Alarm status** | Pilih seluruh alarm `-<nama>` milik Anda | Ringkasan semua alert |
    Simpan berkala dengan **Save dashboard** (tombol di kanan atas). **Checkpoint:** enam widget tampil; widget yang kosong biasanya karena dimensi atau rentang waktu (lihat Pemecahan Masalah).
14. **Atur ulang tata letak.** Seret kepala widget agar ringkasan (text, number, alarm status) berada di baris atas dan detail di bawah; ubah ukuran dengan menyeret sudut kanan bawah. Aturan: tampilkan yang menentukan keputusan di atas. Atur *time range* **1h** pada bilah atas dan **auto refresh** 1 menit (ikon refresh, *Auto refresh*, **1 Minute**), lalu **Save dashboard**.
15. **Ubah lewat JSON.** Klik **Actions**, **View/edit source**. Temukan widget CPU, ubah nilai `"title"` atau `"period"` langsung di JSON, klik **Update** lalu **Save dashboard**. Dashboard adalah dokumen JSON, sehingga dapat disalin ke dashboard lain atau disimpan di repositori. Opsional di CloudShell: `aws cloudwatch get-dashboard --dashboard-name ops-<nama> --query DashboardBody --output text > ops.json`.

## Bagian F: Picu dan amati (8 menit)
16. **Siapkan CloudShell.** Variabel dan berkas di CloudShell dapat hilang bila sesi berakhir. Periksa:
    ```bash
    echo $ALB
    ls loadgen.sh
    ```
    Bila `$ALB` kosong, atur ulang dengan DNS name ALB (EC2, **Load Balancers**, `alb-app-<nama>`, salin *DNS name*): `export ALB=http://<dns-alb>` (tanpa garis miring di akhir). Bila `loadgen.sh` tidak ada, unggah lagi (**Actions**, **Upload file**).
17. **Picu tiga kondisi satu per satu** dan pastikan alarm yang sesuai berubah ke ALARM dan email diterima. Amati juga dashboard Anda.
    | Pemicu | Alert yang diharapkan | Apa yang diamati |
    |---|---|---|
    | `curl $ALB/health/fail` berulang hingga mengenai satu instance | `tg-unhealthy` | Target Group, tab Targets, kolom *Health status details*; widget 2 |
    | `for i in $(seq 20); do curl -s -o /dev/null $ALB/error; done` | `alb-5xx` | Widget 5 (persentase 5xx naik) |
    | `bash loadgen.sh cpu $ALB 6 300` | `cpu-high` | Widget 3 (CPU ASG naik) dan tab Activity ASG |
18. **Pemulihan.** `curl $ALB/health/ok` (ulangi agar mengenai instance yang tepat), `curl $ALB/cpu/stop` (ulangi), lalu pastikan alarm kembali ke OK (beberapa menit).
19. **Diskusi desain alert** (5 menit): apakah alert ini *actionable*? Gunakan severity berbeda (siapa yang dibangunkan pukul 03.00 dan siapa yang cukup membaca esok pagi?), *M out of N datapoints* dan *treat missing data* agar tidak berkedip, dan *composite alarm* untuk mengurangi kebisingan. Tujuan akhir alert (email, chat, pager) dibahas sebagai teori (AWS Chatbot atau Lambda ke webhook).

**Demo trainer (5 menit):** alert biaya. Tunjukkan Budget dari Lab 1 dan Cost Anomaly Detection. Billing alarm CloudWatch hanya ada di Region us-east-1 sehingga tidak dikerjakan peserta. Trainer juga menjelaskan bahwa instance ASG belum memiliki agent dan akan dipasang lewat Launch Template pada Lab 6, serta cara memperbarui konfigurasi agent di banyak instance tanpa SSH (SSM Run Command atau State Manager dengan dokumen `AmazonCloudWatch-ManageAgent`) sebagai teori.

## Pertanyaan Operasi
- Alert apa yang berbunyi bila satu AZ mati? Berapa lama sampai Anda tahu, dan siapa yang menerimanya?
- Alert apa yang *tidak* ada tetapi seharusnya ada (misalnya latensi, disk, atau kegagalan tunnel pada Lab 8)?
- Bagaimana membedakan masalah aplikasi, instance, dan jaringan hanya dari metrik?
- Bagaimana Anda memastikan setiap server baru otomatis dimonitor, dan siapa yang tahu bila agent mati?

## Validasi
Agent berjalan pada `mon-solo-<nama>` dan `mem_used_percent` terlihat di namespace CWAgent, log group `/lab/lab-app` memiliki stream instance itu, email uji dan email alarm diterima, keempat alarm berstatus OK saat stack sehat, dashboard `ops-<nama>` menampilkan enam widget (termasuk annotation, metric math, dan alarm status), dan ketiga kondisi yang dipicu menghasilkan alert dan kembali ke OK setelah dipulihkan.

## Pemecahan Masalah
| Gejala | Penyebab dan solusi |
|---|---|
| Email tidak diterima | Subscription masih *Pending confirmation*, email masuk ke spam, atau alamat salah |
| `dnf install` gagal atau lama | Instance tidak punya jalur internet (public IP/Security Group outbound), atau repositori belum siap; ulangi setelah satu menit |
| `fetch-config` gagal dengan `NoCredentialProviders: no valid providers in chain` | Instance **tidak memiliki IAM role**, sehingga agent tidak punya kredensial untuk membaca parameter. EC2, pilih instance, Actions, Security, Modify IAM role, pilih `lab-ec2-app`. Uji dengan `aws sts get-caller-identity` |
| Log agent berisi `AccessDeniedException ... assumed-role/<role lain>/... is not authorized to perform: logs:PutLogEvents` (juga `ec2:DescribeTags`) | Agent berjalan tetapi instance memakai **role yang salah** (bukan `lab-ec2-app`), jadi kirim metrik dan log ditolak dan namespace CWAgent tidak muncul. Ganti ke `lab-ec2-app` (Modify IAM role), cek `aws sts get-caller-identity`, lalu `sudo systemctl restart amazon-cloudwatch-agent` |
| `fetch-config` gagal atau `AccessDenied` pada `ssm:GetParameter` | Nama parameter tidak berawalan `AmazonCloudWatch-`, nama berbeda dengan yang diketik (`<nama>`), atau instance tidak memakai role `lab-ec2-app` |
| Status agent `stopped` / log agent berisi error JSON | Konfigurasi di parameter tidak valid (tanda kurung, koma, atau tanda kutip hilang); periksa `/opt/aws/amazon-cloudwatch-agent/logs/amazon-cloudwatch-agent.log`, perbaiki parameter, jalankan `fetch-config` lagi |
| Kartu `CWAgent` tidak ada di Classic metrics | Agent belum berjalan (`sudo systemctl status amazon-cloudwatch-agent`), role salah (baris sebelumnya), Region bukan Jakarta, atau tunggu 1 sampai 2 menit |
| Alarm `INSUFFICIENT_DATA` | Belum ada datapoint (tunggu 2 sampai 3 menit), nama dimensi atau namespace salah, atau metrik per menit belum aktif (detailed monitoring) |
| Log group `/lab/lab-app` kosong | Agent belum memuat konfigurasi, atau aplikasi belum menulis log (`curl localhost/` di instance sekali) |
| Alarm tidak kembali ke OK | Periode evaluasi belum lewat, atau beban masih berjalan (`/cpu/stop`) |
| Alarm 5xx tidak berbunyi | `/error` menghasilkan 500 dari aplikasi, yang dicatat ALB sebagai `HTTPCode_Target_5XX_Count`; `HTTPCode_ELB_5XX_Count` hanya untuk error yang dibuat ALB sendiri (502/503/504) |
| `$ALB` kosong atau `loadgen.sh` tidak ditemukan di CloudShell | Sesi CloudShell baru; atur ulang `export ALB=http://<dns-alb>` dan unggah ulang `loadgen.sh` |
| Widget dashboard kosong | Dimensi salah, rentang waktu terlalu pendek, atau metrik belum ada; periksa di *Classic metrics* lebih dulu |

## Cleanup
Pertahankan sampai Lab 6: instance `mon-solo-<nama>` (dipakai untuk menambah penerima trace), parameter `AmazonCloudWatch-lab-app-<nama>` (Lab 6 menambah versi 2), dashboard, dan topik SNS. Pada akhir Hari 2 hapus alarm (`cpu-high`, `mem-high`, `tg-unhealthy`, `alb-5xx`), instance `mon-solo-<nama>`, dan parameter; dashboard boleh disimpan (gratis, tiga pertama). **Pertahankan topik SNS `ops-alerts-<nama>` dan subscription-nya** karena dipakai pada Lab 8 (Hari 3); topik itu dihapus pada Lab 10. Log group `/lab/lab-app` boleh dibiarkan (retensi 1 hari) dan dihapus pada Lab 10.
