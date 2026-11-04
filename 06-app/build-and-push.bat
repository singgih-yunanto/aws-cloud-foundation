@echo off
rem ============================================================================
rem Membangun image lab-app (tag v1, v2, v-bad) dan mengunggahnya ke Amazon ECR.
rem Versi Windows dari build-and-push.sh. Dijalankan TRAINER sekali sebelum kelas.
rem
rem Prasyarat:
rem   - Docker Desktop terpasang dan SEDANG BERJALAN (ikon paus tidak lagi berputar)
rem   - AWS CLI v2 terpasang, kredensial trainer sudah diatur (aws configure atau aws sso login)
rem
rem Pemakaian (dari Command Prompt atau PowerShell, folder bebas):
rem   build-and-push.bat ACCOUNT_ID [REGION] [REPO]
rem   contoh: build-and-push.bat 123456789012 ap-southeast-3 lab-app
rem
rem Yang dilakukan (rincian dan alasannya ada di
rem 03-trainer-kit\Runbook\Runbook-Persiapan-Hari3.id.md):
rem   1. membuat repository ECR bila belum ada, dengan scan-on-push
rem   2. login Docker ke ECR memakai token sementara
rem   3. membangun tiga tag untuk linux/amd64 (Fargate bawaan memakai x86_64,
rem      meski laptop Anda ARM)
rem   4. mengunggah ketiganya
rem ============================================================================
setlocal EnableExtensions

if "%~1"=="" goto usage

set "ACCOUNT=%~1"
set "REGION=%~2"
set "REPO=%~3"
if "%REGION%"=="" set "REGION=ap-southeast-3"
if "%REPO%"=="" set "REPO=lab-app"
set "REGISTRY=%ACCOUNT%.dkr.ecr.%REGION%.amazonaws.com"

rem Bekerja dari folder berkas ini (tempat Dockerfile berada), apa pun folder aktif Anda.
cd /d "%~dp0"
if not exist Dockerfile (
  echo [GAGAL] Dockerfile tidak ditemukan di %CD%.
  exit /b 1
)

echo ^>^> Memeriksa alat
where docker >nul 2>&1
if errorlevel 1 (
  echo [GAGAL] Perintah docker tidak ditemukan. Pasang Docker Desktop dan buka ulang terminal.
  exit /b 1
)
where aws >nul 2>&1
if errorlevel 1 (
  echo [GAGAL] Perintah aws tidak ditemukan. Pasang AWS CLI v2 dan buka ulang terminal.
  exit /b 1
)
call docker info >nul 2>&1
if errorlevel 1 (
  echo [GAGAL] Docker daemon tidak merespons. Jalankan Docker Desktop, tunggu sampai statusnya Running, lalu ulangi.
  exit /b 1
)
call aws sts get-caller-identity --query Account --output text >"%TEMP%\lab-app-acct.txt" 2>nul
if errorlevel 1 (
  echo [GAGAL] Kredensial AWS tidak valid. Jalankan aws configure atau aws sso login, lalu ulangi.
  exit /b 1
)
set /p CALLER=<"%TEMP%\lab-app-acct.txt"
del "%TEMP%\lab-app-acct.txt" >nul 2>&1
if not "%CALLER%"=="%ACCOUNT%" (
  echo [GAGAL] Kredensial aktif milik akun %CALLER%, tetapi ACCOUNT_ID yang diminta %ACCOUNT%.
  echo         Periksa profil AWS yang dipakai ^(set AWS_PROFILE=...^).
  exit /b 1
)

echo ^>^> Repository %REPO% di %REGION%
call aws ecr describe-repositories --repository-names "%REPO%" --region "%REGION%" >nul 2>&1
if errorlevel 1 (
  call aws ecr create-repository --repository-name "%REPO%" --region "%REGION%" --image-scanning-configuration scanOnPush=true >nul
  if errorlevel 1 (
    echo [GAGAL] Tidak dapat membuat repository %REPO%.
    exit /b 1
  )
)

echo ^>^> Login ke %REGISTRY%
call aws ecr get-login-password --region "%REGION%" | call docker login --username AWS --password-stdin "%REGISTRY%"
if errorlevel 1 (
  echo [GAGAL] Login Docker ke ECR gagal.
  exit /b 1
)

call :build v1 v1 no
if errorlevel 1 exit /b 1
call :build v2 v2 no
if errorlevel 1 exit /b 1
call :build v-bad v-bad yes
if errorlevel 1 exit /b 1

echo ^>^> Selesai. Daftar tag:
call aws ecr list-images --repository-name "%REPO%" --region "%REGION%" --query "imageIds[].imageTag" --output text
exit /b 0

rem ----------------------------------------------------------------------------
rem :build TAG APP_VERSION START_UNHEALTHY
:build
echo ^>^> Build %REPO%:%~1
call docker build --platform linux/amd64 --build-arg APP_VERSION=%~2 --build-arg START_UNHEALTHY=%~3 -t "%REGISTRY%/%REPO%:%~1" .
if errorlevel 1 (
  echo [GAGAL] Build %~1 gagal.
  exit /b 1
)
call docker push "%REGISTRY%/%REPO%:%~1"
if errorlevel 1 (
  echo [GAGAL] Push %~1 gagal.
  exit /b 1
)
exit /b 0

:usage
echo Pemakaian: build-and-push.bat ACCOUNT_ID [REGION] [REPO]
echo Contoh   : build-and-push.bat 123456789012 ap-southeast-3 lab-app
exit /b 1
