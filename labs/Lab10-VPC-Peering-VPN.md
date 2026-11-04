# Lab 10: VPC Peering dan Site-to-Site VPN ke Jaringan "On-Prem" (45 menit, Hari 3)

**Tujuan:** peserta membangun dua VPC sendiri (A dan B), menghubungkannya dengan **VPC peering**, lalu menghubungkan VPC A ke jaringan "on-prem" (VPC C milik trainer, disimulasikan dengan gateway strongSwan dan PostgreSQL) lewat **Site-to-Site VPN**. Peserta membuktikan konektivitas (ping, TCP, `psql` dengan TLS), membuktikan bahwa peering **tidak transitif**, membuat alarm status tunnel, dan mentriase tunnel yang dimatikan trainer. Lab ini sengaja terpisah dari aplikasi Fargate agar fokus pada jaringan.

**Biaya:** satu VPN connection sekitar $0,05 per jam per peserta (berjalan sampai dihapus), dua instance `t3.micro` selama lab, alamat IPv4 publik. **Hapus VPN connection segera setelah lab** (lihat Cleanup).

**Status:** belum diuji pada akun AWS yang sebenarnya (VPN statis dengan PSK kustom ke strongSwan di EC2 ber-EIP, propagasi rute, `add-tunnel.sh`). Bagian B bergantung pada trainer yang mendaftarkan tunnel tiap peserta; bila waktu habis, Bagian A dijadikan demo trainer agar Bagian B cukup waktu.

## Prasyarat
- Trainer sudah menyiapkan VPC C dan host gateway (`06-app/network/onprem-setup.sh`) dan membagikan: **alamat IP Customer Gateway** (Elastic IP), **PSK** Anda, **kata sandi** role database `app_ro`, serta nomor urut Anda (`n` = 1 sampai 4).
- Guardrail menolak pembuatan Transit Gateway; VGW, Customer Gateway, dan VPN connection diizinkan untuk Anda selama Hari 3.
- Key pair `key-<nama>` dari Lab 2 atau EC2 Instance Connect.

## Rencana Alamat (CIDR harus unik dan tidak tumpang tindih)

| Jaringan | CIDR | Pemilik |
|---|---|---|
| VPC A `a-<nama>-vpc` | `10.<n>.0.0/16` | Anda (n = nomor urut) |
| VPC B `b-<nama>-vpc` | `10.<n+10>.0.0/16` | Anda |
| VPC C "on-prem" | `192.168.100.0/24` (database di `192.168.100.10`) | Trainer |
| Default VPC | `172.31.0.0/16` | Tidak dipakai lab ini |

Peering dan VPN **tidak dapat** menghubungkan jaringan dengan CIDR yang tumpang tindih. Itu sebabnya satu rencana alamat dipegang bersama; di dunia nyata ini sering menjadi hambatan utama saat menyambung on-prem atau jaringan vendor.

## Bagian A: VPC A, VPC B, dan peering (15 menit)
1. **Buat dua VPC.** VPC console, **Create VPC**, pilih **VPC and more**.
   - **a.** VPC A: *Name tag auto-generation* `a-<nama>`, *IPv4 CIDR* `10.<n>.0.0/16`, *Number of AZs* **1**, *Public subnets* **1**, *Private subnets* **0**, *NAT gateways* **None**, *VPC endpoints* **None**. Create. Hasilnya VPC `a-<nama>-vpc`, satu subnet publik, Internet Gateway, dan route table publik. (Catatan: nama otomatis boleh dipakai; di bawah disebut "VPC A".)
   - **b.** Ulangi untuk VPC B: prefix `b-<nama>`, CIDR `10.<n+10>.0.0/16`.

   **Checkpoint:** dua VPC dengan CIDR berbeda, masing-masing memiliki satu subnet publik dan route table dengan rute `0.0.0.0/0` ke Internet Gateway.

2. **Instance uji.** Luncurkan dua instance Amazon Linux 2023 `t3.micro`.
   - **a.** `a-test-<nama>` di subnet VPC A, *Auto-assign public IP* **Enable**. Security Group baru `a-sg-<nama>`: inbound **SSH 22** dari My IP, serta **All ICMP-IPv4** dan **All TCP** dari `10.0.0.0/8`.
   - **b.** `b-test-<nama>` di subnet VPC B, Security Group `b-sg-<nama>` dengan aturan yang sama. Pada *Advanced details*, *User data*:

      ```bash
      #!/bin/bash
      echo "halo dari B <nama>" > /tmp/index.html
      nohup python3 -m http.server 8080 --directory /tmp >/dev/null 2>&1 &
      ```

   **Checkpoint:** kedua instance *running*; catat **IP privat** keduanya (`10.<n>.x.x` dan `10.<n+10>.x.x`). Sambungkan ke `a-test-<nama>` lewat EC2 Instance Connect dan coba `ping -c 2 <IP privat B>`: **gagal** (belum ada jalur).

