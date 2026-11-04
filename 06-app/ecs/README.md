# ecs: task definition untuk Lab 7 sampai 9

Dua templat task definition untuk lab-app. Ganti penanda `<nama>` (nama peserta, huruf kecil) dan `<ACCOUNT_ID>` sebelum didaftarkan. Isinya sama dengan yang peserta isi lewat console; berkas ini rujukan trainer dan cadangan bila peserta kewalahan.

> **Status: belum diuji di AWS.** Terutama konfigurasi sidecar ADOT (`--config=/etc/ecs/ecs-default-config.yaml`) dan versi image `aws-otel-collector:latest`; setelah dry-run, kunci tag versi yang berhasil.

| Berkas | Dipakai di | Isi |
|---|---|---|
| `task-definition.v1.json` | Lab 7, Lab 8 | Fargate, 0,25 vCPU / 0,5 GB, satu container `app` (image `lab-app:v1`, port 8080), log ke `/ecs/lab-app-<nama>`. |
| `task-definition.v2-adot.json` | Lab 9 | Fargate, 0,5 vCPU / 1 GB, container `app` (`TRACING=on`) ditambah sidecar `adot-collector`; keduanya berbagi `localhost` (mode awsvpc), sehingga `OTLP_ENDPOINT` bawaan `http://127.0.0.1:4318/v1/traces` langsung bekerja. Perbaikan "indeks" dilakukan dengan merevisi `MOCK_INDEXED` menjadi `yes`. |

Menggantikan penanda dan mendaftarkan (CloudShell):
```bash
NAMA=budi; ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
sed -e "s/<nama>/$NAMA/g" -e "s/<ACCOUNT_ID>/$ACCOUNT/g" task-definition.v1.json > td.json
aws ecs register-task-definition --cli-input-json file://td.json --region ap-southeast-3
```

Prasyarat (trainer): role `lab-ecs-task-execution` (kebijakan `AmazonECSTaskExecutionRolePolicy` ditambah izin `logs:CreateLogGroup` agar `awslogs-create-group` bekerja) dan `lab-ecs-task` (`AWSXRayDaemonWriteAccess` untuk Lab 9), serta image di ECR (`../build-and-push.sh`).

Tag image: `v1` (baik), `v2` (baik, label versi baru), `v-bad` (gagal health check sejak start; untuk latihan circuit breaker dan rollback). Regresi yang lolos health check disimulasikan lewat variabel `ERROR_PCT` / `EXTRA_LATENCY_MS` pada revisi task definition, bukan lewat image.
