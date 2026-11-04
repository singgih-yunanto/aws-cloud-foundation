# Lab 7: Menjalankan Aplikasi di Amazon ECS, Fargate lalu EC2 sebagai Pembanding (90 menit, Hari 3)

**Tujuan:** peserta men-deploy `lab-app` sebagai container di **ECS Fargate** di belakang ALB, memahami hubungan task definition, service, task, target group, dan Security Group, mengamati penggantian task otomatis, rolling deployment, serta deployment yang gagal dan dibatalkan otomatis (circuit breaker). Pada Bagian B, aplikasi yang sama dijalankan di **ECS dengan launch type EC2** di cluster yang sama, lalu keduanya dibandingkan. Alasannya: di lingkungan yang dikelola vendor, Anda perlu tahu apa yang vendor bangun, apa yang terlihat dari CloudWatch, dan jenis kegagalan apa yang khas untuk masing-masing model.

**Biaya:** sekitar $0,1 per jam per peserta (dua task Fargate 0,25 vCPU, ALB, alamat IPv4 publik, satu `t3.small` pada Bagian B, Container Insights); total beberapa puluh sen bila semua dihapus pada akhir hari. Image sudah disiapkan trainer di ECR.

**Status:** belum diuji pada akun AWS yang sebenarnya (Fargate dan ECS EC2 di Region Jakarta, wizard console, circuit breaker). Nama menu pada console ECS sering berubah; bila berbeda, ikuti maksud langkahnya dan catat perbedaannya untuk trainer.

## Prasyarat
- Trainer sudah membangun image `lab-app` (tag `v1`, `v2`, `v-bad`) di ECR dan menyiapkan kebijakan `lab-ecs-create-log-group`. **Tiga role IAM Anda buat sendiri di Langkah 0.**
- Anda memakai **default VPC** dengan subnet publik di dua AZ. Subnet dan route table tidak diubah di lab ini (VPC buatan sendiri dibangun pada Lab 10).
- Di **CloudShell** (Region Jakarta) Anda dapat menjalankan `curl`. Ganti `<nama>` dengan nama Anda (huruf kecil) di semua nama sumber daya.

## Peta Sumber Daya

| Sumber daya | Nama | Keterangan |
|---|---|---|
| Cluster ECS | `ecs-<nama>` | Wadah logis; Container Insights aktif |
| Task definition | `td-app-<nama>` | Resep task: image, CPU, memori, port, env, log, role |
| Service | `svc-app-<nama>` | Menjaga jumlah task dan menghubungkannya ke target group |
| ALB, target group | `alb-ecs-<nama>`, `tg-ecs-<nama>` | Target group bertipe **ip** (task awsvpc memiliki IP sendiri) |
| Security Group | `alb-sg-<nama>`, `task-sg-<nama>` | `task-sg` hanya menerima port 8080 dari `alb-sg` |
| Log group | `/ecs/lab-app-<nama>` | Dibuat otomatis oleh task execution role |
| Role execution | `lab-ecs-task-execution-<nama>` | Dipakai ECS agent: menarik image, menulis log |
| Role task | `lab-ecs-task-<nama>` | Dipakai kode di dalam container (X-Ray pada Lab 9) |
| Role instance (Bagian B) | `lab-ecs-instance-<nama>` | Dipakai container instance EC2 untuk mendaftar ke cluster |

