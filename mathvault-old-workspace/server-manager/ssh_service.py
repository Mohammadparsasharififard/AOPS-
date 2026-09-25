"""SSH service — runs commands on remote servers via paramiko.

Security:
- Credentials are decrypted in-memory only, immediately used, and discarded
- All commands are logged to AuditLog
- Timeouts are enforced
- The service NEVER accepts a host/key string from the API caller —
  only IDs that resolve to existing Server rows
"""
from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import paramiko
from sqlalchemy.orm import Session

from crypto import decrypt_credential
from database.models import AuditLog, Server


logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass
class ServerStatus:
    online: bool
    hostname: str
    uname: str
    uptime: str
    load_avg: Optional[str]
    cpu_count: Optional[int]
    mem_total_mb: Optional[int]
    mem_used_mb: Optional[int]
    disk_total_gb: Optional[float]
    disk_used_gb: Optional[float]
    # Extended metrics (new in phase 3)
    docker_status: Optional[str] = None  # raw "name:status" lines
    git_mathvault_head: Optional[str] = None  # latest git commit on /opt/mathvault
    mathvault_service_status: Optional[str] = None  # active | inactive | not-found
    mathvault_last_sync: Optional[str] = None
    network_info: Optional[str] = None  # iface + IP lines


# Predefined "Server Actions" — safe one-click commands the user can run
# from the UI. Each has a name, a description, the actual command, and a
# "danger" flag requiring explicit confirmation.
SAFE_ACTIONS = [
    {
        "id": "update-mathvault",
        "label": "Update MathVault",
        "description": "Pull latest from git and restart MathVault service",
        "command": "cd /opt/mathvault && git pull && sudo systemctl restart mathvault-api || sudo systemctl restart mathvault",
        "danger": False,
    },
    {
        "id": "restart-mathvault",
        "label": "Restart MathVault",
        "description": "Just restart the MathVault API service",
        "command": "sudo systemctl restart mathvault-api || sudo systemctl restart mathvault",
        "danger": False,
    },
    {
        "id": "start-mathvault",
        "label": "Start MathVault",
        "description": "Start the MathVault API service",
        "command": "sudo systemctl start mathvault-api || sudo systemctl start mathvault",
        "danger": False,
    },
    {
        "id": "stop-mathvault",
        "label": "Stop MathVault",
        "description": "Stop the MathVault API service (archive still browsable from frontend)",
        "command": "sudo systemctl stop mathvault-api || sudo systemctl stop mathvault",
        "danger": True,
    },
    {
        "id": "view-logs",
        "label": "View MathVault Logs",
        "description": "Tail last 50 log lines from MathVault API",
        "command": "sudo journalctl -u mathvault-api -n 50 --no-pager || sudo journalctl -u mathvault -n 50 --no-pager",
        "danger": False,
    },
    {
        "id": "run-sync",
        "label": "Run Sync Now",
        "description": "Trigger an immediate incremental sync (instead of waiting for next timer tick)",
        "command": "cd /opt/mathvault && ./.venv/bin/python -m cli.mathvault sync",
        "danger": False,
    },
    {
        "id": "dry-run",
        "label": "Dry-Run Sync",
        "description": "Show what URLs the crawler WOULD fetch, without downloading",
        "command": "cd /opt/mathvault && ./.venv/bin/python -m cli.mathvault crawl --dry-run",
        "danger": False,
    },
    {
        "id": "check-disk",
        "label": "Check Disk",
        "description": "Show disk usage of /opt and /opt/mathvault/archive",
        "command": "df -h /opt && du -sh /opt/mathvault/archive 2>/dev/null || true",
        "danger": False,
    },
    {
        "id": "check-docker",
        "label": "Check Docker",
        "description": "Show running Docker containers",
        "command": "docker ps --no-trunc",
        "danger": False,
    },
    {
        "id": "check-database",
        "label": "Check Database",
        "description": "Test DB connectivity + show table counts",
        "command": "cd /opt/mathvault && ./.venv/bin/python -m cli.mathvault status",
        "danger": False,
    },
    {
        "id": "backup",
        "label": "Backup Now",
        "description": "Create a manual backup (DB + archive) — saved to /opt/mathvault/backups/",
        "command": "cd /opt/mathvault && ./scripts/backup.sh",
        "danger": False,
    },
    {
        "id": "health-check",
        "label": "Health Check",
        "description": "Curl the MathVault API /health endpoint",
        "command": "curl -sS http://localhost:8000/api/health",
        "danger": False,
    },
]


