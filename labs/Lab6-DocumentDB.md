# Lab 6: DocumentDB terhubung ke Aplikasi dan Agent pada ASG (50 menit, Hari 2)

**Tujuan:** peserta memasang CloudWatch Agent pada **ASG lewat Launch Template** (agent harus ada di template, bukan dipasang manual), lalu aplikasi pada ASG memakai Amazon DocumentDB (API MongoDB) tanpa kredensial di kode, dan peserta memahami perbedaan state di instance dengan state di database. Tracing (X-Ray) tidak lagi dikerjakan di sini; topik itu dibahas pada Hari 3 (Lab 9) dengan aplikasi yang berjalan di Fargate.

**Biaya:** satu cluster DocumentDB (satu instance db.t3.medium, sekitar $0,1 per jam) dibuat dan dihapus oleh trainer. Peserta tidak membuat DocumentDB.

**Status:** belum diuji pada akun AWS yang sebenarnya (User Data dengan paket tambahan, koneksi DocumentDB, agent lewat Launch Template). Trainer melakukan dry-run.

## Prasyarat
Lab 5 selesai: agent terpasang pada `mon-solo-<nama>`, parameter `AmazonCloudWatch-lab-app-<nama>` berisi konfigurasi versi 1, topik SNS dan dashboard `ops-<nama>` ada. Instance ASG dari Lab 4 **belum memiliki agent**; agent dipasang pada ASG di langkah 3.

## Endpoint `lab-app` yang Dipakai
Daftar lengkap ada di `Lab4-HA-WebApp.md` (Referensi Endpoint).

| Endpoint | Fungsi dalam lab ini |
|---|---|
| `/notes?u=<nama>` | GET membaca dan POST menyimpan catatan di DocumentDB; membuktikan data berada di database, bukan di memori instance |
| `/` | Memastikan instance baru sehat dan memakai konfigurasi baru |

## Persiapan Trainer (dilakukan sebelum kelas)
- Buat cluster DocumentDB `lab-docdb` di **default VPC** (satu instance, db.t3.medium, TLS aktif). Security Group `docdb-sg` mengizinkan port 27017 dari CIDR default VPC (`172.31.0.0/16`). Cluster tidak dapat diakses dari internet.
- Simpan kredensial di Secrets Manager dengan nama `lab/docdb`, berisi `{"username","password","host","port"}` (host berisi cluster endpoint). Jangan menulis nilai ini di materi atau repo.
- Role `lab-ec2-app` memiliki `secretsmanager:GetSecretValue` terbatas pada secret itu serta `CloudWatchAgentServerPolicy`.
- Pengisian koleksi `orders` (`06-app/seed-orders.py`) tidak diperlukan lagi: `/checkout` dianalisis pada Hari 3 dengan `DB_MODE=mock`.

## Bagian A: Agent pada ASG, DocumentDB, dan aplikasi (40 menit)
1. **Kenali cluster.** Trainer menunjukkan halaman cluster `lab-docdb`: cluster endpoint dan reader endpoint, replica set, Multi-AZ, backup, parameter TLS. Diskusikan: bagian mana yang dikelola AWS dan bagian mana yang tetap menjadi tanggung jawab Anda (data, akses, kueri, indeks).

2. **Cara aplikasi mendapat kredensial.** Buka IAM, Roles, `lab-ec2-app`, dan baca policy JSON-nya. Buka Secrets Manager dan lihat bahwa secret `lab/docdb` ada (peserta tidak membaca isinya). Aplikasi mengambil secret saat berjalan, sehingga tidak ada kata sandi di kode, User Data, atau Launch Template.

3. **Launch Template versi baru: aplikasi dan agent.** Agent harus ada di Launch Template, karena instance pengganti dan hasil scale-out lahir dari template; agent yang dipasang manual hilang bersama instance lamanya. **Instance ASG belum punya agent sama sekali**, dan parameter di Parameter Store hanya dibaca saat agent dijalankan (`fetch-config`) atau saat instance baru menyala.
   - **a.** EC2, Launch Templates, `lt-app-<nama>`, Actions, **Modify template (Create new version)**. *Template version description*: `agent-docdb`. **Source template version**: pilih versi yang sekarang dipakai ASG (jangan dikosongkan; bila kosong, role dan User data ikut kosong).
   - **b.** Pada **Advanced details**, periksa *IAM instance profile* = **`lab-ec2-app`** (tepat nama ini; tanpa role agent gagal dengan `NoCredentialProviders`, dan role yang salah menghasilkan `AccessDenied` pada log agent) dan *Detailed CloudWatch monitoring* = **Enable**.
   - **c.** Pada **User data**, ubah **hanya dua nilai** di bagian KONFIGURASI: `EXTRAS=yes` dan `DB_MODE=docdb`. Biarkan `TRACING=off`.
   - **d.** Klik di akhir teks User data, tekan Enter, lalu **tambahkan di akhir** (ganti `<nama>`):

      ```bash
      dnf install -y amazon-cloudwatch-agent
      /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c ssm:AmazonCloudWatch-lab-app-<nama> -s
      ```

      Ini perintah yang sama dengan yang Anda ketik manual di Lab 5, tanpa `sudo` karena User Data berjalan sebagai root.
   - **e.** **Create template version**, lalu Actions, **Set default version** ke versi baru. **Checkpoint:** tab *Versions* menampilkan versi baru berlabel *Default*; buka dan pastikan IAM instance profile, dua nilai KONFIGURASI, dan dua baris agent di akhir terlihat.
   - **f.** Pastikan ASG memakai versi itu: ASG `asg-app-<nama>`, tab *Details*, bagian *Launch template*. Bila *Version* tertulis **Default**, tidak perlu mengubah apa pun; bila nomor versi tetap, **Edit** dan pilih **Default (latest)**.
   - **g.** Pada armada besar, trainer menunjukkan cara lain secara teori untuk instance yang sudah berjalan: SSM Run Command atau State Manager (dokumen `AmazonCloudWatch-ManageAgent`).

