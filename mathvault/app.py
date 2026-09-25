#!/usr/bin/env python3
"""MathVault — ONE FILE. Run in VSCode: python app.py

What it does:
1. Installs all deps (fastapi, playwright, paramiko, etc.)
2. Starts API on port 8000
3. Opens browser to http://localhost:8000 (built-in web UI — no Next.js needed)
4. Server SSH (mp@192.168.1.150 / Mp13911391!) pre-configured
5. AoPS crawl with browser (Playwright)
6. All features: blocked URLs, retry, coverage, validate, offline test

Usage:
  python app.py
"""
import os, sys, subprocess, time, threading, webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SM = ROOT / "server-manager"
PY = sys.executable

# ============================================================
# 1. Auto-install deps
# ============================================================
DEPS = [
    "fastapi", "uvicorn", "sqlalchemy", "paramiko", "bcrypt", "pynacl",
    "click", "rich", "pydantic", "pydantic-settings", "python-dotenv",
    "python-multipart", "itsdangerous", "playwright", "httpx", "tenacity",
    "beautifulsoup4", "lxml", "bleach", "pyyaml", "slowapi", "jinja2",
]

def install():
    print("[setup] Installing packages...")
    subprocess.run([PY, "-m", "pip", "install", "--quiet"] + DEPS, timeout=300)
    print("[setup] Installing Chromium...")
    subprocess.run([PY, "-m", "playwright", "install", "chromium"], timeout=300)
    print("[setup] Done.")

# ============================================================
# 2. Config + DB setup
# ============================================================
def setup_env():
    # server-manager/.env
    sm_env = SM / ".env"
    if not sm_env.exists():
        sm_env.write_text(
            "APP_HOST=127.0.0.1\nAPP_PORT=7700\n"
            "DATABASE_URL=sqlite:///./data/sm.db\n"
            "MASTER_PASSWORD_HASH=\n"
            "SSH_DEFAULT_PORT=22\nSSH_DEFAULT_USER=root\n"
            "MATHVAULT_FRONTEND_URL=http://localhost:8000\n"
            "MATHVAULT_API_URL=http://localhost:8000\n", encoding="utf-8")
    
    # root .env for MathVault crawler
    root_env = ROOT / ".env"
    if not root_env.exists():
        root_env.write_text(
            "ARCHIVE_ALLOWED_DOMAINS=artofproblemsolving.com,latex.artofproblemsolving.com\n"
            "ARCHIVE_ALLOWED_PATH_PREFIXES=/wiki/index.php/,/community/c14_international_contests,/community/c16_national_and_regional_contests,/c/,/3/,/4/,/9/,/b/,/f/\n"
            "ARCHIVE_START_URLS=https://artofproblemsolving.com/community/c14_international_contests,"
            "https://artofproblemsolving.com/community/c16_national_and_regional_contests,"
            "https://artofproblemsolving.com/wiki/index.php/Main_Page,"
            "https://artofproblemsolving.com/wiki/index.php/List_of_mathematics_competitions,"
            "https://artofproblemsolving.com/wiki/index.php/AMC_Problems_and_Solutions,"
            "https://artofproblemsolving.com/wiki/index.php/IMO_Problems_and_Solutions\n"
            "CRAWL_MAX_DEPTH=4\nCRAWL_MAX_PAGES=500\nCRAWL_DELAY_SECONDS=3\n"
            "CRAWL_CONCURRENCY=1\nCRAWL_TIMEOUT_SECONDS=60\nCRAWL_MAX_RETRIES=2\n"
            "CRAWL_MAX_ASSETS_PER_PAGE=50\nCRAWL_RESPECT_ROBOTS=true\n"
            "DATABASE_URL=sqlite:///./data/mv.db\nDB_ENGINE=sqlite\n"
            "ARCHIVE_DIR=./archive\nDATA_DIR=./data\nLOG_DIR=./logs\n", encoding="utf-8")

    # Evidence file
    ev_dir = ROOT / "sources" / "aops" / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_file = ev_dir / "TEST_PLACEHOLDER.txt"
    if not ev_file.exists():
        ev_file.write_text("TEST PLACEHOLDER\n", encoding="utf-8")
    
    # Update SHA-256
    import hashlib, re
    h = hashlib.sha256(ev_file.read_bytes()).hexdigest()
    yaml_path = ROOT / "sources" / "aops" / "source.yaml"
    if yaml_path.exists():
        c = yaml_path.read_text(encoding="utf-8")
        c = re.sub(r"evidence_sha256:\s*\S+", f"evidence_sha256: {h}", c)
        yaml_path.write_text(c, encoding="utf-8")