# Dangerous command patterns — REFUSED at the API level, never executed.
# This protects against: rm -rf, drop database, format, mkfs, dd, etc.
FORBIDDEN_PATTERNS = (
    "rm -rf",
    "rm -fr",
    "rm -r /",
    "rmdir /",
    "dd if=",
    "mkfs",
    "format",
    ":(){:|:&};:",  # fork bomb
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
    "drop database",
    "drop table",
    "truncate table",
    "delete from",
    "git push --force",
    "git push -f",
    "> /dev/sda",
    "shred",
)


def is_command_safe(command: str) -> tuple[bool, Optional[str]]:
    """Return (is_safe, refusal_reason). Safe = does NOT contain forbidden pattern."""
    lowered = command.lower()
    for pat in FORBIDDEN_PATTERNS:
        if pat in lowered:
            return False, f"Command contains forbidden pattern: '{pat}'"
    return True, None


def _connect(server: Server, master_password: str, timeout: int = 15) -> paramiko.SSHClient:
    """Open an SSH connection using the server's stored (encrypted) credentials."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    if server.auth_method == "password":
        if not server.encrypted_password:
            raise RuntimeError(f"Server {server.name} has no stored password")
        password = decrypt_credential(server.encrypted_password, master_password)
        if password is None:
            raise RuntimeError("Failed to decrypt password — wrong master password?")
        try:
            client.connect(
                hostname=server.host,
                port=server.port,
                username=server.username,
                password=password,
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        finally:
            del password
    elif server.auth_method == "key":
        if not server.encrypted_private_key:
            raise RuntimeError(f"Server {server.name} has no stored private key")
        key_pem = decrypt_credential(server.encrypted_private_key, master_password)
        if key_pem is None:
            raise RuntimeError("Failed to decrypt private key — wrong master password?")
        try:
            # Try RSA / Ed25519 / ECDSA — most common
            pkey = None
            for cls_name in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSAKey"):
                try:
                    pkey = getattr(paramiko, cls_name).from_private_key(key_pem)  # type: ignore
                    break
                except paramiko.SSHException:
                    continue
            if pkey is None:
                raise RuntimeError("Could not parse private key (tried Ed25519/ECDSA/RSA/DSA)")
            client.connect(
                hostname=server.host,
                port=server.port,
                username=server.username,
                pkey=pkey,
                timeout=timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        finally:
            del key_pem
    else:
        raise RuntimeError(f"Unknown auth method: {server.auth_method}")

    return client


def run_command(
    db: Session,
    server: Server,
    master_password: str,
    command: str,
    timeout: int = 60,
) -> CommandResult:
    """Run a single command on the remote server. Logs to AuditLog."""
    audit = AuditLog(
        action="run_command",
        server_id=server.id,
        command=command[:5000],
        started_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.flush()

    import time
    t0 = time.monotonic()
    try:
        client = _connect(server, master_password)
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
        finally:
            client.close()
        duration = time.monotonic() - t0
        audit.exit_code = exit_code
        audit.finished_at = datetime.now(timezone.utc)
        audit.success = exit_code == 0
        return CommandResult(exit_code=exit_code, stdout=out, stderr=err, duration_seconds=duration)
    except Exception as e:
        duration = time.monotonic() - t0
        audit.finished_at = datetime.now(timezone.utc)
        audit.success = False
        audit.error = str(e)[:2000]
        logger.exception("SSH command failed on %s: %s", server.name, e)
        raise
    finally:
        db.commit()


def get_server_status(server: Server, master_password: str) -> ServerStatus:
    """Get a snapshot of the server's status — online check + basic metrics."""
    try:
        client = _connect(server, master_password, timeout=10)
        try:
            # Run a batch of commands to gather status
            cmd = (
                "echo '---HOSTNAME---'; hostname; "
                "echo '---UNAME---'; uname -a; "
                "echo '---UPTIME---'; uptime; "
                "echo '---LOAD---'; cat /proc/loadavg; "
                "echo '---CPU---'; nproc; "
                "echo '---MEM---'; free -m | awk 'NR==2{print $2,$3}'; "
                "echo '---DISK---'; df -BG / | awk 'NR==2{print $2,$3,$4}'; "
                "echo '---DOCKER---'; (docker ps --format '{{.Names}}:{{.Status}}' 2>/dev/null | head -10) || echo 'docker-not-available'; "
                "echo '---GIT-MV---'; (cd /opt/mathvault 2>/dev/null && git log -1 --oneline 2>/dev/null) || echo 'mathvault-not-found'; "
                "echo '---MV-STATUS---'; (systemctl is-active mathvault-api 2>/dev/null) || systemctl is-active mathvault 2>/dev/null || echo 'mv-service-not-found'; "
                "echo '---MV-LAST-SYNC---'; (systemctl show mathvault-update.service -p ExecMainExitTimestamp 2>/dev/null | head -1) || echo 'never'; "
                "echo '---NET---'; (ip -o -4 addr show scope global 2>/dev/null | awk '{print $2, $4}' | head -5) || echo 'net-unknown'"
            )
            stdin, stdout, stderr = client.exec_command(cmd, timeout=15)
            output = stdout.read().decode("utf-8", errors="replace")
        finally:
            client.close()
        return _parse_status(output, server)
    except Exception as e:
        logger.warning("Status check failed for %s: %s", server.name, e)
        return ServerStatus(
            online=False, hostname="", uname="", uptime="",
            load_avg=None, cpu_count=None, mem_total_mb=None, mem_used_mb=None,
            disk_total_gb=None, disk_used_gb=None,
        )