## Bagian A: Fargate di belakang ALB (62 menit)
0. **Buat tiga role IAM (8 menit).** IAM, Roles, **Create role**. Ketiganya berawalan `lab-ecs-` dan berakhiran nama Anda; guardrail akun lab hanya mengizinkan nama itu, dan hanya mengizinkan kebijakan yang tercantum di bawah.

   Peserta yang bekerja di lingkungan vendor biasanya tidak membuat role. Tetapi dengan membuatnya sendiri, Anda tahu persis apa yang dimiliki masing-masing role, sehingga saat membaca task definition vendor Anda dapat bertanya: "role mana yang dipakai, dan izin apa yang ada di dalamnya?"

   - **a.** Role **execution**. *Trusted entity type* **AWS service**; *Use case* **Elastic Container Service**, lalu pilih **Elastic Container Service Task**. **Next**. Pada *Add permissions*, centang dua kebijakan: **`AmazonECSTaskExecutionRolePolicy`** dan **`lab-ecs-create-log-group`** (cari dengan kata kunci `lab-ecs`). *Role name* `lab-ecs-task-execution-<nama>`. **Create role**.

      *Mengapa dua kebijakan:* `AmazonECSTaskExecutionRolePolicy` mengizinkan ECS agent menarik image dari ECR dan menulis log (`logs:CreateLogStream`, `logs:PutLogEvents`), tetapi **tidak** membuat log group. Kebijakan `lab-ecs-create-log-group` menambahkan `logs:CreateLogGroup` agar opsi `awslogs-create-group` pada langkah 4e bekerja. Tanpa itu, task berhenti dengan `ResourceInitializationError`.

      Isi kebijakan `lab-ecs-create-log-group` (buatan trainer; untuk dibaca, bukan diketik). Klik namanya di daftar kebijakan, tab **JSON**:

      ```json
      {
        "Version": "2012-10-17",
        "Statement": [{
          "Effect": "Allow",
          "Action": "logs:CreateLogGroup",
          "Resource": "arn:aws:logs:ap-southeast-3:<akun>:log-group:/ecs/*"
        }]
      }
      ```
   - **b.** Role **task**. Ulangi dengan *Use case* yang sama (**Elastic Container Service Task**), centang **`AWSXRayDaemonWriteAccess`**, *Role name* `lab-ecs-task-<nama>`. **Create role**.

      *Mengapa X-Ray sekarang:* Lab 7 dan 8 tidak memerlukan izin apa pun dari role ini, tetapi pada Lab 9 sidecar pengirim trace memakainya. Membuatnya sekarang berarti task definition Lab 9 cukup mengganti isi, bukan membuat role baru. Role ini milik **aplikasi**, sedangkan role pada langkah a milik **platform ECS**.
   - **c.** Role **instance** (dipakai di Bagian B). *Trusted entity type* **AWS service**; *Use case* **EC2**. **Next**. Centang **`AmazonEC2ContainerServiceforEC2Role`**. *Role name* `lab-ecs-instance-<nama>`. **Create role**.

      *Mengapa:* pada launch type EC2, server yang menjalankan container harus mendaftar ke cluster dan menarik image; role ini memberi izin itu. Konsol otomatis membuat *instance profile* dengan nama yang sama, yang nanti dipilih pada Auto Scaling group.
   - **d.** Buka salah satu role (`lab-ecs-task-execution-<nama>`), tab **Trust relationships**. Temukan `"Service": "ecs-tasks.amazonaws.com"` dan `"Action": "sts:AssumeRole"`. Bandingkan dengan tab **Permissions**.

      Trust policy role **execution** dan **task** (ECS) berbentuk:

      ```json
      {
        "Version": "2012-10-17",
        "Statement": [{
          "Effect": "Allow",
          "Principal": {"Service": "ecs-tasks.amazonaws.com"},
          "Action": "sts:AssumeRole"
        }]
      }
      ```

      Pada role **instance** (EC2), hanya `Principal`-nya yang berbeda: `{"Service": "ec2.amazonaws.com"}`. Wizard console mengisinya otomatis dari *Use case* yang Anda pilih; bila salah pilih, di sinilah kesalahannya terlihat.

      *Artinya:* **trust policy** menjawab *siapa boleh memakai role ini* (di sini hanya layanan ECS Tasks), **permissions policy** menjawab *apa yang boleh dilakukan pemakainya*. Dua pertanyaan berbeda yang sering tertukar.

   **Checkpoint:** tiga role ada di daftar Roles (filter `lab-ecs-`); role execution memiliki **2** kebijakan, role task **1**, role instance **1**. Bila muncul `AccessDenied` saat Create role, periksa nama (harus berawalan `lab-ecs-`) dan kebijakan yang dicentang (hanya yang tercantum di atas).

