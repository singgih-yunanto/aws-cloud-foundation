# AWS Cloud Foundations: Materi Pelatihan 3 Hari

Materi pelatihan **AWS Cloud Foundations** untuk infra engineer (Linux, jaringan, dan virtualisasi) yang baru mengenal AWS. Mengacu pada AWS Academy Cloud Foundations (Modul 0 sampai 10). Bahasa pengantar adalah bahasa Indonesia; istilah teknis tetap dalam bahasa Inggris.

Seluruh lab dikerjakan pada akun AWS yang disediakan trainer, dengan satu IAM user untuk setiap peserta. Pengalaman dengan AWS tidak diperlukan; pemahaman dasar Linux dan jaringan (alamat IP, subnet, HTTP) sangat membantu.

> **Status:** repositori memuat materi **Hari 1, Hari 2, dan Hari 3**. Lab Hari 2 dan Hari 3 serta aplikasi `06-app` **belum diuji pada akun AWS yang sebenarnya**; ikuti arahan trainer bila tampilan konsol berbeda dari panduan.

## Hari 1: Fondasi, Identitas, dan Server Pertama
Cloud basics, Global Infrastructure (Region dan AZ), Security dan IAM, EC2, serta EBS.

**Slide (`slides/`):** `Day1-Foundations-Identity-FirstServer.pptx` (35 slide). Versi PDF ada pada `slides/pdf/`.

**Lab (`labs/`):**
| Lab | Topik | Durasi |
|---|---|---|
| 1 | IAM dan Billing Budget | 45 menit |
| 2 | EC2 Web Server (SSH, IAM role, dan AMI) | 60 menit |
| 3 | EBS: volume, snapshot, restore, dan pindah AZ | 50 menit |

## Hari 2: Load Balancing, Auto Scaling, Monitoring, dan Database
ELB dan Auto Scaling, monitoring dan alert (CloudWatch Agent, alarm, dashboard), serta database (DocumentDB dan diskusi MongoDB Atlas).

**Slide (`slides/`):** `Day2-ALB-Monitoring-Database.pptx` (26 slide). Versi PDF ada pada `slides/pdf/`.

**Lab (`labs/`):**
| Lab | Topik | Durasi |
|---|---|---|
| 4 | HA Web App: ALB, Auto Scaling, dan aplikasi `lab-app` | 80 menit |
| 5 | Metrik, alarm, dan dashboard dengan CloudWatch Agent | 65 menit (isi 45) |
| 6 | DocumentDB terhubung ke aplikasi dan agent pada ASG | 50 menit |

## Hari 3: Container di ECS, Pemantauan, Tracing, dan Konektivitas Jaringan
ECS dan Fargate (deploy, pemantauan, pelacakan perubahan, triase), X-Ray pada container, serta VPC peering dan Site-to-Site VPN. Konteksnya tim operasi yang mengelola lingkungan yang dikelola vendor dengan akses terbatas. S3, Lambda, dan biaya tidak dibahas di kelas.

**Slide (`slides/`):** `Day3-ECS-Fargate-Network.pptx` (36 slide). Versi PDF ada pada `slides/pdf/`.

**Lab (`labs/`):**
| Lab | Topik | Durasi |
|---|---|---|
| 7 | Menjalankan aplikasi di ECS: Fargate, lalu launch type EC2 sebagai pembanding | 90 menit |
| 8 | Memantau, melacak perubahan, dan mentriase layanan ECS | 70 menit |
| 9 | Menelusuri request lambat dengan X-Ray pada task Fargate | 40 menit |
| 10 | VPC peering dan Site-to-Site VPN ke jaringan "on-prem" | 45 menit |

## Aplikasi Lab (`06-app/`)
Aplikasi web kecil `lab-app` yang dipakai pada Lab 4 sampai 9 (di EC2 sebagai User Data, di ECS sebagai container). Lihat `06-app/README.md`.

## Catatan
- Beri nama resource dengan akhiran nama Anda (misalnya `-budi`) agar tidak bentrok dengan peserta lain.
- **Hapus seluruh resource di akhir setiap lab atau akhir hari**, sesuai bagian Cleanup pada masing-masing lab, untuk menghindari biaya.
- Jangan menyimpan access key, kata sandi, atau file `.pem` pada repositori ini.
