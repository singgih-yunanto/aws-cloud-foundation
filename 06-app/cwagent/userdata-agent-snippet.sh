# Tambahkan di AKHIR User Data Launch Template (Lab 6).
# Ganti <nama> dengan nama Anda. Konfigurasi dibaca dari SSM Parameter Store saat instance pertama kali menyala.
dnf install -y amazon-cloudwatch-agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c ssm:AmazonCloudWatch-lab-app-<nama> -s