1. **Lihat image di ECR (4 menit).** ECR, Repositories, `lab-app`.
   - **a.** Catat tiga tag: `v1`, `v2`, `v-bad`. Salin **Image URI** tag `v1` (bentuk `<akun>.dkr.ecr.ap-southeast-3.amazonaws.com/lab-app:v1`) ke catatan Anda.
   - **b.** Buka hasil *scan* (tab *Vulnerabilities* pada image). Image ini sengaja memakai base image kecil; temuan tidak perlu diperbaiki, cukup dikenali.
   - **c.** Diskusikan: tag adalah label yang dapat dipindahkan, sedangkan *digest* (`sha256:...`) tidak. Mengapa vendor yang disiplin men-deploy dengan digest atau tag unik per rilis, dan mengapa tag `latest` menyulitkan pelacakan perubahan?

   **Checkpoint:** Anda memegang Image URI `v1` dan tahu `v-bad` ada.

2. **Buat cluster `ecs-<nama>`.** ECS, Clusters, **Create cluster**.
   - **a.** *Cluster name* `ecs-<nama>`. *Infrastructure*: biarkan **AWS Fargate (serverless)** tercentang.
   - **b.** Buka *Monitoring* dan pilih **Container Insights** (versi standar; versi *enhanced observability* menambah biaya dan tidak diperlukan di lab). Klik **Create**.

   **Mengapa Container Insights sekarang:** metrik CPU, memori, dan jumlah task per service hanya mulai tercatat sejak fitur ini aktif. Lab 8 memakainya.

   **Checkpoint:** cluster berstatus *Active*, 0 services, 0 tasks.

3. **Security Group, target group, dan ALB (EC2 console, 10 menit).** Lakukan sebelum membuat service agar Anda mengendalikan jaringan sendiri.
   - **a.** EC2, Security Groups, Create: `alb-sg-<nama>` di default VPC, inbound **HTTP 80 dari Anywhere-IPv4**. Lalu `task-sg-<nama>`: inbound **Custom TCP 8080** dengan *Source* = **`alb-sg-<nama>`** (pilih Security Group, bukan CIDR). Outbound biarkan semua.

      *Mengapa:* task hanya boleh dijangkau dari ALB; mereferensikan Security Group membuat aturan tetap benar walau IP ALB berubah.
   - **b.** EC2, Target Groups, Create: *target type* **IP addresses** (bukan Instances), nama `tg-ecs-<nama>`, protokol HTTP port **8080**, VPC default. *Health check path* `/health`. Klik Next, **jangan mendaftarkan target secara manual**, lalu Create.

      *Mengapa tipe IP:* task awsvpc memiliki ENI dan IP privat sendiri; ECS mendaftarkan dan mencabut IP itu otomatis.
   - **c.** EC2, Load Balancers, Create **Application Load Balancer** `alb-ecs-<nama>`: internet-facing, default VPC, **dua AZ**, Security Group `alb-sg-<nama>`, listener HTTP 80 yang *forward* ke `tg-ecs-<nama>`. Create.
   - **d.** Setelah ALB *Active*, di CloudShell: `ALB=http://<DNS name ALB>` (tanpa garis miring di akhir).

   **Checkpoint:** ALB *Active*; target group `tg-ecs-<nama>` kosong (0 target); `curl -s -o /dev/null -w '%{http_code}\n' $ALB/` menghasilkan `503` (belum ada target).

4. **Task definition `td-app-<nama>`.** ECS, Task definitions, Create new task definition.
   - **a.** *Task definition family* `td-app-<nama>`. *Launch type*: **AWS Fargate**. *OS/Architecture* **Linux/X86_64**. *Task size*: CPU **.25 vCPU**, Memory **.5 GB**.
   - **b.** *Task role* **`lab-ecs-task-<nama>`**; *Task execution role* **`lab-ecs-task-execution-<nama>`** (kedua role buatan Anda di Langkah 0; pilih dari daftar, jangan memilih "Create new role").

      *Dua role, dua fungsi:* **execution role** dipakai ECS agent untuk menarik image dari ECR dan menulis log; **task role** dipakai kode aplikasi di dalam container untuk memanggil layanan AWS (misalnya X-Ray pada Lab 9). Salah satu salah pilih adalah penyebab gagal start yang paling umum.
   - **c.** *Container-1*: *Name* `app`, *Image URI* = URI `v1` dari langkah 1, *Essential* **Yes**. *Port mappings*: Container port **8080**, Protocol **TCP**, App protocol **HTTP**.
   - **d.** *Environment variables* (Add): `TRACING` = `off`, `DB_MODE` = `mock`.
   - **e.** *Logging*: aktifkan **Use log collection** (awslogs). Isi `awslogs-group` = `/ecs/lab-app-<nama>`, `awslogs-region` = `ap-southeast-3`, `awslogs-stream-prefix` = `app`, dan pastikan `awslogs-create-group` = `true`.
   - **f.** **Create**. **Checkpoint:** task definition `td-app-<nama>:1` berstatus *Active*; buka tab *JSON* dan temukan image, port, dan log yang baru Anda isi (inilah isi yang akan dibandingkan antar revisi).

