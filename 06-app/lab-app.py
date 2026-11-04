#!/usr/bin/env python3
"""lab-app: aplikasi web kecil untuk lab AWS Cloud Foundations (Hari 2 dan 3).

Satu file, hanya library standar untuk fitur inti. Library opsional:
  boto3, pymongo  -> /notes, /checkout (DocumentDB), diambil lewat Secrets Manager
  psycopg2        -> /customers (PostgreSQL lewat VPN; opsional, tidak dipakai di kelas)
  opentelemetry-* -> tracing ke X-Ray (Lab 9: lewat sidecar ADOT di Fargate)

Konfigurasi lewat environment (EC2: lihat user-data.sh; container: task definition):
  PORT=80  TRACING=on|off  DB_MODE=docdb|mock  DOCDB_SECRET=lab/docdb
  PG_SECRET=lab/onprem-pg  AWS_REGION=ap-southeast-3  LOG_FILE=/var/log/lab-app.log
Khusus container / operasi ECS (Hari 3):
  APP_VERSION=v1         label versi; tampil di /, header X-App-Version, dan field "version" pada setiap log
  START_UNHEALTHY=yes    /health menjawab 503 sejak start (simulasi rilis yang gagal health check)
  ERROR_PCT=0            persen request biasa yang dijawab 500 (simulasi regresi yang lolos health check)
  EXTRA_LATENCY_MS=0     tambahan latensi pada setiap request biasa (simulasi regresi kinerja)
  MOCK_INDEXED=no        pada DB_MODE=mock: yes = query /checkout sudah memakai indeks (cepat)
  INSTANCE_ID, AZ        mengganti identitas yang biasanya dibaca dari metadata ECS atau EC2
  LOG_FILE=/dev/stdout   tulis log ke stdout (awslogs menangkapnya)
"""
import json, os, random, signal, subprocess, sys, threading, time, urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("PORT", "80"))
TRACING = os.environ.get("TRACING", "off").lower() == "on"
DB_MODE = os.environ.get("DB_MODE", "docdb").lower()
REGION = os.environ.get("AWS_REGION", "ap-southeast-3")
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/lab-app.log")
CA_FILE = os.environ.get("DOCDB_CA", "/opt/lab-app/global-bundle.pem")
APP_VERSION = os.environ.get("APP_VERSION", "dev")
START_UNHEALTHY = os.environ.get("START_UNHEALTHY", "no").lower() in ("yes", "on", "true", "1")
ERROR_PCT = float(os.environ.get("ERROR_PCT", "0") or 0)
EXTRA_LATENCY_MS = int(os.environ.get("EXTRA_LATENCY_MS", "0") or 0)
MOCK_INDEXED = os.environ.get("MOCK_INDEXED", "no").lower() in ("yes", "on", "true", "1")
STARTED = time.time()
# jalur yang tidak terkena ERROR_PCT / EXTRA_LATENCY_MS (health check dan informasi)
PLAIN_PATHS = ("/health", "/health/ok", "/health/fail", "/version", "/config", "/oom/free", "/cpu/stop")

# ---------- identitas: env -> metadata ECS -> metadata EC2 (IMDSv2) ----------
def http_get(url, headers=None, method="GET", timeout=1):
    try:
        r = urllib.request.Request(url, method=method, headers=headers or {})
        return urllib.request.urlopen(r, timeout=timeout).read().decode()
    except Exception:
        return None

def imds(path):
    tok = http_get("http://169.254.169.254/latest/api/token", {"X-aws-ec2-metadata-token-ttl-seconds": "60"}, "PUT")
    if not tok:
        return None
    return http_get("http://169.254.169.254/latest/meta-data/" + path, {"X-aws-ec2-metadata-token": tok})

def ecs_task_metadata():
    """Metadata task ECS (Fargate maupun EC2). None bila tidak berjalan di ECS."""
    base = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if not base:
        return None
    raw = http_get(base.rstrip("/") + "/task", timeout=2)
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return None

