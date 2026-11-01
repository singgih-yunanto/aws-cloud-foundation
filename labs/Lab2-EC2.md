# Lab 2: Meluncurkan EC2 Web Server (60 menit, Hari 1, default VPC)

**Tujuan:** Peserta meluncurkan EC2, menyiapkan web server melalui User Data, mengakses server melalui SSH dari laptop, membuat AMI, serta memahami Security Group dan IAM role.
**Biaya:** t3.micro sekitar $0,01 per jam (Free Tier atau kredit). Instance dan AMI (beserta snapshot-nya) dipakai kembali pada Lab 3 dan **wajib dihapus di akhir Lab 3** (hari yang sama), sehingga tidak ada resource yang menginap. Snapshot AMI berukuran 8 GiB hanya menghabiskan beberapa sen selama beberapa jam.

## Langkah
1. Buka EC2, pilih Launch instance, dan beri nama `web-<nama>`.
2. Pilih AMI **Amazon Linux 2023** dan instance type **t3.micro** (atau t2.micro bila itu yang masuk Free Tier di Region Anda).
3. Key pair: pilih **Create new key pair** dengan nama `key-<nama>`, tipe RSA, dan format **.pem** (untuk OpenSSH, baik di Linux, macOS, maupun Windows 10/11). File `.pem` terunduh satu kali saja dan tidak dapat diunduh ulang, sehingga simpan pada folder yang mudah ditemukan.
4. Jaringan (pada Hari 1 memakai **default VPC**): pilih default VPC dan salah satu default subnet, lalu aktifkan Auto-assign public IP. Buat Security Group baru bernama `web-sg-<nama>` dengan dua inbound rule: **HTTP 80** dari `0.0.0.0/0` dan **SSH 22** dari **My IP** (jangan `0.0.0.0/0`). VPC buatan sendiri baru dibuat pada Lab 7 (Hari 3).
5. Storage: gunakan 8 GiB gp3 (nilai default).
6. Pada Advanced details, isi **User data** dengan script berikut:
```bash
#!/bin/bash
dnf install -y httpd
systemctl enable --now httpd
echo "<h1>Halo dari $(hostname -f)</h1>" > /var/www/html/index.html
```
7. Luncurkan instance dan tunggu hingga status menunjukkan *2/2 checks passed*.
8. Salin **Public IPv4 address**, lalu buka `http://<ip>` di browser (gunakan HTTP, bukan HTTPS).
9. **SSH dari komputer lokal.** Buka terminal pada laptop Anda (Terminal di Linux atau macOS, PowerShell di Windows 10/11), lalu pindah ke folder tempat `key-<nama>.pem` tersimpan.
   - Linux atau macOS: batasi izin file kunci, kemudian sambungkan.
   ```bash
   chmod 400 key-<nama>.pem
   ssh -i key-<nama>.pem ec2-user@<public-ip>
   ```
   - Windows (PowerShell): hanya pengguna Anda yang boleh membaca file kunci, kemudian sambungkan.
   ```powershell
   icacls .\key-<nama>.pem /inheritance:r /grant:r "$($env:USERNAME):(R)"
   ssh -i .\key-<nama>.pem ec2-user@<public-ip>
   ```
   Jawab `yes` pada pertanyaan host fingerprint pada koneksi pertama. Setelah masuk, jalankan `whoami`, `curl localhost`, `df -h`, dan `lsblk`. Bandingkan dengan akses SSH ke server on-prem: sama-sama berbasis key, tetapi tanpa password dan tanpa VPN. Bila port 22 diblokir oleh jaringan lokasi pelatihan, gunakan **EC2 Instance Connect** (tombol Connect pada console) sebagai alternatif.