5. **Service `svc-app-<nama>`.** Buka cluster `ecs-<nama>`, tab *Services*, **Create**.
   - **a.** *Compute options*: **Launch type** **FARGATE**. *Application type* **Service**. *Task definition* family `td-app-<nama>`, revision **1 (LATEST)**. *Service name* `svc-app-<nama>`. *Desired tasks* **2**.
   - **b.** *Deployment options*: tipe **Rolling update**, *Min running tasks* **100** %, *Max running tasks* **200** %. Aktifkan **Deployment failure detection**: **Use the Amazon ECS deployment circuit breaker** dan **Rollback on failures**.

      *Artinya:* saat deployment, task baru dinyalakan lebih dulu (maksimal dua kali jumlah) dan task lama baru dimatikan setelah yang baru sehat, sehingga kapasitas tidak turun. Bila task baru terus gagal, ECS membatalkan deployment dan kembali ke revisi sebelumnya.
   - **c.** *Networking*: VPC default, pilih **dua subnet di AZ berbeda**, hapus Security Group `default` dan pilih **`task-sg-<nama>`**, **Public IP: Turned on**.

      *Mengapa public IP:* task harus menjangkau ECR dan CloudWatch Logs lewat internet. Tanpa public IP, Anda memerlukan NAT Gateway atau VPC endpoint (lihat diskusi di bawah).
   - **d.** *Load balancing*: **Application Load Balancer**, **Use an existing load balancer** `alb-ecs-<nama>`, *Container* `app 8080:8080`, listener yang ada (80), *Target group* yang ada `tg-ecs-<nama>`. *Health check grace period* **30** detik.
   - **e.** **Create**. Tunggu 2 sampai 4 menit.

   **Checkpoint:** tab *Tasks* menampilkan 2 task **Running** (kolom *Last status*), tab *Deployments* menampilkan *Completed*, dan target group menampilkan 2 target **healthy** (IP privat dari subnet default).

   **Diskusi (5 menit):** task Anda punya IP publik karena tidak ada NAT. Apa konsekuensinya bagi keamanan, biaya (IPv4 publik berbayar), dan bagi layanan eksternal yang memakai *allowlist* IP, misalnya MongoDB Atlas? Jalan keluarnya: NAT Gateway dengan IP tetap, VPC peering, atau PrivateLink.

6. **Uji aplikasi dan baca identitas task.** Di CloudShell:

   ```bash
   curl -s $ALB/version; echo
   for i in $(seq 20); do curl -s $ALB/id; done | sort | uniq -c
   ```

   `/version` menampilkan `version`, ID task, AZ, serta `ecs.launch_type`, `family`, dan `revision`. Hitungan `/id` menunjukkan sebaran antar dua task. **Checkpoint:** `launch_type` = `FARGATE`, `revision` = 1, dua ID task berbeda di dua AZ berbeda.

7. **Task mati, task pengganti.** ECS, `ecs-<nama>`, `svc-app-<nama>`, tab *Tasks*, pilih satu task, **Stop**. Amati tab *Events* pada service dan tab *Tasks*.
   - **a.** Catat urutan peristiwa dan berapa lama sampai jumlah task kembali 2 dan target kembali *healthy*.
   - **b.** Diskusi: apa yang mengganti task (service scheduler), apa bedanya dengan ASG di Lab 4 (ASG mengganti *instance*; ECS service mengganti *task*), dan di mana jejak penghentian itu tercatat (tab *Stopped* pada task: *Stopped reason* dan *Stop code*).

   **Checkpoint:** 2 task *Running* kembali; task yang dihentikan terlihat di filter *Stopped* dengan *Stopped reason* `Task stopped by user`.