4. **Instance refresh.** Pada ASG, tab *Instance refresh*, Start: minimum healthy percentage 50% dan instance warmup 120 detik. Instance diganti bergiliran sehingga situs tetap hidup (sekitar 8 sampai 10 menit). Instance baru memasang paket tambahan dan **agent**, membaca parameter saat agent mulai, sehingga langsung mengirim metrik dan log. Setelah dua instance baru *InService*, buka satu instance (EC2 Instance Connect) dan periksa `sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status` (`"status": "running"`), lalu di CloudWatch, Classic metrics, kartu **CWAgent**, grup dimensi **AutoScalingGroupName** kini ada. Bandingkan dengan `mon-solo-<nama>` yang hanya memiliki dimensi `InstanceId`. Sambil menunggu, jawab: apa bedanya refresh dengan menghentikan semua instance sekaligus, dan metrik apa yang akan Anda pantau selama deployment?

5. **Uji aplikasi.** Setelah dua instance baru sehat, di CloudShell: `curl -X POST "$ALB/notes?u=<nama>&text=halo-1"` beberapa kali dengan teks berbeda, kemudian `curl "$ALB/notes?u=<nama>"`. Perhatikan bahwa `served_by` berganti-ganti tetapi **semua catatan terlihat dari instance mana pun**, berbeda dengan penghitung `/session` di Lab 4 yang hilang saat berpindah instance. Inilah yang dimaksud dengan state di luar instance (stateless).

6. Terminate satu instance, tunggu pengganti sehat, dan baca kembali `/notes`: data tetap ada. Pengganti juga otomatis memasang agent dengan konfigurasi terbaru, karena semuanya ada di Launch Template dan Parameter Store. Ini yang tidak terjadi bila agent hanya dipasang manual.

7. **Diskusi Atlas** (5 menit; rincian pada sesi Database dan `05-learn/DocumentDB-Atlas`): jika data berada di MongoDB Atlas yang berjalan di atas AWS dan dibeli lewat AWS Marketplace, bagian mana dari aplikasi ini yang berubah? Hanya connection string dan jalur jaringan (IP access list, peering, atau PrivateLink), serta cara kredensial didapat (user database atau AWS IAM role). Marketplace hanya mengubah **penagihan** (biaya Atlas muncul di tagihan AWS), bukan identitas atau akses ke cluster. Tanyakan: siapa yang memegang langganan Marketplace dan siapa yang memegang organization Atlas di tim Anda, dan di mana Anda melihat rincian biayanya? Pertanyaan ini dilanjutkan pada Hari 3: dari task Fargate, jalur mana ke Atlas yang aman dan stabil?

## Bagian B: Demo trainer DynamoDB (5 menit, pada sesi Database)
Trainer membuat tabel `Students-demo` (partition key `StudentId`, On-demand), menambahkan beberapa item dengan atribut berbeda, menjalankan Query dan Scan, serta menunjukkan GSI. Bandingkan dengan DocumentDB: DynamoDB bersifat serverless dan memakai IAM (tanpa kata sandi), sedangkan DocumentDB kompatibel dengan driver MongoDB tetapi berjalan di cluster dalam VPC. Hapus tabel setelah demo.

## Validasi
`/notes` mengembalikan data yang sama dari kedua instance, instance ASG baru memiliki agent berstatus `running` dan metrik CWAgent berdimensi `AutoScalingGroupName`, dan instance pengganti hasil terminate juga memilikinya tanpa tindakan manual.

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| Instance refresh gagal atau target `unhealthy` | User Data gagal (cek `/var/log/lab-app-userdata.log`), paket tidak terpasang, atau role tidak dapat membaca secret; ASG akan menahan refresh |
| `/notes` mengembalikan 500 atau timeout | `docdb-sg` tidak mengizinkan 27017 dari VPC, secret salah, atau CA bundle tidak terunduh (`/opt/lab-app/global-bundle.pem`); lihat log aplikasi |
| `AccessDenied` pada Secrets Manager | `lab-ec2-app` belum memiliki `secretsmanager:GetSecretValue` untuk `lab/docdb` |
| Instance ASG tidak mengirim metrik padahal instance tunggal bisa | Instance belum diganti oleh refresh (masih tanpa agent), versi Launch Template tidak memuat dua perintah agent di akhir User Data, versi baru belum default, atau *IAM instance profile* kosong atau salah (cek `aws sts get-caller-identity` pada instance; harus `lab-ec2-app`) |
| Peserta saling menimpa data | Gunakan parameter `u=<nama>` yang berbeda untuk setiap peserta |

## Cleanup
Trainer menghapus cluster DocumentDB (tanpa final snapshot), secret `lab/docdb`, dan tabel DynamoDB demo. Peserta menghapus stack Lab 4 dan 5 sesuai urutan pada bagian Cleanup di `Lab4-HA-WebApp.md` dan `Lab5-Monitoring-Alerting.md` (termasuk instance `mon-solo-<nama>` dan parameter `AmazonCloudWatch-lab-app-<nama>`). Dashboard `ops-<nama>` boleh disimpan.