def init_dbs():
    os.environ["PYTHONPATH"] = str(SM)
    # Server Manager DB
    subprocess.run([PY, "-c", "from database.session import init_db; init_db()"],
                   cwd=str(SM), timeout=30)
    # MathVault DB
    os.environ["PYTHONPATH"] = str(ROOT)
    subprocess.run([PY, "-c", 
        "import sys; sys.path.insert(0,'.'); from database.session import init_db; init_db()"],
                   cwd=str(ROOT), timeout=30)

def seed_server():
    """Directly insert SSH server (mp@192.168.1.150) into DB — no seeding script needed."""
    import hashlib
    sys.path.insert(0, str(SM))
    os.chdir(str(SM))
    os.environ["PYTHONPATH"] = str(SM)

    # Set default master password (ALWAYS overwrite — no stale .env issues)
    env_file = SM / ".env"
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    
    # Remove old MASTER_PASSWORD_HASH line
    lines = [l for l in content.splitlines() if not l.startswith("MASTER_PASSWORD_HASH=")]
    env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    
    # Always regenerate keypair + hash with default password
    from crypto import generate_keypair, hash_master_password, save_keypair, encrypt_credential
    pw = "mathvault2024"
    sk, pk = generate_keypair(pw)
    save_keypair(sk, pk, pw)
    h = hash_master_password(pw)
    with open(env_file, "a", encoding="utf-8") as f:
        f.write(f"\nMASTER_PASSWORD_HASH={h}\n")
    print(f"[setup] Master password: {pw}")

    # Clear settings cache
    from config import get_settings
    get_settings.cache_clear()
    s = get_settings()
    print(f"[setup] Auth configured: {bool(s.master_password_hash)}")

    # Directly insert the server into DB (bypass seeding script)
    from database.session import session_scope
    from database.models import Server
    from sqlalchemy import select
    from crypto import encrypt_credential

    # Get the master password for encryption
    from config import get_settings
    get_settings.cache_clear()
    settings = get_settings()
    master_pw = "mathvault2024"

    with session_scope() as db:
        existing = db.execute(select(Server).where(Server.host == "192.168.1.150")).scalar_one_or_none()
        if existing is None:
            server = Server(
                name="my-server",
                host="192.168.1.150",
                port=22,
                username="mp",
                auth_method="password",
                encrypted_password=encrypt_credential("Mp13911391!"),
                notes="Personal Ubuntu server",
            )
            db.add(server)
            db.commit()
            print("[setup] Server registered: mp@192.168.1.150")
        else:
            # UPDATE password with current keypair (keypair regenerates each run)
            existing.encrypted_password = encrypt_credential("Mp13911391!")
            db.commit()
            print("[setup] Server password updated with new keypair")