8. **Deploy versi baru (rolling).** Task definition `td-app-<nama>`, revision 1, **Create new revision**: ubah **hanya Image URI** menjadi tag **`v2`** (label versi aplikasi sudah tertanam di image, jadi tidak ada variabel lain yang diubah). **Create**.
   - **a.** Service `svc-app-<nama>`, **Update**: *Revision* **2 (LATEST)**, centang *Force new deployment* bila tersedia, **Update**.
   - **b.** Selama berjalan, jalankan di CloudShell: `for i in $(seq 40); do curl -s $ALB/version | python3 -c 'import sys,json; print(json.load(sys.stdin)["version"])'; sleep 2; done | uniq -c`. Anda melihat `v1` berganti `v2` tanpa ada jeda di mana situs mati.
   - **c.** Buka tab *Deployments* pada service: ada dua deployment (lama dan baru), jumlah task masing-masing, dan status *Rollout state*.

   **Checkpoint:** semua jawaban `/version` `v2`, `revision` 2, dan *Deployments* hanya menampilkan satu deployment *Completed*.

9. **Deployment yang gagal dan dibatalkan otomatis.** Buat revision 3 dari `td-app-<nama>` dengan **Image URI yang salah**: ganti tag menjadi `v999` (tidak ada di ECR). Update service ke revision 3.
   - **a.** Amati tab *Events* dan *Deployments* selama beberapa menit. Task baru tidak pernah *Running*; pada tab *Tasks* (filter *Stopped*) baca *Stopped reason*: `CannotPullContainerError` ... `not found`.
   - **b.** Setelah beberapa kegagalan beruntun, circuit breaker menandai deployment *Failed* dan service **kembali ke revisi sebelumnya** (revision 2). Selama itu, task lama (revision 2) tetap melayani, jadi `curl $ALB/version` tetap berhasil dan `v2`.

   **Checkpoint:** *Deployments* menampilkan deployment revision 3 berstatus *Rollback* atau *Failed*, service kembali pada revision 2 dengan 2 task *Running*, dan pesan *Events* menyebut deployment gagal atau rollback.

   **Pelajaran operasi:** kegagalan *saat start* (image, role, kuota, jaringan) dicegat circuit breaker. Kegagalan *setelah* start yang lolos health check (lihat Lab 8) tidak dicegat; hanya pemantauan yang menangkapnya.

## Bagian B: ECS dengan launch type EC2 sebagai pembanding (28 menit)
Tujuannya bukan membangun produksi, melainkan merasakan perbedaan tanggung jawab dan kegagalan antara Fargate dan EC2.

10. **Tambah kapasitas EC2 ke cluster (7 menit).** Cluster `ecs-<nama>`, tab *Infrastructure*, **Create** pada *Capacity providers* (atau *Add capacity*), pilih **Auto Scaling group** baru.
    - **a.** *Provisioning model* **On-demand**, *Container instance AMI* **Amazon Linux 2023** (ECS-optimized), *EC2 instance type* **t3.small**, *Desired capacity* **1**, *Maximum* **1**.
    - **b.** *Container instance IAM role*: **`lab-ecs-instance-<nama>`** (buatan Anda di Langkah 0c). *Network*: default VPC, **satu subnet publik**. Security Group baru bernama `ecs-ec2-sg-<nama>` tanpa inbound (tidak diperlukan; task memiliki Security Group sendiri).
    - **c.** Beri nama ASG `asg-ecs-<nama>`. Create.

    **Checkpoint (3 sampai 5 menit kemudian):** tab *Infrastructure* menampilkan **1 container instance** *Active* dengan *Registered CPU* 2048 dan *Memory* sekitar 1,9 GB. Buka EC2 console: instance `t3.small` itu benar-benar ada, bisa dilihat, dan membawa biaya per jam sekalipun tidak ada task.

