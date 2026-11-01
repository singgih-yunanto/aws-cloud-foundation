# Lab 3: EBS Volume, Snapshot, Restore, dan Pindah AZ (50 menit, Hari 1)

**Tujuan:** Peserta membuat dan meng-attach volume EBS, memformat dan me-mount-nya seperti disk pada server Linux, memperbesar ukurannya tanpa menghentikan instance, membuat snapshot, memahami bahwa snapshot hanya menyimpan perubahan (delta), lalu memulihkan data ke **AZ yang berbeda** pada instance yang diluncurkan dari AMI.
**Prasyarat:** instance `web-<nama>` dan AMI `web-ami-<nama>` dari Lab 2. Instance harus **masih berjalan** dan AMI sebaiknya sudah berstatus *Available* (periksa pada menu AMIs).
**Biaya:** volume gp3 kecil, snapshot, dan satu instance t3.micro tambahan hanya menghabiskan beberapa sen apabila seluruh resource dihapus di akhir lab pada hari yang sama. **Seluruh resource Lab 2 dan Lab 3 (instance, volume, AMI, dan snapshot) wajib dihapus sebelum Hari 1 berakhir.**

> **Catatan padanan on-prem:** volume EBS setara dengan LUN SAN yang dipresentasikan ke server, snapshot setara dengan snapshot storage atau backup disk, dan AMI setara dengan template VM di vSphere.

## Persiapan
Pada console EC2, buka instance `web-<nama>` dan catat **Availability Zone**-nya (misalnya `ap-southeast-3a`), yang selanjutnya disebut **AZ-a**. Tentukan **AZ-b**, yaitu AZ lain pada Region yang sama (misalnya `ap-southeast-3b`). Volume hanya dapat di-attach ke instance pada AZ yang sama.

## Bagian A: Volume Baru
1. Buka EC2, Elastic Block Store, **Volumes**, lalu pilih Create volume. Gunakan tipe **gp3**, ukuran **2 GiB**, dan AZ-a. Beri tag Name `data-<nama>`.
2. Pilih volume tersebut, kemudian Actions, **Attach volume**. Pilih instance `web-<nama>` dan device name `/dev/sdf`.
3. Hubungkan ke instance melalui SSH, lalu jalankan `lsblk`. Volume baru muncul sebagai `nvme1n1` (instance generasi Nitro menampilkan `/dev/sdf` sebagai perangkat NVMe) dan belum memiliki filesystem. Perintah `sudo file -s /dev/nvme1n1` akan menampilkan `data`, yang berarti disk masih kosong.
4. Buat filesystem, mount, dan tulis sebuah file:
```bash
sudo mkfs -t xfs /dev/nvme1n1
sudo mkdir /data
sudo mount /dev/nvme1n1 /data
echo "versi 1" | sudo tee /data/catatan.txt
df -h /data
```
5. Agar mount bertahan setelah reboot, tambahkan entri `/etc/fstab` dengan UUID (nama device dapat berubah, sedangkan UUID tetap):
```bash
sudo blkid /dev/nvme1n1
echo "UUID=<uuid-dari-blkid>  /data  xfs  defaults,nofail  0  2" | sudo tee -a /etc/fstab
sudo umount /data && sudo mount -a && df -h /data
```
Opsi `nofail` mencegah boot gagal apabila volume tidak terpasang. Konsepnya sama dengan `/etc/fstab` pada server fisik.

## Bagian B: Elastic Volumes (Memperbesar Saat Online)
6. Pada console, pilih volume `data-<nama>`, Actions, **Modify volume**, lalu ubah ukuran menjadi **4 GiB** (opsional: ubah juga IOPS atau throughput gp3). Status volume akan menjadi *optimizing* dan volume tetap dapat dipakai. Setelah satu kali modifikasi, volume yang sama baru dapat dimodifikasi lagi setelah sekitar 6 jam.
7. Pada instance, jalankan `lsblk` (perangkat sudah 4 GiB) dan `df -h /data` (filesystem masih 2 GiB). Perbesar filesystem tanpa menghentikan instance:
```bash
sudo xfs_growfs -d /data
df -h /data
```
Untuk ext4, gunakan `resize2fs`. Untuk disk yang bertabel partisi (seperti root volume), jalankan `growpart` terlebih dahulu.