3. **VPC peering.** VPC console, Peering connections, **Create peering connection**: nama `pcx-a-b-<nama>`, *Requester* VPC A, *Accepter* **My account**, **This Region**, VPC B. Create, lalu pilih peering itu dan **Actions, Accept request**.
   - **a.** **Rute di kedua sisi** (peering tidak menambah rute otomatis): Route tables, route table VPC A, **Edit routes**, tambah destination `10.<n+10>.0.0/16` target **Peering Connection** `pcx-a-b-<nama>`. Lalu route table VPC B: destination `10.<n>.0.0/16` ke peering yang sama.
   - **b.** Uji dari `a-test-<nama>`: `ping -c 3 <IP privat B>` dan `curl -s http://<IP privat B>:8080/index.html`.

   **Checkpoint:** ping berhasil dan curl menampilkan "halo dari B". Diskusi (2 menit): mengapa kedua sisi butuh rute dan Security Group yang mengizinkan, dan apa yang terjadi bila CIDR A dan B sama? Peering Atlas bekerja dengan cara ini: VPC Anda dipeering dengan VPC milik Atlas; CIDR tidak boleh bentrok dan IP access list Atlas diatur terpisah.

## Bagian B: Site-to-Site VPN dari VPC A ke "on-prem" (30 menit)
4. **Virtual private gateway.** VPC console, Virtual private gateways, **Create**: nama `vgw-<nama>`, ASN **Amazon default**. Pilih, **Actions, Attach to VPC**, VPC A. **Checkpoint:** status *attached*.

5. **Customer gateway.** Customer gateways, **Create**: nama `cgw-onprem-<nama>`, *BGP ASN* `65000` (wajib diisi walau routing statis), *IP address* = alamat yang trainer berikan. **Checkpoint:** status *available*.

6. **VPN connection.** Site-to-Site VPN connections, **Create**: nama `vpn-<nama>`, *Target gateway type* **Virtual private gateway** `vgw-<nama>`, *Customer gateway* **Existing** `cgw-onprem-<nama>`, *Routing options* **Static**, *Static IP prefixes* `192.168.100.0/24`.
   - **a.** Buka *Tunnel 1 options* dan *Tunnel 2 options*: isi **Pre-shared key** dengan PSK dari trainer (sama untuk kedua tunnel). Jangan menulis PSK di tempat lain.
   - **b.** **Create**. Buka tab *Tunnel details*: kedua tunnel berstatus **Down** dan masing-masing menampilkan *Outside IP address*.
   - **c.** **Kirim kedua Outside IP address** (tunnel 1 dan 2) kepada trainer.

   *Mengapa dua tunnel:* AWS menyediakan dua endpoint pada AZ berbeda; satu dapat diperbarui AWS tanpa memutus konektivitas.

7. **Propagasi rute.** Route tables, route table VPC A, tab *Route propagation*, **Edit route propagation**, centang `vgw-<nama>`. Rute `192.168.100.0/24` akan muncul sendiri begitu tunnel Up (*Propagated: Yes*).

8. **Tunggu tunnel, buat alarm (sambil menunggu 2 sampai 5 menit).** Trainer mendaftarkan tunnel Anda pada gateway.
   - **a.** CloudWatch, Alarms, Create alarm: metrik **VPN**, **TunnelState** (dimensi `VpnId`), pilih `vpn-<nama>`. *Statistic* **Minimum**, *Period* 1 minute, *Threshold* **Lower than 1**, *Datapoints* **3 out of 3**, *Missing data* **Treat missing data as breaching**. Notifikasi ke `ops-alerts-<nama>`. Nama `tunnel-state-<nama>`.

      *Mengapa Minimum dan breaching:* 1 berarti Up dan 0 berarti Down; bila datanya hilang, anggap masalah.
   - **b.** Unduh konfigurasi contoh (**Download configuration**, vendor *Generic* atau *Strongswan*) dan baca bagian IKE, ESP, dan *Inside IP*. Bandingkan dengan yang dipakai gateway trainer.

   **Checkpoint:** tunnel 1 (dan 2 bila didaftarkan) berstatus **Up** pada *Tunnel details*; route table VPC A memuat `192.168.100.0/24` via `vgw-<nama>`.

9. **Uji konektivitas dan enkripsi.** Dari `a-test-<nama>`:

   ```bash
   ping -c 3 192.168.100.10
   timeout 3 bash -c '</dev/tcp/192.168.100.10/5432' && echo "port 5432 terbuka"
   sudo dnf install -y postgresql15
   PGPASSWORD='<kata sandi dari trainer>' psql "host=192.168.100.10 dbname=pdp_demo user=app_ro sslmode=require" \
     -c "SELECT * FROM customers_masked LIMIT 5" \
     -c "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()" \
     -c "SELECT * FROM customers LIMIT 1"
   ```

   **Checkpoint:** ping dan port terbuka; kueri pertama menampilkan NIK yang sudah disamarkan; kueri kedua menunjukkan `ssl = t`; kueri ketiga **ditolak** (`permission denied for table customers`). Jawab: ada dua lapis enkripsi (IPsec pada VPN dan TLS pada PostgreSQL); mengapa keduanya? Bagaimana role `app_ro` yang hanya boleh `SELECT` pada view menjalankan prinsip *least privilege* sesuai kebutuhan UU PDP?

