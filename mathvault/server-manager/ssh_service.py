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
                "echo '---DISK---'; df -BG / | awk 'NR==2{print $2,$3,$4}'"
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
    sections = {}
    current = None
    for line in output.splitlines():
        if line.startswith("---") and line.endswith("---"):
            current = line.strip("-")
        elif current:
            sections[current] = line.strip()
            current = None
    # Parse disk "60G 30G 30G" → total=60, used=30
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
    """Run a deploy: git pull (or clone) + optional deploy script + optional service restart.

    Returns the result of the last command (or the failure).
    """
    # Build the deploy sequence
    cmds = []
    # Ensure directory exists (clone if missing)
    cmds.append(f"mkdir -p {shlex.quote(deploy_path)}")
    if git_url:
        cmds.append(
            f"if [ ! -d {shlex.quote(deploy_path + '/.git')} ]; then "
            f"git clone --branch {shlex.quote(git_branch)} {shlex.quote(git_url)} {shlex.quote(deploy_path)}; "
            f"else cd {shlex.quote(deploy_path)} && git fetch --all && git reset --hard origin/{shlex.quote(git_branch)}; fi"
        )
    if deploy_script:
        cmds.append(
            f"cd {shlex.quote(deploy_path)} && "
            f"if [ -f {shlex.quote(deploy_script)} ]; then "
            f"bash {shlex.quote(deploy_script)}; "
            f"else echo 'deploy script not found: {shlex.quote(deploy_script)}'; fi"
        )
    if service_name:
        # Use sudo for service control — assumes passwordless sudo (typical for personal server)
        cmds.append(f"sudo systemctl restart {shlex.quote(service_name)} || systemctl restart {shlex.quote(service_name)}")
        cmds.append(f"systemctl is-active {shlex.quote(service_name)}")

    full_cmd = " && ".join(cmds)
    return run_command(db, server, master_password, full_cmd, timeout=300)


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