11. **Task definition untuk EC2.** Buat task definition baru `td-app-ec2-<nama>`: *Launch type* **Amazon EC2 instances**, *Network mode* **awsvpc**, *Task size* **.25 vCPU / .5 GB**, role seperti langkah 4 (task role `lab-ecs-task-<nama>`, execution role `lab-ecs-task-execution-<nama>`), container `app` image tag **`v2`**, port 8080, env `TRACING=off`, `DB_MODE=mock`, dan awslogs yang sama (`/ecs/lab-app-<nama>`, prefix `app-ec2`).

12. **Target group kedua dan service EC2.**
    - **a.** Buat target group `tg-ecs-ec2-<nama>` (tipe IP, HTTP 8080, health `/health`), seperti langkah 3b. (Satu target group hanya boleh dipakai satu service ECS.)
    - **b.** ALB `alb-ecs-<nama>`, tab *Listeners*, listener HTTP 80, **Manage rules / Edit**: *Default action* **Forward to target groups** ke **dua** target group, bobot `tg-ecs-<nama>` **50** dan `tg-ecs-ec2-<nama>` **50**.
    - **c.** Cluster, tab *Services*, **Create**: *Compute options* **Capacity provider strategy** (pilih provider ASG `asg-ecs-<nama>`), task definition `td-app-ec2-<nama>`, *Service name* `svc-app-ec2-<nama>`, *Desired tasks* **1**, jaringan: subnet yang sama dengan container instance, Security Group `task-sg-<nama>`, **public IP tidak tersedia** pada awsvpc di EC2, load balancer yang ada dengan target group `tg-ecs-ec2-<nama>`.

       *Catatan:* pada launch type EC2, image ditarik dan log dikirim oleh container instance (memakai jaringan instance), jadi task tidak butuh public IP untuk itu. Namun bila aplikasi sendiri perlu menjangkau internet, jalurnya lewat ENI task yang privat dan memerlukan NAT.

    **Checkpoint:** 1 task *Running* di container instance, target `tg-ecs-ec2-<nama>` *healthy*; `for i in $(seq 30); do curl -s $ALB/version; done | grep -o '"launch_type": *"[A-Z]*"' | sort | uniq -c` menampilkan **FARGATE dan EC2** bersama-sama.

13. **Kapasitas habis.** Naikkan *Desired tasks* `svc-app-ec2-<nama>` menjadi **4**. Amati tab *Tasks* dan *Events* selama 2 sampai 3 menit. Hanya sebagian task yang naik; sisanya `PENDING`, dan *Events* menulis bahwa service tidak dapat menempatkan task karena tidak ada container instance yang memenuhi syarat (sumber daya memori, CPU, atau **ENI** tidak cukup; awsvpc memakai satu ENI per task dan `t3.small` hanya memiliki 3 ENI).
    - **a.** Catat jumlah task *Running* dan pesan persisnya. Pada tab *Infrastructure*, bandingkan *Registered* dan *Available* untuk CPU, memori, dan ENI.
    - **b.** Bandingkan dengan Fargate: naikkan juga `svc-app-<nama>` dari 2 menjadi 4 sebentar. Task tambahan langsung diprovisikan tanpa memikirkan kapasitas mesin. Kembalikan ke 2.

    **Checkpoint:** Anda dapat menyebut dua hal: mengapa task EC2 `PENDING` dan siapa yang harus menambah kapasitas (Anda atau vendor, lewat ASG/capacity provider) pada model EC2.

14. **Tabel pembanding (6 menit, dibahas bersama).** Isi sendiri lalu cocokkan dengan kelas:

    | Aspek | Fargate | ECS launch type EC2 |
    |---|---|---|
    | Siapa menyediakan dan menambal server | ? | ? |
    | Perencanaan kapasitas | ? | ? |
    | Penskalaan | ? | ? |
    | Biaya | ? | ? |
    | Apa yang terlihat di EC2 console | ? | ? |
    | Jenis kegagalan khas | ? | ? |
    | Akses ke host (SSH) | ? | ? |

    **Pertanyaan penutup:** vendor Anda memakai yang mana? Cara mengetahuinya tanpa akses penuh: `ecs.launch_type` pada `/version`, kolom *Launch type* atau *Capacity provider* pada service, ada tidaknya instance `ecs-optimized` di EC2 console, dan tab *Infrastructure* pada cluster.