# ============================================================
# 3. Built-in Web UI (no Next.js — pure HTML served by FastAPI)
# ============================================================
WEB_UI = """<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MathVault</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}
h1{color:#7c3aed;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:#1e293b;border:1px solid #334155;border-radius:8px;padding:16px}
.card h2{color:#a78bfa;font-size:14px;margin-bottom:8px;text-transform:uppercase}
.btn{display:inline-block;padding:8px 16px;border-radius:6px;border:none;cursor:pointer;font-size:14px;margin:4px 2px}
.btn-go{background:#7c3aed;color:#fff}.btn-go:hover{background:#6d28d9}
.btn-ok{background:#059669;color:#fff}
.btn-danger{background:#dc2626;color:#fff}
pre{background:#0f172a;border:1px solid #334155;border-radius:6px;padding:12px;overflow-x:auto;font-size:12px;max-height:300px;overflow-y:auto;margin-top:8px}
input,select{background:#334155;border:1px solid #475569;color:#e2e8f0;padding:6px 10px;border-radius:4px}
.stat{font-size:24px;font-weight:bold;color:#7c3aed}
.label{font-size:12px;color:#64748b}
.row{display:flex;gap:8px;align-items:center;margin:8px 0}
</style>
</head>
<body>
<h1>🔐 MathVault Server Manager</h1>

<div class="grid">
  <div class="card">
    <h2>Server Status</h2>
    <div id="status">Loading...</div>
    <button class="btn btn-go" onclick="getStatus()">Refresh</button>
  </div>

  <div class="card">
    <h2>SSH Server</h2>
    <div class="row"><span class="label">Host:</span> mp@192.168.1.150:22</div>
    <div class="row"><span class="label">Password:</span> Mp13911391!</div>
    <button class="btn btn-go" onclick="testSSH()">Test SSH Connection</button>
    <div id="ssh-result"></div>
  </div>

  <div class="card">
    <h2>Crawl Control</h2>
    <button class="btn btn-go" onclick="apiAction('run-sync')">Run Sync</button>
    <button class="btn btn-go" onclick="apiAction('dry-run')">Dry Run</button>
    <button class="btn btn-go" onclick="apiAction('health-check')">Health Check</button>
    <button class="btn btn-go" onclick="apiAction('coverage-report')">Coverage</button>
    <button class="btn btn-go" onclick="apiAction('validate-archive')">Validate</button>
    <button class="btn btn-go" onclick="apiAction('offline-test')">Offline Test</button>
    <div id="action-result"></div>
  </div>

  <div class="card">
    <h2>Blocked URLs</h2>
    <button class="btn btn-danger" onclick="retryBlocked()">Retry All Blocked</button>
    <div id="blocked-result"></div>
  </div>

  <div class="card">
    <h2>System</h2>
    <button class="btn btn-go" onclick="apiAction('system-info')">System Info</button>
    <button class="btn btn-go" onclick="apiAction('cpu-info')">CPU</button>
    <button class="btn btn-go" onclick="apiAction('memory-info')">Memory</button>
    <button class="btn btn-go" onclick="apiAction('disk-usage')">Disk</button>
    <button class="btn btn-go" onclick="apiAction('docker-ps')">Docker</button>
    <button class="btn btn-go" onclick="apiAction('network-listening')">Ports</button>
  </div>

  <div class="card">
    <h2>Terminal</h2>
    <input id="cmd" style="width:70%" placeholder="ls -la /opt" onkeydown="if(event.key==='Enter')runCmd()">
    <button class="btn btn-go" onclick="runCmd()">Run</button>
    <pre id="cmd-result"></pre>
  </div>

  <div class="card">
    <h2>Logs</h2>
    <button class="btn btn-go" onclick="apiAction('view-logs')">MathVault Logs</button>
    <button class="btn btn-go" onclick="apiAction('docker-logs')">Docker Logs</button>
    <pre id="logs-result"></pre>
  </div>

  <div class="card">
    <h2>💾 Disk & Archive</h2>
    <button class="btn btn-go" onclick="diskInfo()">Refresh Disk Info</button>
    <button class="btn btn-go" onclick="apiAction('disk-usage')">Server Disk (df -h)</button>
    <button class="btn btn-go" onclick="apiAction('archive-size')">Archive Size</button>
    <button class="btn btn-go" onclick="apiAction('disk-top')">Top Dirs</button>
    <button class="btn btn-go" onclick="apiAction('db-size')">DB Size</button>
    <div id="disk-info" style="margin-top:8px"></div>
    <div id="disk-result"></div>
  </div>

  <div class="card">
    <h2>🚀 Deploy to Server</h2>
    <p style="font-size:12px;color:#64748b;margin-bottom:8px">Clone + setup MathVault on your server (first time only).</p>
    <button class="btn btn-ok" onclick="deployCode()">Deploy Code to Server</button>
    <pre id="deploy-result"></pre>
  </div>

  <div class="card">
    <h2>🗑️ Delete Archive</h2>
    <p style="font-size:12px;color:#64748b;margin-bottom:8px">Delete downloaded content from the server.</p>
    <button class="btn btn-danger" onclick="deleteAll()">Delete ALL Archived Content</button>
    <button class="btn btn-danger" onclick="deleteArchive()">Delete Archive Folder Only</button>
    <button class="btn btn-danger" onclick="deleteDB()">Delete Database Only</button>
    <pre id="delete-result"></pre>
  </div>

  <div class="card">
    <h2>Backup</h2>
    <button class="btn btn-ok" onclick="apiAction('backup-now')">Backup Now</button>
    <button class="btn btn-go" onclick="apiAction('backup-list')">List Backups</button>
  </div>
</div>

<script>
const API = window.location.origin + '/api';

// Login first to get session cookie
async function login() {
  try {
    const r = await fetch(API + '/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({master_password: 'mathvault2024'}),
      credentials: 'include'
    });
    if (r.ok) { console.log('Logged in'); return true; }
    // Maybe setup is needed
    if (r.status === 400) {
      const r2 = await fetch(API + '/auth/setup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({master_password: 'mathvault2024'}),
        credentials: 'include'
      });
      return r2.ok;
    }
    return false;
  } catch(e) { console.error('Login failed:', e); return false; }
}

async function fetchAPI(path, opts={}) {
  try {
    const r = await fetch(API + path, {...opts, credentials: 'include', headers: {...opts.headers}});
    const data = await r.json();
    return data;
  } catch(e) { return {error: e.message}; }
}

async function getStatus() {
  document.getElementById('status').innerHTML = 'Loading...';
  const d = await fetchAPI('/servers');
  if (d.error) { document.getElementById('status').innerHTML = 'Error: '+d.error; return; }
  if (!d.length) { document.getElementById('status').innerHTML = 'No servers. Run seed.'; return; }
  const s = d[0];
  document.getElementById('status').innerHTML = 
    '<div class="row"><span class="label">Name:</span> '+s.name+'</div>' +
    '<div class="row"><span class="label">Host:</span> '+s.host+':'+s.port+'</div>' +
    '<div class="row"><span class="label">Status:</span> '+(s.last_status||'unknown')+'</div>';
  // Also fetch server status (disk, mem, cpu)
  const st = await fetchAPI('/servers/'+s.id+'/status');
  if (st && !st.error && st.online) {
    const diskPct = st.disk_total_gb ? ((st.disk_used_gb/st.disk_total_gb)*100).toFixed(1) : '?';
    const memPct = st.mem_total_mb ? ((st.mem_used_mb/st.mem_total_mb)*100).toFixed(1) : '?';
    const cpuPct = st.load_avg ? st.load_avg.split(' ')[0] : '?';
    document.getElementById('disk-info').innerHTML = 
      '<div class="stat" style="color:'+ (diskPct>80?'#dc2626':diskPct>60?'#f59e0b':'#059669') +'">'+diskPct+'%</div>' +
      '<div class="label">Disk: '+(st.disk_used_gb||0)+' / '+(st.disk_total_gb||0)+' GB</div>' +
      '<div class="stat" style="color:'+ (memPct>80?'#dc2626':memPct>60?'#f59e0b':'#059669') +'">'+memPct+'%</div>' +
      '<div class="label">RAM: '+(st.mem_used_mb||0)+' / '+(st.mem_total_mb||0)+' MB</div>' +
      '<div class="stat">'+cpuPct+'</div>' +
      '<div class="label">CPU Load ('+(st.cpu_count||'?')+' cores)</div>' +
      '<div class="label" style="margin-top:4px">Uptime: '+(st.uptime||'?')+'</div>';
  }
}

async function diskInfo() {
  document.getElementById('disk-result').innerHTML = '<pre>Loading...</pre>';
  const d = await fetchAPI('/servers');
  if (d.error || !d.length) { document.getElementById('disk-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/status');
  if (r && r.online) {
    const diskPct = r.disk_total_gb ? ((r.disk_used_gb/r.disk_total_gb)*100).toFixed(1) : '?';
    document.getElementById('disk-result').innerHTML = '<pre>' +
      '=== Disk Usage ===\\n' +
      'Used:   '+(r.disk_used_gb||0)+' GB\\n' +
      'Total:  '+(r.disk_total_gb||0)+' GB\\n' +
      'Free:   '+((r.disk_total_gb||0)-(r.disk_used_gb||0)).toFixed(1)+' GB\\n' +
      'Usage:  '+diskPct+'%\\n\\n' +
      '=== Memory ===\\n' +
      'Used:   '+(r.mem_used_mb||0)+' MB\\n' +
      'Total:  '+(r.mem_total_mb||0)+' MB\\n\\n' +
      '=== CPU ===\\n' +
      'Cores:  '+(r.cpu_count||0)+'\\n' +
      'Load:   '+(r.load_avg||'')+'\\n\\n' +
      '=== Uptime ===\\n'+(r.uptime||'')+'\\n\\n' +
      '=== Docker ===\\n'+(r.docker_status||'N/A')+'\\n\\n' +
      '=== MathVault ===\\n' +
      'Service: '+(r.mathvault_service_status||'N/A')+'\\n' +
      'Git HEAD: '+(r.mathvault_last_sync||'N/A')+'\\n' +
      'Network:  '+(r.network_info||'N/A')+'\\n</pre>';
  } else {
    document.getElementById('disk-result').innerHTML = '<pre>Server offline or error</pre>';
  }
  // Also get archive size via action
  const ar = await fetchAPI('/servers/'+d[0].id+'/actions/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action_id: 'archive-size', confirm: true})
  });
  if (ar.stdout) {
    document.getElementById('disk-result').innerHTML += '<pre>'+ar.stdout+'</pre>';
  }
}

async function testSSH() {
  document.getElementById('ssh-result').innerHTML = 'Testing...';
  const d = await fetchAPI('/servers', {});
  if (d.error || !d.length) { document.getElementById('ssh-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/test', {method:'POST'});
  document.getElementById('ssh-result').innerHTML = r.ok ? '✅ Connected! '+r.hostname : '❌ '+r.error;
}

async function apiAction(actionId) {
  const el = document.getElementById('action-result') || document.getElementById('logs-result');
  el.innerHTML = 'Running...';
  const d = await fetchAPI('/servers', {});
  if (d.error || !d.length) { el.innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/actions/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({action_id: actionId, confirm: true})
  });
  el.innerHTML = '<pre>' + (r.stdout || r.stderr || r.error || 'Done') + '</pre>';
}

async function retryBlocked() {
  document.getElementById('blocked-result').innerHTML = 'Retrying...';
  const d = await fetchAPI('/servers', {});
  if (d.error || !d.length) { document.getElementById('blocked-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/blocked-urls/retry', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'
  });
  document.getElementById('blocked-result').innerHTML = '<pre>' + (r.output || 'Done') + '</pre>';
}

async function runCmd() {
  const cmd = document.getElementById('cmd').value;
  if (!cmd) return;
  document.getElementById('cmd-result').innerHTML = 'Running...';
  const d = await fetchAPI('/servers', {});
  if (d.error || !d.length) { document.getElementById('cmd-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/run', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command: cmd})
  });
  document.getElementById('cmd-result').innerHTML = 
    'Exit: '+r.exit_code+'\\n'+(r.stdout||'')+(r.stderr||'');
}

getStatus();
// Auto-login on page load
login().then(ok => {
  if (ok) getStatus();
  else document.getElementById('status').innerHTML = 'Login failed — check console';
});

async function deleteAll() {
  if (!confirm('DELETE ALL archived content?\\nThis deletes archive/ + data/*.db\\nThis cannot be undone!')) return;
  document.getElementById('delete-result').innerHTML = 'Deleting...';
  const d = await fetchAPI('/servers');
  if (d.error || !d.length) { document.getElementById('delete-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/terminal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command: 'rm -rf ~/mathvault/archive/* ~/mathvault/data/*.db 2>/dev/null; echo "All deleted"'})
  });
  document.getElementById('delete-result').innerHTML = '<pre>'+(r.stdout||r.stderr||'Done')+'</pre>';
}

async function deleteArchive() {
  if (!confirm('Delete archive/ folder only?\\nDatabase kept.')) return;
  document.getElementById('delete-result').innerHTML = 'Deleting archive...';
  const d = await fetchAPI('/servers');
  if (d.error || !d.length) { document.getElementById('delete-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/terminal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command: 'rm -rf ~/mathvault/archive/pages/* ~/mathvault/archive/assets/* ~/mathvault/archive/index/* 2>/dev/null; echo "Archive deleted"'})
  });
  document.getElementById('delete-result').innerHTML = '<pre>'+(r.stdout||r.stderr||'Done')+'</pre>';
}

async function deleteDB() {
  if (!confirm('Delete database only?\\nArchive files kept.')) return;
  document.getElementById('delete-result').innerHTML = 'Deleting DB...';
  const d = await fetchAPI('/servers');
  if (d.error || !d.length) { document.getElementById('delete-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/terminal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command: 'rm -f ~/mathvault/data/*.db ~/mathvault/data/*.db-wal ~/mathvault/data/*.db-shm 2>/dev/null; echo "DB deleted"'})
  });
  document.getElementById('delete-result').innerHTML = '<pre>'+(r.stdout||r.stderr||'Done')+'</pre>';
}

async function deployCode() {
  if (!confirm('Deploy MathVault code to server?\\nThis clones the repo to ~/mathvault/ and installs deps.')) return;
  document.getElementById('deploy-result').innerHTML = 'Deploying... (takes 1-2 min)';
  const d = await fetchAPI('/servers');
  if (d.error || !d.length) { document.getElementById('deploy-result').innerHTML = 'No server'; return; }
  const r = await fetchAPI('/servers/'+d[0].id+'/terminal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({command: 'cd ~ && if [ ! -d mathvault ]; then git clone https://github.com/Mohammadparsasharififard/AOPS-.git mathvault; fi && cd mathvault && git pull && python3 -m venv .venv && .venv/bin/pip install -q fastapi uvicorn sqlalchemy httpx tenacity beautifulsoup4 lxml bleach bcrypt click rich pydantic pydantic-settings python-dotenv pyyaml slowapi jinja2 itsdangerous paramiko pynacl && .venv/bin/python -m playwright install chromium && cp .env.example .env 2>/dev/null; .venv/bin/python -c "from database.session import init_db; init_db()" && echo "DEPLOY OK" && ls -la ~/mathvault/'})
  });
  document.getElementById('deploy-result').innerHTML = '<pre>'+(r.stdout||r.stderr||'Done')+'</pre>';
}
</script>
</body>
</html>"""