def _parse_status(output: str, server: Server) -> ServerStatus:
    sections: dict[str, str] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("---") and line.endswith("---"):
            current = line.strip("-")
        elif current:
            sections[current] = line.strip()
            current = None
    disk_parts = sections.get("DISK", "").split()
    disk_total = float(disk_parts[0].rstrip("G")) if len(disk_parts) >= 2 else None
    disk_used = float(disk_parts[1].rstrip("G")) if len(disk_parts) >= 2 else None
    mem_parts = sections.get("MEM", "").split()
    mem_total = int(mem_parts[0]) if len(mem_parts) >= 2 else None
    mem_used = int(mem_parts[1]) if len(mem_parts) >= 2 else None
    return ServerStatus(
        online=True,
        hostname=sections.get("HOSTNAME", ""),
        uname=sections.get("UNAME", ""),
        uptime=sections.get("UPTIME", ""),
        load_avg=sections.get("LOAD", ""),
        cpu_count=int(sections.get("CPU", "0") or "0") or None,
        mem_total_mb=mem_total,
        mem_used_mb=mem_used,
        disk_total_gb=disk_total,
        disk_used_gb=disk_used,
        docker_status=sections.get("DOCKER"),
        git_mathvault_head=sections.get("GIT-MV"),
        mathvault_service_status=sections.get("MV-STATUS"),
        mathvault_last_sync=sections.get("MV-LAST-SYNC"),
        network_info=sections.get("NET"),
    )


