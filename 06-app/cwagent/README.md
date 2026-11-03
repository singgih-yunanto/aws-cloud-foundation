# CloudWatch Agent untuk lab-app (Lab 5 dan 6)

Agent **tidak** dipasang oleh `user-data.lab4.sh` atau `user-data.lab6.sh`. Peserta memasangnya sendiri pada Lab 5; isi berkas ini sama dengan yang tertulis di lab dan berfungsi sebagai rujukan serta cadangan salin-tempel untuk trainer.

| Berkas | Dipakai di | Isi |
|---|---|---|
| `agent-config.v1.json` | Lab 5 | Disimpan di SSM Parameter Store `AmazonCloudWatch-lab-app-<nama>` (versi 1). Metrik `mem_used_percent`, `disk_used_percent` (namespace `CWAgent`) dan log `/var/log/lab-app.log` ke log group `/lab/lab-app`. |
| `agent-config.v2-traces.json` | Lab 6 | Versi 2 parameter yang sama: versi 1 ditambah penerima OTLP `127.0.0.1:4318` untuk trace X-Ray. |
| `userdata-agent-snippet.sh` | Lab 5 (ASG) | Dua perintah yang ditambahkan ke akhir User Data Launch Template. |

Nama parameter berawalan `AmazonCloudWatch-` agar `CloudWatchAgentServerPolicy` pada role `lab-ec2-app` boleh membacanya. Kasus instance tunggal memakai perintah yang sama secara manual (`dnf install`, lalu `amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c ssm:<nama parameter> -s`).

**Status:** belum diuji di AWS (Amazon Linux 2023, pembacaan konfigurasi dari SSM, dimensi metrik instance tunggal dibanding ASG, penerima OTLP).