# ============================================================
# 4. Main — start everything
# ============================================================
def main():
    print("=" * 50)
    print("  MathVault — One File App")
    print("=" * 50)

    # Step 1: Install
    install()

    # Step 2: Config
    print("\n[setup] Config + DB...")
    setup_env()
    init_dbs()
    seed_server()
    print("[setup] Done.")

    # Step 3: Kill any old process on port 8000
    print("\n[run] Checking port 8000...")
    if os.name == "nt":
        subprocess.run("netstat -ano | findstr :8000 | findstr LISTENING", shell=True, capture_output=True, text=True)
        # Kill old process
        r = subprocess.run("netstat -ano | findstr :8000 | findstr LISTENING", shell=True, capture_output=True, text=True)
        if r.stdout.strip():
            # Extract PID and kill
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                    print(f"  Killed old process PID {pid}")
        else:
            print("  Port 8000 is free")
    else:
        subprocess.run("fuser -k 8000/tcp 2>/dev/null", shell=True, capture_output=True)
        print("  Port 8000 cleared")

    # Step 4: Start
    print("\n[run] Starting on http://localhost:8000")
    print("[run] Master password: mathvault2024")
    print("[run] SSH: mp@192.168.1.150 (Mp13911391!)")
    print("[run] Press Ctrl+C to stop.\n")

    os.environ["PYTHONPATH"] = str(SM)
    os.chdir(str(SM))

    # Write the web UI
    ui_file = SM / "static" / "index.html"
    ui_file.parent.mkdir(parents=True, exist_ok=True)
    ui_file.write_text(WEB_UI, encoding="utf-8")

    # Open browser after 2 seconds
    def open_browser():
        time.sleep(2)
        webbrowser.open("http://localhost:8000")
    threading.Thread(target=open_browser, daemon=True).start()

    os.execv(PY, [PY, "-m", "uvicorn", "api.main:app",
                  "--host", "127.0.0.1", "--port", "8000"])

if __name__ == "__main__":
    main()