## Pertanyaan Operasi
1. Task gagal start berulang-ulang. Alarm mana yang berbunyi (jumlah task berjalan di bawah yang diinginkan, target tidak sehat, deployment event), dan apa langkah triase pertama Anda tanpa akses ke container?

2. Deployment baru dimulai pukul 14.00. Di mana Anda membuktikan versi mana yang melayani saat ini, dan siapa yang melakukannya? (Dibahas mendalam di Lab 8.)

3. Pada launch type EC2, task `PENDING` terus-menerus. Metrik apa yang membuktikan kapasitas habis, dan siapa yang harus bertindak?

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| Task berhenti dengan `CannotPullContainerError` | Tag/URI image salah, execution role tidak boleh menarik dari ECR, atau task tidak punya jalur internet (public IP tidak aktif tanpa NAT/VPC endpoint) |
| `ResourceInitializationError` atau gagal membuat log group | Execution role tidak punya `logs:CreateLogGroup` (atau `awslogs-create-group` tidak `true`); trainer memperbaiki role atau buat log group manual |
| `AccessDenied` saat **Create role** (Langkah 0) | Nama tidak berawalan `lab-ecs-`, atau mencentang kebijakan di luar daftar (`AmazonECSTaskExecutionRolePolicy`, `lab-ecs-create-log-group`, `AWSXRayDaemonWriteAccess`, `AmazonEC2ContainerServiceforEC2Role`); guardrail hanya mengizinkan itu |
| Kebijakan `lab-ecs-create-log-group` tidak ada di daftar | Trainer belum membuatnya; minta trainer |
| `AccessDeniedException ... iam:PassRole` saat memilih role di wizard | Role yang dipilih bukan buatan Anda (`lab-ecs-task-<nama>` / `lab-ecs-task-execution-<nama>`); guardrail hanya mengizinkan PassRole untuk role berawalan `lab-ecs-` |
| Target group tetap `unhealthy` | `task-sg` tidak mengizinkan 8080 dari `alb-sg`, health check path bukan `/health`, atau port target group bukan 8080 |
| `curl $ALB/` menghasilkan 503 setelah service dibuat | Belum ada target *healthy*; tunggu 1 sampai 2 menit atau cek *Events* |
| Service berulang kali memulai dan menghentikan task | Health check ALB gagal (periksa path/port/SG) atau container keluar; baca *Stopped reason* dan log di `/ecs/lab-app-<nama>` |
| Tidak ada container instance pada Bagian B | `lab-ecs-instance-<nama>` salah (atau kebijakan `AmazonEC2ContainerServiceforEC2Role` tidak terpasang), instance tidak punya jalur internet ke endpoint ECS, atau AMI bukan ECS-optimized; cek `/var/log/ecs/ecs-agent.log` lewat Instance Connect |
| Task EC2 `PENDING` | Kapasitas habis (CPU/memori/ENI); itu perilaku yang diharapkan pada langkah 13 |
| Circuit breaker tidak membatalkan deployment | Opsi *Rollback on failures* tidak dicentang; periksa pengaturan service |

## Cleanup
Pada akhir lab, **hapus Bagian B**: service `svc-app-ec2-<nama>` (desired 0 lalu delete), capacity provider dan ASG `asg-ecs-<nama>` (pastikan instance `t3.small` terminasi), target group `tg-ecs-ec2-<nama>`, dan kembalikan listener ALB ke satu target group `tg-ecs-<nama>` (bobot 100). **Biarkan** cluster, service `svc-app-<nama>`, ALB, dan log group tetap hidup untuk Lab 8 dan 9. Seluruhnya dihapus pada cleanup akhir hari: service (desired 0 lalu delete), cluster, ALB, target group, Security Group `task-sg-<nama>` lalu `alb-sg-<nama>`, task definition (deregister), log group, dan **tiga role** `lab-ecs-*-<nama>` (IAM, Roles, pilih, **Delete**; role instance terhapus bersama instance profile-nya setelah ASG hilang). **Pertahankan** role task `lab-ecs-task-<nama>` sampai Lab 9 selesai.
