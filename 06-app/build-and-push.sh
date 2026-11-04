#!/usr/bin/env bash
# Membangun image lab-app (tag v1, v2, v-bad) dan mengunggahnya ke Amazon ECR.
# Dijalankan TRAINER sekali sebelum kelas, dari folder 06-app, di mesin yang punya Docker dan AWS CLI.
#
#   bash build-and-push.sh <ACCOUNT_ID> [REGION=ap-southeast-3] [REPO=lab-app]
#
# Yang dilakukan (rincian dan alasannya ada di 03-trainer-kit/Runbook/Runbook-Persiapan-Hari3.id.md):
#   1. membuat repository ECR bila belum ada, dengan scan-on-push
#   2. login Docker ke ECR memakai token sementara
#   3. membangun tiga tag untuk arsitektur linux/amd64 (Fargate bawaan memakai x86_64, meski laptop Anda ARM)
#   4. mengunggah ketiganya
set -euo pipefail

ACCOUNT="${1:?isi ACCOUNT_ID sebagai argumen pertama}"
REGION="${2:-ap-southeast-3}"
REPO="${3:-lab-app}"
REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com"

echo ">> Repository ${REPO}"
aws ecr describe-repositories --repository-names "${REPO}" --region "${REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${REPO}" --region "${REGION}" \
       --image-scanning-configuration scanOnPush=true >/dev/null

echo ">> Login ke ${REGISTRY}"
aws ecr get-login-password --region "${REGION}" | docker login --username AWS --password-stdin "${REGISTRY}"

build() {  # build <tag> <APP_VERSION> <START_UNHEALTHY>
  echo ">> Build ${REPO}:$1"
  docker build --platform linux/amd64 \
    --build-arg APP_VERSION="$2" --build-arg START_UNHEALTHY="$3" \
    -t "${REGISTRY}/${REPO}:$1" .
  docker push "${REGISTRY}/${REPO}:$1"
}

build v1     v1     no
build v2     v2     no
build v-bad  v-bad  yes

echo ">> Selesai. Daftar tag:"
aws ecr list-images --repository-name "${REPO}" --region "${REGION}" --query 'imageIds[].imageTag' --output text