ECS = ecs_task_metadata()
if ECS:
    ECS_INFO = {"cluster": (ECS.get("Cluster") or "").split("/")[-1], "family": ECS.get("Family"),
                "revision": ECS.get("Revision"), "launch_type": ECS.get("LaunchType")}
    INSTANCE_ID = os.environ.get("INSTANCE_ID") or (ECS.get("TaskARN") or "").split("/")[-1] or "ecs-task"
    AZ = os.environ.get("AZ") or ECS.get("AvailabilityZone") or "unknown"
else:
    ECS_INFO = None
    INSTANCE_ID = os.environ.get("INSTANCE_ID") or imds("instance-id") or "local"
    AZ = os.environ.get("AZ") or imds("placement/availability-zone") or "local"

# ---------- log JSON ----------
_log_lock = threading.Lock()
def log(level, msg, **kw):
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "level": level, "instance": INSTANCE_ID,
                       "version": APP_VERSION, "msg": msg, **kw}, ensure_ascii=False)
    with _log_lock:
        if LOG_FILE in ("-", "/dev/stdout"):
            print(line, flush=True)
            return
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except OSError:
            print(line, flush=True)

# ---------- state ----------
state = {"requests": 0, "inflight": 0, "healthy": not START_UNHEALTHY, "indexed": MOCK_INDEXED, "degrade_ms": 0}
state_lock = threading.Lock()
sessions = {}
cpu_procs = []      # semua proses pembakar CPU yang masih hidup
cpu_until = [0.0]   # perkiraan waktu selesai beban CPU terakhir
mem_hog = []        # blok memori yang sengaja ditahan oleh /oom

def read_first(*paths):
    for p in paths:
        try:
            with open(p) as f:
                return f.read().strip()
        except OSError:
            continue
    return None

def mem_status():
    """Pemakaian dan batas memori cgroup (container), dalam MB; n/a bila bukan di cgroup."""
    cur = read_first("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes")
    lim = read_first("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes")
    if not cur:
        return "n/a"
    def mb(v):
        return "tanpa batas" if not v.isdigit() or int(v) > 1 << 50 else "%d MB" % (int(v) // (1 << 20))
    return "%s dari %s" % (mb(cur), mb(lim or "max"))

# ---------- tracing (opsional) ----------
tracer = None
propagator = None
if TRACING:
    try:
        from opentelemetry import trace, context as otctx
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        try:
            from opentelemetry.sdk.extension.aws.trace import AwsXRayIdGenerator
            idgen = AwsXRayIdGenerator()
        except ImportError:
            idgen = None
        res = Resource.create({"service.name": "lab-app", "service.version": APP_VERSION, "cloud.provider": "aws",
                               "host.id": INSTANCE_ID})
        prov = TracerProvider(resource=res, **({"id_generator": idgen} if idgen else {}))
        prov.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=os.environ.get("OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces"))))
        trace.set_tracer_provider(prov)
        tracer = trace.get_tracer("lab-app")
        try:
            from opentelemetry.propagators.aws import AwsXRayPropagator
            propagator = AwsXRayPropagator()
        except ImportError:
            pass
    except ImportError as e:
        log("WARN", "tracing diminta tetapi library OpenTelemetry tidak ada", error=str(e))

class _NoSpan:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def set_attribute(self, *a): pass

def mark_status(sp, status):
    """Menandai span sebagai error/fault agar muncul berwarna di service map."""
    if not tracer or isinstance(sp, _NoSpan):
        return
    from opentelemetry.trace import Status, StatusCode
    sp.set_attribute("http.status_code", status)
    if status >= 500:
        sp.set_status(Status(StatusCode.ERROR))

def span(name, kind=None, **attrs):
    if not tracer:
        return _NoSpan()
    from opentelemetry import trace
    sp = tracer.start_as_current_span(name, kind=kind or trace.SpanKind.INTERNAL, attributes=attrs)
    return sp

# ---------- database ----------
_db_cache = {}
def secret(name):
    import boto3
    sm = boto3.client("secretsmanager", region_name=REGION)
    return json.loads(sm.get_secret_value(SecretId=name)["SecretString"])