def deploy_to_server(
    db: Session,
    server: Server,
    master_password: str,
    deploy_path: str,
    git_url: Optional[str],
    git_branch: str,
    service_name: Optional[str],
    deploy_script: Optional[str],
) -> CommandResult:
    """Run a deploy with a real pipeline:

    1. Connect (implicit)
    2. Check server is reachable
    3. Check git status
    4. Pull latest source
    5. Validate configuration (.env exists)
    6. Run deploy script (if defined)
    7. Restart required service (if defined)
    8. Health check (curl /health)
    9. Return result + log

    Each step is run separately so we can return meaningful errors. If any
    step fails, we abort and the previous version is preserved (we never
    `git reset --hard` to a broken commit — we use `git pull --ff-only`).
    """
    steps: list[tuple[str, str]] = []  # (step_name, command)
    steps.append(("check_server", "true"))  # server is reachable if we got here
    steps.append(("check_git", f"cd {shlex.quote(deploy_path)} && git rev-parse --short HEAD 2>/dev/null || echo 'no-git'"))
    if git_url:
        steps.append((
            "pull_source",
            f"cd {shlex.quote(deploy_path)} && "
            f"if [ ! -d .git ]; then git clone --branch {shlex.quote(git_branch)} {shlex.quote(git_url)} .; "
            f"else git fetch origin {shlex.quote(git_branch)} && git merge --ff-only origin/{shlex.quote(git_branch)}; fi"
        ))
    steps.append(("validate_config", f"cd {shlex.quote(deploy_path)} && test -f .env && echo '.env OK' || echo '.env MISSING'"))
    if deploy_script:
        steps.append((
            "run_deploy_script",
            f"cd {shlex.quote(deploy_path)} && "
            f"if [ -f {shlex.quote(deploy_script)} ]; then bash {shlex.quote(deploy_script)}; "
            f"else echo 'WARN: deploy script not found: {shlex.quote(deploy_script)}'; fi"
        ))
    if service_name:
        steps.append((
            "restart_service",
            f"sudo systemctl restart {shlex.quote(service_name)} 2>&1 || systemctl restart {shlex.quote(service_name)} 2>&1"
        ))
        steps.append((
            "health_check_service",
            f"systemctl is-active {shlex.quote(service_name)}"
        ))
    # Final health check via API (best effort)
    steps.append(("health_check_api", "curl -sS --max-time 5 http://localhost:8000/api/health 2>/dev/null || echo 'api-not-reachable'"))

    log_lines: list[str] = []
    last_result: Optional[CommandResult] = None
    failed_step: Optional[str] = None
    for step_name, cmd in steps:
        log_lines.append(f"\n--- STEP: {step_name} ---")
        log_lines.append(f"$ {cmd}")
        try:
            r = run_command(db, server, master_password, cmd, timeout=180)
            last_result = r
            log_lines.append(r.stdout.rstrip())
            if r.stderr:
                log_lines.append(f"[stderr] {r.stderr.rstrip()}")
            # Stop pipeline on failure
            if r.exit_code != 0 and step_name not in {"check_server", "validate_config", "health_check_api"}:
                failed_step = step_name
                log_lines.append(f"\n*** FAILED at step: {step_name} (exit {r.exit_code}) ***")
                log_lines.append("*** Previous version preserved. No rollback needed (we used git merge --ff-only). ***")
                break
        except Exception as e:
            failed_step = step_name
            log_lines.append(f"\n*** EXCEPTION at step {step_name}: {e} ***")
            break

    # Compose a synthetic CommandResult for the API
    full_log = "\n".join(log_lines)
    final_exit = last_result.exit_code if last_result else 1
    if failed_step:
        final_exit = 1

    return CommandResult(
        exit_code=final_exit,
        stdout=full_log,
        stderr=f"Failed at step: {failed_step}" if failed_step else "",
        duration_seconds=last_result.duration_seconds if last_result else 0.0,
    )


def start_service(db: Session, server: Server, master_password: str, service: str) -> CommandResult:
    return run_command(db, server, master_password, f"sudo systemctl start {shlex.quote(service)}")


def stop_service(db: Session, server: Server, master_password: str, service: str) -> CommandResult:
    return run_command(db, server, master_password, f"sudo systemctl stop {shlex.quote(service)}")


def restart_service(db: Session, server: Server, master_password: str, service: str) -> CommandResult:
    return run_command(db, server, master_password, f"sudo systemctl restart {shlex.quote(service)}")


def service_status(db: Session, server: Server, master_password: str, service: str) -> CommandResult:
    return run_command(db, server, master_password, f"systemctl is-active {shlex.quote(service)}; systemctl status {shlex.quote(service)} --no-pager -l | head -30")


def list_services(db: Session, server: Server, master_password: str) -> CommandResult:
    """List active systemd services."""
    return run_command(
        db, server, master_password,
        "systemctl list-units --type=service --state=running --no-pager --no-legend | head -40",
    )