10. **Eksperimen.** Stop lalu Start instance, kemudian periksa apakah public IP berubah (berubah, kecuali memakai Elastic IP), dan sambungkan kembali dengan SSH menggunakan IP yang baru. Hapus rule port 80 pada Security Group sehingga situs tidak dapat diakses, lalu tambahkan kembali dan amati bahwa efeknya langsung terjadi (stateful).
11. **IAM role untuk EC2.** Pasang role `lab-ec2-s3-readonly` (akses S3 read-only; disiapkan oleh trainer) pada instance melalui Actions, Security, Modify IAM role. Dari instance, jalankan `aws s3 ls` tanpa memakai access key. Kredensial sementara diberikan otomatis melalui instance profile, sehingga tidak ada access key yang disimpan di server.
12. **AMI sebagai template VM.** Pilih instance, lalu Actions, Image and templates, **Create image** dengan nama `web-ami-<nama>`. Biarkan opsi default: instance di-reboot sebentar agar filesystem konsisten, sehingga koneksi SSH terputus dan dapat dilakukan ulang setelah satu menit. Proses pembuatan AMI berjalan di latar belakang (sekitar 3 sampai 5 menit); pantau pada menu AMIs hingga status *Available*. Bandingkan dengan template VM di vSphere. AMI ini dipakai pada Lab 3.
13. **Pada akhir lab, jangan terminate instance dan jangan hapus AMI.** Keduanya dipakai kembali pada Lab 3 (EBS, snapshot, dan pindah AZ) dan dihapus di akhir Lab 3.

## Validasi
Halaman web tampil dengan hostname instance, koneksi SSH dari laptop berhasil, `aws s3 ls` berjalan tanpa access key, dan AMI `web-ami-<nama>` berstatus *Available* (atau sedang diproses).

## Pemecahan Masalah
| Gejala | Penyebab | Solusi |
|---|---|---|
| Browser timeout | Security Group tanpa port 80, tidak ada public IP, tidak ada route ke IGW, atau memakai https | Periksa keempat hal tersebut secara berurutan |
| Muncul halaman default Apache atau 403 | User Data gagal dijalankan | Periksa `sudo cat /var/log/cloud-init-output.log` |
| Instance type tidak tersedia | Kapasitas pada AZ atau Region | Ganti instance type atau AZ |
| SSH timeout | Rule port 22 tidak ada, rule My IP sudah tidak sesuai karena IP laptop berubah (misalnya berpindah jaringan), tidak ada public IP, atau port 22 diblokir oleh jaringan lokal | Periksa rule SSH dan perbarui My IP; bila diblokir, gunakan Instance Connect |
| `Permissions 0644 for 'key.pem' are too open` atau `UNPROTECTED PRIVATE KEY FILE` | File kunci dapat dibaca pengguna lain | Jalankan `chmod 400` (Linux atau macOS) atau `icacls` (Windows) seperti pada langkah 9 |
| `Permission denied (publickey)` | Nama user salah, atau file kunci bukan pasangan key pair instance | Gunakan `ec2-user` pada Amazon Linux 2023 dan pastikan nama key pair sesuai |
| Instance Connect gagal | Security Group tidak mengizinkan SSH dari rentang IP EC2 Instance Connect (rule hanya untuk My IP), atau tidak ada public IP | Tambahkan sementara rule port 22 untuk rentang IP EC2 Instance Connect Region Anda, atau gunakan SSH dari laptop |
| Muncul `UnauthorizedOperation` | Policy IAM belum mengizinkan aksi | Hubungi trainer |
| `aws s3 ls` menampilkan `Unable to locate credentials` atau `AccessDenied` | Role belum terpasang pada instance, atau role tidak memiliki akses S3 | Periksa Modify IAM role, lalu tunggu sekitar satu menit |
| SSH terputus setelah Create image | Instance di-reboot oleh proses pembuatan AMI | Tunggu sekitar satu menit, lalu SSH ulang (public IP tetap sama karena reboot bukan stop) |
| Status AMI lama *pending* | Snapshot root volume sedang dibuat | Tunggu beberapa menit; lanjutkan ke Lab 3 dan periksa kembali |

## Cleanup
Instance, AMI, snapshot, key pair, dan resource Lab 2 lainnya dihapus pada **akhir Lab 3** (lihat bagian Cleanup di `Lab3-EBS.md`), karena instance ini masih diperlukan di sana.