def docdb():
    if "client" not in _db_cache:
        import pymongo
        s = secret(os.environ.get("DOCDB_SECRET", "lab/docdb"))
        uri = "mongodb://%s:%s@%s:%s/?tls=true&tlsCAFile=%s&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false" % (
            s["username"], s["password"], s["host"], s.get("port", 27017), CA_FILE)
        _db_cache["client"] = pymongo.MongoClient(uri, serverSelectionTimeoutMS=4000)
        _db_cache["host"] = s["host"]
    return _db_cache["client"]

def is_indexed(user):
    if DB_MODE == "mock":
        return state["indexed"]
    return "customer_id_1" in docdb()[user_db(user)].orders.index_information()

def user_db(user):
    safe = "".join(c for c in (user or "demo") if c.isalnum() or c in "-_")[:30] or "demo"
    return "lab_" + safe

# ---------- daftar endpoint (ditampilkan di halaman /; sama dengan Referensi Endpoint di Lab 4) ----------
ENDPOINTS = [
    ("/", "Halaman status: instance, AZ, jumlah request, in-flight, uptime, health, tracing, degrade, dan daftar endpoint ini", "curl $ALB/"),
    ("/id", "Satu baris teks 'instance-id az'; dipakai loadgen.sh untuk menghitung sebaran per instance", "curl $ALB/id"),
    ("/health", "Health check ALB: 200 ok, atau 503 unhealthy setelah /health/fail; tidak terpengaruh /degrade", "curl -i $ALB/health"),
    ("/health/fail", "Membuat /health menjawab 503 pada instance yang melayani (target menjadi unhealthy)", "curl $ALB/health/fail"),
    ("/health/ok", "Memulihkan /health menjadi 200", "curl $ALB/health/ok"),
    ("/slow?ms=10000", "Long request: menahan request selama ms milidetik (bawaan 10000, maks 60000); tetap dihitung outstanding", "curl \"$ALB/slow?ms=10000\""),
    ("/degrade?ms=10000&only=<instance-id>", "Membuat SATU instance lambat: setiap request (kecuali health check) ditambah ms (bawaan 10000, maks 30000); instance lain menjawab 409", "bash loadgen.sh degrade $ALB <instance-id> 10000"),
    ("/degrade/off?only=<instance-id>", "Memulihkan instance dari mode lambat", "bash loadgen.sh recover $ALB <instance-id>"),
    ("/cpu?seconds=300&workers=2", "Beban CPU tinggi: memulai proses pembakar CPU selama seconds detik (bawaan 300, maks 900) pada instance yang melayani; status beban tampil di halaman /", "bash loadgen.sh cpu $ALB 6 300"),
    ("/cpu/stop", "Menghentikan semua proses beban CPU pada instance yang melayani", "curl $ALB/cpu/stop"),
    ("/session", "Penghitung sesi di memori instance dengan cookie labsess; tanpa sticky hitungan kembali ke 1 saat pindah instance", "bash loadgen.sh session $ALB 10"),
    ("/error", "Menjawab HTTP 500 dan menulis log ERROR (alarm 5xx dan metric filter)", "curl -i $ALB/error"),
    ("/notes?u=<nama>", "GET menampilkan 20 catatan terbaru; POST menyimpan satu catatan (&text=...) di DocumentDB (Lab 6)", "curl -X POST \"$ALB/notes?u=<nama>&text=halo\""),
    ("/checkout?u=<nama>", "Transaksi bertahap: validate, db.find pada orders, payment.call (~300 ms), render; respons memuat steps_ms (Lab 6)", "bash loadgen.sh checkout $ALB 40 4 <nama>"),
    ("/admin/index?u=<nama>", "Membuat indeks customer_id pada orders (memperbaiki query lambat); /admin/index/drop menghapusnya", "curl \"$ALB/admin/index?u=<nama>\""),
    ("/customers", "Opsional, tidak dipakai di kelas: membaca 10 baris customers_masked dari PostgreSQL melalui VPN", "curl $ALB/customers"),
    ("/version", "Versi aplikasi dan identitas task/instance (JSON); dipakai untuk memastikan versi yang sedang melayani (Lab 7 dan 8)", "curl $ALB/version"),
    ("/config", "Konfigurasi aman yang aktif (versi, mode, ERROR_PCT, batas memori); tanpa rahasia", "curl $ALB/config"),
    ("/crash?code=1", "Mematikan proses container sesaat setelah menjawab (exit code code, bawaan 1); ECS menjalankan task pengganti (Lab 8)", "curl $ALB/crash"),
    ("/oom?mb=600", "Menahan memori mb MB (bawaan 600, maks 4096) sampai melewati batas container sehingga di-kill (exit 137, OOMKilled); /oom/free melepas (Lab 8)", "curl \"$ALB/oom?mb=600\""),
]

