#!/usr/bin/env bash
# loadgen.sh - generator beban sederhana untuk lab-app (hanya butuh bash, curl, xargs, awk).
# Pemakaian: ./loadgen.sh <mode> <URL ALB atau instance> [opsi]
#   fast     <URL> [jumlah=60] [paralel=10]          request cepat ke /id: sebaran per instance + latensi rata-rata dan p95
#   degrade  <URL> <instance-id> [ms=10000]          membuat SATU instance lambat (setiap request +ms); diulang sampai instance itu menjawab
#   recover  <URL> <instance-id>                     memulihkan instance tersebut
#   slow     <URL> [jumlah=4] [ms=10000]             long request ke /slow (paralel); lihat in-flight di halaman utama tiap instance
#   cpu      <URL> [jumlah=6] [detik=300]            panggil /cpu berulang agar CPU instance terbakar
#   session  <URL> [jumlah=10]                       jumlah request tanpa dan dengan cookie jar; hitung per instance
#   checkout <URL> [jumlah=40] [paralel=4] [user=demo]  request /checkout, tampilkan rata-rata dan p95
set -u
MODE="${1:-}"; URL="${2:-}"
if [ -z "$MODE" ] || [ -z "$URL" ]; then sed -n '2,10p' "$0"; exit 1; fi
URL="${URL%/}"
case "$URL" in http*) ;; *) URL="http://$URL" ;; esac

# menghitung baris yang sama: masukan "kata1 kata2", keluaran "jumlah  kata1 kata2"
tally() { sort | uniq -c | sort -rn | awk '{printf "  %-6s request -> %s %s\n",$1,$2,$3}'; }
# statistik latensi dari daftar angka (detik) di stdin
lat() { sort -n | awk '{a[NR]=$1; s+=$1} END {if (NR) printf "  latensi: rata-rata=%.3fs  p95=%.3fs  maks=%.3fs\n", s/NR, a[int(NR*0.95)+(NR*0.95>int(NR*0.95))], a[NR]}'; }

case "$MODE" in
  fast)
    N="${3:-60}"; P="${4:-10}"; T="$(mktemp)"
    echo "== $N request cepat (paralel $P) ke $URL/id"
    # keluaran per request: "<instance-id> <az> <detik>"
    seq "$N" | xargs -P "$P" -I{} sh -c 'curl -s -m 30 -w "%{time_total}\n" "$0/id" | tr "\n" " "; echo' "$URL" > "$T"
    awk '{print $1, $2}' "$T" | tally
    awk '{print $3}' "$T" | lat
    rm -f "$T"
    ;;
  degrade|recover)
    ID="${3:-}"; MS="${4:-10000}"
    if [ -z "$ID" ]; then echo "butuh instance-id (lihat $URL/id)"; exit 1; fi
    EP="degrade?ms=$MS&only=$ID"; [ "$MODE" = recover ] && EP="degrade/off?only=$ID"
    for i in $(seq 40); do
      R="$(curl -s -m 30 "$URL/$EP")"
      case "$R" in *'"applied": true'*) echo "$R"; exit 0 ;; esac
    done
    echo "instance $ID tidak terjangkau lewat $URL setelah 40 percobaan"; exit 1
    ;;
  slow)
    N="${3:-4}"; MS="${4:-10000}"
    echo "== $N long request ($MS ms) ke $URL/slow, paralel"
    seq "$N" | xargs -P "$N" -I{} curl -s -m 90 "$URL/slow?ms=$MS" | grep -o '"instance": "[^"]*"' | sort | uniq -c
    ;;
  cpu)
    N="${3:-6}"; SEC="${4:-300}"; T="$(mktemp)"
    echo "== $N panggilan /cpu (${SEC}s, 2 proses). Tiap panggilan membakar CPU di instance yang melayaninya."
    for i in $(seq "$N"); do curl -s -m 10 "$URL/cpu?seconds=$SEC&workers=2"; echo; done > "$T"
    echo "Instance yang terkena beban:"
    grep -o '"instance": "[^"]*"' "$T" | sed 's/"instance": //' | sort | uniq -c | awk '{print "  " $1 " panggilan -> " $2}'
    echo "Pastikan SEMUA instance muncul di atas. Bila ada yang belum, ulangi perintah ini (ALB memilih instance bergantian/acak)."
    echo "Beban berjalan ${SEC} detik. Target tracking butuh CPU rata-rata di atas target selama beberapa menit berturut-turut."
    echo "Periksa tiap instance: halaman / menampilkan 'Beban CPU: AKTIF'. Hentikan dengan: curl $URL/cpu/stop (ulangi beberapa kali)."
    rm -f "$T"
    ;;
  session)
    N="${3:-10}"; JAR="$(mktemp)"
    echo "== $N request TANPA cookie (tiap request sesi baru):"
    seq "$N" | xargs -I{} curl -s -m 10 "$URL/session" | grep -o '"instance": "[^"]*"' | sed 's/"instance": //' | tally
    echo "== $N request DENGAN cookie jar (sticky mengunci ke satu instance bila diaktifkan):"
    for i in $(seq "$N"); do curl -s -m 10 -b "$JAR" -c "$JAR" "$URL/session"; echo; done | grep -o '"instance": "[^"]*"' | sed 's/"instance": //' | tally
    rm -f "$JAR"
    ;;
  checkout)
    N="${3:-40}"; P="${4:-4}"; U="${5:-demo}"
    echo "== $N request /checkout?u=$U (paralel $P)"
    seq "$N" | xargs -P "$P" -I{} curl -s -m 30 -o /dev/null -w '%{time_total}\n' "$URL/checkout?u=$U" | lat
    ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