## Bagian C: Snapshot dan Restore
8. Jalankan `sudo sync` agar data yang masih berada di cache tertulis ke disk, lalu pilih volume `data-<nama>`, Actions, **Create snapshot** dengan deskripsi `snap1-<nama>`. Buka menu **Snapshots** dan tunggu status *completed*. Snapshot bersifat *crash-consistent*; untuk konsistensi aplikasi, hentikan penulisan atau unmount volume sebelum membuat snapshot.
9. Ubah data, lalu buat snapshot kedua:
```bash
echo "versi 2" | sudo tee /data/catatan.txt
sudo sync
```
Buat snapshot `snap2-<nama>`. Snapshot kedua bersifat **incremental**: hanya blok yang berubah sejak `snap1-<nama>` yang disimpan dan ditagih, sedangkan blok lainnya dirujuk ke snapshot pertama. Karena itu snapshot kedua selesai jauh lebih cepat.
10. Buka menu **Snapshots** dan pilih filter *Owned by me*. Daftar berisi **tiga snapshot**: `snap1-<nama>`, `snap2-<nama>`, dan satu snapshot milik AMI `web-ami-<nama>` dari Lab 2 (ukuran 8 GiB, deskripsi `Created by CreateImage(...) for ami-...`). AMI tidak menyimpan data sendiri: AMI adalah metadata yang menunjuk ke snapshot root volume. Coba hapus snapshot milik AMI; penghapusan ditolak karena snapshot masih dipakai AMI.
11. Pilih `snap1-<nama>`, Actions, **Create volume from snapshot**. Pilih **AZ-b** (bukan AZ-a) dan beri nama `restore-<nama>`. Coba Actions, Attach volume: daftar instance kosong karena belum ada instance pada AZ-b. Volume pada AZ-b tidak dapat dipasang ke instance `web-<nama>` yang berada pada AZ-a.

## Bagian D: Pindah AZ melalui Instance dari AMI
12. Buka **AMIs**, pilih `web-ami-<nama>`, lalu **Launch instance from AMI**. Gunakan nama `web-azb-<nama>`, t3.micro, dan key pair `key-<nama>`. Pada Network settings, pilih Edit, kemudian pilih default subnet pada **AZ-b**, aktifkan Auto-assign public IP, dan pilih Security Group yang sudah ada, yaitu `web-sg-<nama>`.
13. Setelah status instance *running*, kembali ke Volumes, pilih `restore-<nama>`, lalu Actions, Attach volume. Kini instance `web-azb-<nama>` muncul pada daftar. Pilih instance tersebut dengan device name `/dev/sdf`.
14. Hubungkan ke `web-azb-<nama>` melalui SSH (IP publik yang baru), lalu mount volume:
```bash
lsblk
sudo mkdir /restore
sudo mount /dev/nvme1n1 /restore
cat /restore/catatan.txt
```
Isi file adalah `versi 1`, yaitu kondisi pada saat snapshot pertama, yang kini berada pada AZ yang berbeda. Bandingkan dengan `cat /data/catatan.txt` pada instance `web-<nama>`, yang berisi `versi 2`. Buka juga `http://<ip-web-azb>`: web server dari AMI ikut berjalan dan masih menampilkan hostname instance asli karena file `index.html` ikut tersalin.
15. **(Opsional bila waktu mencukupi)** Buktikan konsep delta. Hapus `snap1-<nama>`, lalu buat volume baru dari `snap2-<nama>`. Pembuatan tetap berhasil dan datanya utuh, karena AWS mempertahankan blok milik `snap1` yang masih dirujuk oleh `snap2`. Hapus volume tersebut setelah selesai.