def cpu_status():
    alive = [p for p in cpu_procs if p.poll() is None]
    if not alive:
        return "tidak aktif"
    return "AKTIF, %d proses pembakar, sisa sekitar %d detik" % (len(alive), max(0, int(cpu_until[0] - time.time())))

def load_status():
    try:
        return " / ".join("%.2f" % x for x in os.getloadavg())
    except (OSError, AttributeError):
        return "n/a"

def html_esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# ---------- handler ----------
class H(BaseHTTPRequestHandler):
    server_version = "lab-app/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # akses log dicatat sendiri
        pass

    def send(self, code, body, ctype="application/json", cookie=None):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if ctype == "application/json" else str(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Instance-Id", INSTANCE_ID)
        self.send_header("X-App-Version", APP_VERSION)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")

    def dispatch(self, method):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path.rstrip("/") or "/"
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if path != "/health":
            with state_lock:
                state["requests"] += 1
                state["inflight"] += 1
        t0 = time.time()
        status = 500
        ctx_token = None
        try:
            if tracer and propagator and self.headers.get("X-Amzn-Trace-Id"):
                from opentelemetry import context as otctx
                ctx = propagator.extract({"X-Amzn-Trace-Id": self.headers["X-Amzn-Trace-Id"]})
                ctx_token = otctx.attach(ctx)
            with span("%s %s" % (method, path), kind=_server_kind(), **{"http.method": method, "http.route": path,
                                                                        "instance_id": INSTANCE_ID, "endpoint": path}) as sp:
                if state["degrade_ms"] and path not in ("/health", "/health/ok", "/health/fail") and not path.startswith("/degrade"):
                    time.sleep(state["degrade_ms"] / 1000.0)  # simulasi node lambat
                status = self.route(method, path, q, raw)
                mark_status(sp, status)
        except Exception as e:
            log("ERROR", "unhandled", path=path, error=repr(e))
            try:
                self.send(500, {"error": repr(e), "instance": INSTANCE_ID})
                status = 500
            except Exception:
                pass
        finally:
            if ctx_token is not None:
                from opentelemetry import context as otctx
                otctx.detach(ctx_token)
            if path != "/health":
                with state_lock:
                    state["inflight"] -= 1
                log("INFO", "request", method=method, path=path, status=status, ms=int((time.time() - t0) * 1000))

    def route(self, method, path, q, raw):
        if path not in PLAIN_PATHS:
            if EXTRA_LATENCY_MS:
                time.sleep(EXTRA_LATENCY_MS / 1000.0)  # simulasi regresi kinerja pada versi ini
            if ERROR_PCT and random.random() * 100 < ERROR_PCT:
                log("ERROR", "error acak dari konfigurasi ERROR_PCT", path=path, error_pct=ERROR_PCT)
                self.send(500, {"error": "simulated regression", "instance": INSTANCE_ID, "version": APP_VERSION}); return 500
        if path == "/health":
            ok = state["healthy"]
            self.send(200 if ok else 503, "ok\n" if ok else "unhealthy\n", "text/plain")
            return 200 if ok else 503
        if path == "/health/fail":
            state["healthy"] = False; log("WARN", "health diset gagal"); self.send(200, {"healthy": False}); return 200
        if path == "/health/ok":
            state["healthy"] = True; log("INFO", "health dipulihkan"); self.send(200, {"healthy": True}); return 200
        if path == "/id":
            self.send(200, "%s %s\n" % (INSTANCE_ID, AZ), "text/plain"); return 200
        if path == "/version":
            self.send(200, {"version": APP_VERSION, "instance": INSTANCE_ID, "az": AZ, "ecs": ECS_INFO}); return 200
        if path == "/config":
            self.send(200, {"version": APP_VERSION, "port": PORT, "tracing": bool(tracer), "db_mode": DB_MODE,
                            "error_pct": ERROR_PCT, "extra_latency_ms": EXTRA_LATENCY_MS, "mock_indexed": state["indexed"],
                            "healthy": state["healthy"], "log_file": LOG_FILE, "memory": mem_status(), "ecs": ECS_INFO,
                            "otlp_endpoint": os.environ.get("OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")}); return 200
        if path == "/crash":
            code = int(q.get("code", "1"))
            log("ERROR", "proses dimatikan sengaja lewat /crash", exit_code=code)
            self.send(200, {"instance": INSTANCE_ID, "exiting_with": code})
            threading.Timer(0.5, os._exit, args=(code,)).start()
            return 200
        if path == "/oom":
            mb = max(1, min(int(q.get("mb", "600")), 4096))
            log("WARN", "alokasi memori dimulai lewat /oom", mb=mb)
            threading.Thread(target=hog_memory, args=(mb,), daemon=True).start()
            self.send(200, {"instance": INSTANCE_ID, "allocating_mb": mb, "memory_before": mem_status()}); return 200
        if path == "/oom/free":
            mem_hog.clear(); log("INFO", "memori yang ditahan dilepas")
            self.send(200, {"instance": INSTANCE_ID, "memory": mem_status()}); return 200
        if path == "/":
            with state_lock:
                s = dict(state)
            rows = "".join("<tr><td><code>%s</code></td><td>%s</td><td><code>%s</code></td></tr>" % (html_esc(e), html_esc(f), html_esc(c))
                           for e, f, c in ENDPOINTS)
            html = ("<!doctype html><meta charset=utf-8><title>lab-app</title>"
                    "<style>body{font-family:sans-serif;margin:24px;max-width:1100px}table{border-collapse:collapse}"
                    "td,th{border:1px solid #ccc;padding:6px 10px;vertical-align:top;text-align:left}th{background:#eef}code{font-size:90%%}</style>"
                    "<h1>lab-app</h1><p>Instance <b>%s</b> di <b>%s</b> &middot; versi <b>%s</b>%s</p>"
                    "<p>Request: %d, in-flight: %d, uptime: %ds, healthy: %s, tracing: %s, degrade: %d ms</p>"
                    "<p>Beban CPU: %s &middot; load average (1/5/15 menit): %s &middot; memori container: %s</p>"
                    "<h2>Endpoint</h2><table><tr><th>Endpoint</th><th>Fungsi</th><th>Contoh</th></tr>%s</table>") % (
                INSTANCE_ID, AZ, html_esc(APP_VERSION),
                (" &middot; ECS %s/%s:%s (%s)" % (html_esc(str(ECS_INFO["cluster"])), html_esc(str(ECS_INFO["family"])),
                                                   ECS_INFO["revision"], html_esc(str(ECS_INFO["launch_type"])))) if ECS_INFO else "",
                s["requests"], s["inflight"], time.time() - STARTED, s["healthy"], "on" if tracer else "off",
                s["degrade_ms"], cpu_status(), load_status(), mem_status(), rows)
            self.send(200, html, "text/html"); return 200
        if path == "/slow":
            ms = min(int(q.get("ms", "10000")), 60000)
            with span("slow.sleep", **{"duration_ms": ms}):
                time.sleep(ms / 1000.0)
            self.send(200, {"instance": INSTANCE_ID, "slept_ms": ms}); return 200
        if path in ("/degrade", "/degrade/off"):
            only = q.get("only")
            if only and only != INSTANCE_ID:
                self.send(409, {"applied": False, "instance": INSTANCE_ID, "note": "bukan instance yang dituju"}); return 409
            state["degrade_ms"] = 0 if path.endswith("off") else min(int(q.get("ms", "10000")), 30000)
            log("WARN", "mode lambat diubah", degrade_ms=state["degrade_ms"])
            self.send(200, {"applied": True, "instance": INSTANCE_ID, "degrade_ms": state["degrade_ms"]}); return 200
        if path == "/cpu":
            seconds = min(int(q.get("seconds", "300")), 900)
            workers = max(1, min(int(q.get("workers", "2")), 4))
            batch = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(workers)]
            cpu_procs.extend(batch)
            cpu_until[0] = max(cpu_until[0], time.time() + seconds)
            threading.Timer(seconds, stop_cpu, args=(batch,)).start()  # hanya menghentikan proses batch ini
            log("WARN", "cpu burn mulai", seconds=seconds, workers=workers)
            self.send(200, {"instance": INSTANCE_ID, "cpu_burn_seconds": seconds, "workers": workers,
                            "running_burn_processes": len(cpu_procs)}); return 200
        if path == "/cpu/stop":
            stop_cpu(); self.send(200, {"instance": INSTANCE_ID, "cpu": "stopped"}); return 200
        if path == "/session":
            c = SimpleCookie(self.headers.get("Cookie", ""))
            sid = c["labsess"].value if "labsess" in c else None
            new = sid is None
            if new:
                sid = "%016x" % random.getrandbits(64)
            n = sessions.get(sid, 0) + 1
            sessions[sid] = n
            self.send(200, {"session": sid, "hits_on_this_instance": n, "instance": INSTANCE_ID, "az": AZ},
                      cookie="labsess=%s; Path=/" % sid if new else None); return 200
        if path == "/error":
            log("ERROR", "error sengaja dibuat lewat /error")
            self.send(500, {"error": "simulated", "instance": INSTANCE_ID}); return 500
        if path == "/notes":
            return self.notes(method, q, raw)
        if path == "/checkout":
            return self.checkout(q)
        if path in ("/admin/index", "/admin/index/drop"):
            return self.admin_index(path, q)
        if path == "/customers":
            return self.customers(q)
        self.send(404, {"error": "not found", "path": path}); return 404

    # ----- DocumentDB -----
    def notes(self, method, q, raw):
        if DB_MODE == "mock":
            self.send(503, {"error": "DB_MODE=mock tidak mendukung /notes"}); return 503
        db = docdb()[user_db(q.get("u"))]
        if method == "POST":
            doc = {"text": q.get("text") or (json.loads(raw).get("text") if raw else "(kosong)"),
                   "instance": INSTANCE_ID, "ts": time.time()}
            with span("db.insert", kind=_client_kind(), **{"db.system": "mongodb", "db.name": db.name, "db.operation": "insert"}):
                db.notes.insert_one(doc)
            self.send(201, {"saved": True, "instance": INSTANCE_ID}); return 201
        with span("db.find", kind=_client_kind(), **{"db.system": "mongodb", "db.name": db.name, "db.operation": "find"}):
            docs = [{"text": d["text"], "instance": d["instance"]} for d in db.notes.find().sort("ts", -1).limit(20)]
        self.send(200, {"served_by": INSTANCE_ID, "notes": docs}); return 200

    def checkout(self, q):
        user = q.get("u", "demo")
        cust = int(q.get("customer", random.randint(1, 5000)))
        steps = {}
        def timed(name, fn):
            t = time.time()
            r = fn()
            steps[name] = int((time.time() - t) * 1000)
            return r
        with span("validate", **{"step": "validate"}):
            timed("validate", lambda: time.sleep(0.005))
        indexed = is_indexed(user)
        def dbfind():
            with span("db.find orders", kind=_client_kind(), **{"step": "db", "db.system": "mongodb", "db.name": user_db(user),
                                                              "db.operation": "find", "indexed": indexed}):
                if DB_MODE == "mock":
                    time.sleep(0.02 if indexed else 0.9)  # simulasi scan vs indeks
                    return 3
                coll = docdb()[user_db(user)].orders
                return len(list(coll.find({"customer_id": cust}).limit(50)))
        n = timed("db_find", dbfind)
        with span("payment.call", kind=_client_kind(), **{"step": "payment", "peer.service": "payment-gateway"}):
            timed("payment", lambda: time.sleep(0.3 + random.random() * 0.05))
        with span("render", **{"step": "render"}):
            timed("render", lambda: time.sleep(0.01))
        self.send(200, {"instance": INSTANCE_ID, "customer_id": cust, "orders": n, "indexed": indexed, "steps_ms": steps})
        return 200

    def admin_index(self, path, q):
        if path.endswith("drop"):
            if DB_MODE != "mock":
                docdb()[user_db(q.get("u"))].orders.drop_indexes()
            state["indexed"] = False
        else:
            if DB_MODE != "mock":
                docdb()[user_db(q.get("u"))].orders.create_index("customer_id")
            state["indexed"] = True
        log("WARN", "indeks diubah", indexed=state["indexed"])
        self.send(200, {"instance": INSTANCE_ID, "indexed": is_indexed(q.get("u")),
                        "note": ("mode mock: indeks hanya berlaku di instance/task ini; untuk semua task, deploy dengan MOCK_INDEXED=yes"
                                 if DB_MODE == "mock" else
                                 "indeks berlaku di database, jadi semua instance langsung merasakannya")})
        return 200

    # ----- PostgreSQL on-prem (Lab 8) -----
    def customers(self, q):
        import psycopg2
        s = secret(os.environ.get("PG_SECRET", "lab/onprem-pg"))
        with span("db.query customers", kind=_client_kind(), **{"db.system": "postgresql", "db.name": s["dbname"],
                                                                "server.address": s["host"]}):
            conn = psycopg2.connect(host=s["host"], port=s.get("port", 5432), dbname=s["dbname"], user=s["username"],
                                    password=s["password"], sslmode=os.environ.get("PG_SSLMODE", "require"), connect_timeout=5)
            cur = conn.cursor()
            cur.execute("SELECT id, nama, nik, kota FROM customers_masked ORDER BY id LIMIT 10")
            rows = [{"id": r[0], "nama": r[1], "nik": r[2], "kota": r[3]} for r in cur.fetchall()]
            conn.close()
        self.send(200, {"served_by": INSTANCE_ID, "source": s["host"], "customers": rows}); return 200