10. **Peering tidak transitif.** Dari `b-test-<nama>` coba mencapai database: `timeout 3 bash -c '</dev/tcp/192.168.100.10/5432' && echo terbuka || echo gagal`. Hasilnya **gagal**, meski A terhubung ke C dan A terhubung ke B. Peering tidak meneruskan lalu lintas melalui A, dan VPN yang melekat pada VGW A tidak dapat dipakai VPC B. Jalan keluar: Transit Gateway (pada kelas hanya didiskusikan; guardrail menolak pembuatannya) atau VGW/VPN terpisah untuk B.

11. **Insiden (trainer mematikan tunnel, 5 menit).** Trainer menghentikan tunnel Anda pada gateway on-prem (menghentikan layanan VPN di sana). Tanpa diberi tahu penyebabnya, bekerja sebagai tim operasi:
    - **a.** Amati alarm `tunnel-state-<nama>` (setelah 3 menit data Down) dan email.
    - **b.** Triase berurutan: (1) status tunnel di console, (2) apakah rute masih tersebar (*Propagated*), (3) apakah masalah ada di sisi AWS (Security Group, NACL, route) atau di sisi on-prem (tunnel Down walau konfigurasi AWS tidak berubah), (4) CIDR tumpang tindih, PSK, atau parameter IKE tidak cocok, (5) siapa yang harus dihubungi dan membawa bukti apa.
    - **c.** Trainer memulihkan tunnel; alarm kembali OK. Catat berapa lama pemulihan, dan alarm mana yang paling cepat memberi tahu.

12. **Diskusi (3 menit).** Daftar periksa rancangan teknis UU PDP untuk pola "database di lokal, aplikasi di cloud": lokasi data, enkripsi saat transit, penyamaran data, hak akses minimum, jejak audit. Banding VPN dengan Direct Connect (biaya, latensi, SLA, waktu pengadaan) dan dengan VPN buatan sendiri. Dan pada lingkungan vendor-managed: konektivitas hybrid biasanya milik vendor; apa yang Anda minta agar tetap bisa memantaunya (metrik `TunnelState`, notifikasi perubahan, kontak darurat)?

## Pertanyaan Operasi
1. Aplikasi tiba-tiba tidak dapat membaca database on-prem. Dari mana Anda tahu apakah masalahnya VPN, rute, Security Group, atau database, tanpa akses ke server on-prem?

2. Alarm apa yang Anda pasang untuk VPN, dan mengapa `TunnelState` saja belum cukup (dua tunnel, satu bisa Down tanpa terasa)?

3. Siapa yang bertanggung jawab atas tiap bagian jalur (VPC, VGW, internet, router on-prem, database)?

## Pemecahan Masalah

| Gejala | Penyebab dan solusi |
|---|---|
| Tunnel tetap Down | Trainer belum mendaftarkan tunnel Anda, Outside IP salah dikirim, PSK berbeda, UDP 500/4500 diblokir di Security Group gateway, atau parameter IKE/ESP tidak cocok; minta trainer memeriksa `ipsec statusall` |
| Tunnel Up tetapi tidak ada ping | Route propagation belum diaktifkan, `a-sg-<nama>` tidak mengizinkan ICMP/TCP keluar atau masuk, atau rute `192.168.100.0/24` kembali tidak ada di gateway (trainer) |
| Ping jalan, port 5432 tertutup | PostgreSQL tidak mendengarkan di `192.168.100.10`, atau `pg_hba` tidak mengizinkan CIDR Anda; kabari trainer |
| `psql`: `FATAL: no pg_hba.conf entry` | Sumber `10.<n>.x.x` tidak diizinkan, atau `sslmode=require` tidak dipakai |
| Peering aktif tetapi ping A ke B gagal | Salah satu rute belum ditambahkan, Security Group tidak mengizinkan CIDR lawan, atau CIDR A dan B tumpang tindih |
| `CreateVpnConnection` ditolak | Guardrail belum dilonggarkan untuk Hari 3; kabari trainer |
| Alarm `INSUFFICIENT_DATA` | Dimensi `VpnId` salah atau VPN baru dibuat (tunggu beberapa menit) |

## Cleanup

**Hapus VPN secepatnya, karena ditagih per jam.** Urutan: (1) VPN connection `vpn-<nama>` (tunggu *deleted*), (2) Customer gateway `cgw-onprem-<nama>`, (3) Detach lalu hapus `vgw-<nama>`, (4) hapus peering `pcx-a-b-<nama>`, (5) terminate `a-test-<nama>` dan `b-test-<nama>`, (6) hapus Security Group `a-sg-<nama>` dan `b-sg-<nama>`, (7) hapus VPC A dan B (console menghapus subnet, route table, dan Internet Gateway terkait), (8) hapus alarm `tunnel-state-<nama>`. Trainer menghapus pendaftaran tunnel (`add-tunnel.sh --remove`) dan VPC C pada akhir hari.
