# Lab 1: IAM dan Billing Budget (45 menit, Hari 1)

**Tujuan:** Peserta masuk sebagai IAM user, mengaktifkan MFA, memahami policy, dan mengetahui cara kerja Budget.
**Biaya:** $0

## Langkah
1. Buka URL sign-in akun lab: `https://aws24training.signin.aws.amazon.com/console` (account alias `aws24training`). Nama user dan kata sandi sementara diberikan trainer secara langsung. Masuk dengan IAM user dan kata sandi sementara, kemudian ganti kata sandi tersebut.
2. Pilih Region **Asia Pacific (Jakarta) ap-southeast-3** di pojok kanan atas. Bila suatu layanan tidak tersedia, gunakan Singapore.
3. **Aktifkan MFA.** Buka IAM, pilih Users, pilih user Anda, lalu Security credentials dan Assign MFA device. Pilih Authenticator app, pindai kode QR, dan masukkan dua kode yang berurutan.
4. **Pelajari policy.** Buka tab Permissions pada user Anda, pilih salah satu policy, dan lihat tab JSON. Catat arti dari `Effect`, `Action`, dan `Resource`.
5. **Uji batas akses.** Coba membuat user baru (IAM, Users, Create user). Hasil yang diharapkan adalah *Access Denied*, yang menunjukkan penerapan prinsip least privilege.
6. **Budget.** Trainer membuat Budget di akun (Billing, Budgets, Create budget, jenis Cost budget, $10, peringatan pada 80% ke email), sedangkan peserta mengamati konfigurasinya.
7. Buka **Pricing Calculator** (calculator.aws) dan buat estimasi untuk satu instance t3.micro selama 730 jam per bulan.

## Validasi
- MFA aktif, dan peserta dapat login ulang menggunakan kode MFA.
- Peserta dapat menjelaskan alasan penolakan pada langkah Create user.

## Pertanyaan Diskusi
- Apa perbedaan antara IAM user, group, dan role? Mengapa root account tidak dipakai untuk pekerjaan sehari-hari?
- Apa perbedaan antara implicit deny dan explicit deny?

## Pemecahan Masalah
| Gejala | Penyebab | Solusi |
|---|---|---|
| Kode MFA ditolak | Jam pada ponsel tidak sinkron | Aktifkan pengaturan waktu otomatis pada ponsel |
| Layanan tidak muncul | Region yang dipilih salah | Ganti Region |
| Tidak dapat mengganti kata sandi | Policy IAMUserChangePassword belum terpasang | Hubungi trainer |
