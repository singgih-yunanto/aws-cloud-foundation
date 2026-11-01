# AWS Cloud Foundations: Materi Pelatihan 3 Hari

Materi pelatihan **AWS Cloud Foundations** untuk infra engineer (Linux, jaringan, dan virtualisasi) yang baru mengenal AWS. Mengacu pada AWS Academy Cloud Foundations (Modul 0 sampai 10). Bahasa pengantar adalah bahasa Indonesia; istilah teknis tetap dalam bahasa Inggris.

Seluruh lab dikerjakan pada akun AWS yang disediakan trainer, dengan satu IAM user untuk setiap peserta. Pengalaman dengan AWS tidak diperlukan; pemahaman dasar Linux dan jaringan (alamat IP, subnet, HTTP) sangat membantu.

> **Status:** repositori ini baru memuat materi **Hari 1**. Materi Hari 2 dan Hari 3 akan ditambahkan.

## Hari 1: Fondasi, Identitas, dan Server Pertama
Cloud basics, Global Infrastructure (Region dan AZ), Security dan IAM, EC2, serta EBS.

**Slide (`slides/`):** `Day1-Foundations-Identity-FirstServer.pptx` (35 slide). Versi PDF ada pada `slides/pdf/`.

**Lab (`labs/`):**
| Lab | Topik | Durasi |
|---|---|---|
| 1 | IAM dan Billing Budget | 45 menit |
| 2 | EC2 Web Server (SSH, IAM role, dan AMI) | 60 menit |
| 3 | EBS: volume, snapshot, restore, dan pindah AZ | 50 menit |

## Catatan
- Beri nama resource dengan akhiran nama Anda (misalnya `-budi`) agar tidak bentrok dengan peserta lain.
- **Hapus seluruh resource di akhir setiap lab atau akhir hari**, sesuai bagian Cleanup pada masing-masing lab, untuk menghindari biaya.
- Jangan menyimpan access key, kata sandi, atau file `.pem` pada repositori ini.
