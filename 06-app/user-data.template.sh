#!/bin/bash
# User Data lab-app (Amazon Linux 2023). File ini dibuat oleh build-userdata.py; jangan diedit langsung.
# Ubah nilai di bagian KONFIGURASI saja, lalu tempel seluruh isinya ke Launch Template > Advanced details > User data.
# CloudWatch Agent TIDAK dipasang di sini: peserta memasangnya pada Lab 5 (lihat cwagent/). Aplikasi hanya menulis /var/log/lab-app.log.

### KONFIGURASI ###
TRACING=@@TRACING@@            # on = kirim trace OpenTelemetry ke 127.0.0.1:4318 (Lab 6; perlu CloudWatch Agent dengan penerima OTLP)
EXTRAS=@@EXTRAS@@              # yes = pasang boto3/pymongo/psycopg2/OpenTelemetry (Lab 6 dan 8); no = hanya library standar (Lab 4)
DB_MODE=@@DB_MODE@@            # docdb = DocumentDB (Lab 6); mock = tanpa database
DOCDB_SECRET=lab/docdb         # nama secret di Secrets Manager (Lab 6)
PG_SECRET=lab/onprem-pg        # nama secret PostgreSQL on-prem (Lab 8)
REGION=ap-southeast-3
### AKHIR KONFIGURASI ###

set -x
exec > >(tee /var/log/lab-app-userdata.log) 2>&1

dnf install -y python3-pip httpd-tools
mkdir -p /opt/lab-app
echo '@@APP_B64@@' | base64 -d | gunzip > /opt/lab-app/lab-app.py

if [ "$EXTRAS" = "yes" ]; then
  pip3 install --quiet boto3 pymongo psycopg2-binary \
    opentelemetry-sdk opentelemetry-exporter-otlp-proto-http \
    opentelemetry-sdk-extension-aws opentelemetry-propagator-aws-xray
  curl -sS -o /opt/lab-app/global-bundle.pem https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
fi

cat > /etc/systemd/system/lab-app.service <<EOF
[Unit]
Description=lab-app
After=network-online.target
[Service]
Environment=PORT=80 TRACING=$TRACING DB_MODE=$DB_MODE DOCDB_SECRET=$DOCDB_SECRET PG_SECRET=$PG_SECRET AWS_REGION=$REGION
ExecStart=/usr/bin/python3 /opt/lab-app/lab-app.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF
touch /var/log/lab-app.log
systemctl daemon-reload
systemctl enable --now lab-app