## Validasi
`/restore/catatan.txt` pada instance di AZ-b berisi `versi 1`, `/data` pada instance di AZ-a berisi `versi 2` dengan ukuran 4 GiB, dan peserta dapat menjelaskan mengapa snapshot AMI tampil pada daftar snapshot.

## Pertanyaan Diskusi
- Apa perbedaan snapshot dengan AMI? (AMI memuat snapshot beserta metadata untuk meluncurkan instance.)
- Mengapa snapshot kedua jauh lebih kecil dan cepat dibanding yang pertama, dan mengapa menghapus snapshot lama tidak merusak snapshot yang lebih baru?
- Bagaimana memindahkan data EBS antar AZ dan antar Region? (Snapshot, lalu Create volume atau Copy snapshot.)
- Bagaimana strategi backup rutin untuk volume EBS? (AWS Backup atau Data Lifecycle Manager.)

## Pemecahan Masalah
| Gejala | Penyebab | Solusi |
|---|---|---|
| Volume baru tidak muncul pada `lsblk` | Attach gagal, atau volume berada pada AZ yang berbeda | Pastikan status volume `in-use` dan AZ volume sama dengan instance |
| Instance tujuan tidak muncul saat Attach volume | Volume dan instance berada pada AZ yang berbeda | Buat volume pada AZ yang sama dengan instance tujuan |
| `mount` gagal dengan pesan `wrong fs type` atau duplicate UUID | Volume hasil restore di-mount pada instance yang masih memiliki volume asal (UUID XFS sama) | Gunakan `mount -o nouuid`, atau mount pada instance lain seperti pada langkah 14 |
| `xfs_growfs: ... is not a mount point` atau `not an XFS filesystem` | Volume belum di-mount, atau filesystem adalah ext4 | Mount terlebih dahulu, atau gunakan `resize2fs` untuk ext4 |
| Modify volume ditolak | Volume baru saja dimodifikasi (batas sekitar 6 jam) | Tunggu, atau buat volume baru dari snapshot |
| Instance gagal boot setelah mengedit `fstab` | Entri salah dan tidak memakai `nofail` | Selalu uji dengan `mount -a`, dan gunakan `nofail` |
| AMI tidak muncul atau belum dapat dipakai | Status AMI masih *pending* | Tunggu hingga *Available* (beberapa menit) |
| SSH ke `web-azb-<nama>` timeout | Public IP tidak aktif pada subnet, atau Security Group berbeda | Pastikan Auto-assign public IP aktif dan Security Group adalah `web-sg-<nama>` |
| Volume tidak dapat dihapus | Volume masih ter-attach atau dipakai | Unmount, kemudian detach terlebih dahulu |
| Snapshot tidak dapat dihapus | Snapshot masih dipakai oleh AMI | Deregister AMI terlebih dahulu |

## Cleanup (wajib, lakukan sebelum meninggalkan ruangan pada Hari 1)
1. Terminate instance `web-azb-<nama>` dan `web-<nama>`.
2. Buka **Volumes** dan hapus seluruh volume yang tersisa dengan status *available*. Volume tambahan (seperti `data-<nama>` dan `restore-<nama>`) tidak otomatis terhapus saat instance di-terminate karena *Delete on termination* tidak aktif, dan volume yang tertinggal tetap ditagih.
3. Deregister AMI `web-ami-<nama>`.
4. Hapus seluruh snapshot milik Anda (`snap1`, `snap2`, dan snapshot milik AMI, yang baru dapat dihapus setelah AMI di-deregister). Pastikan filter Snapshots berisi *Owned by me*.
5. Hapus key pair `key-<nama>` pada EC2, Key pairs, serta file `.pem` di laptop. Security Group `web-sg-<nama>` boleh dihapus.
6. Pastikan tidak ada instance, volume, AMI, maupun snapshot yang tersisa.