def _server_kind():
    if not tracer: return None
    from opentelemetry import trace
    return trace.SpanKind.SERVER

def _client_kind():
    if not tracer: return None
    from opentelemetry import trace
    return trace.SpanKind.CLIENT

def hog_memory(mb):
    """Menahan mb MB secara bertahap (16 MB per langkah) agar kenaikan terlihat di grafik memori."""
    for _ in range(0, mb, 16):
        mem_hog.append(bytearray(b"\x01") * (16 * 1024 * 1024))  # diisi nilai agar benar-benar terpakai
        time.sleep(0.05)

def stop_cpu(batch=None):
    """Tanpa argumen: hentikan semua proses beban CPU. Dengan batch: hanya proses milik batch itu."""
    targets = list(cpu_procs) if batch is None else list(batch)
    for p in targets:
        if p in cpu_procs:
            cpu_procs.remove(p)
        try:
            p.kill()
        except OSError:
            pass

def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    def bye(*_):
        stop_cpu()
        threading.Thread(target=srv.shutdown).start()
    signal.signal(signal.SIGTERM, bye)
    log("INFO", "lab-app start", port=PORT, tracing=bool(tracer), db_mode=DB_MODE, healthy=state["healthy"],
        error_pct=ERROR_PCT, extra_latency_ms=EXTRA_LATENCY_MS, ecs=ECS_INFO)
    srv.serve_forever()

if __name__ == "__main__":
    main()
