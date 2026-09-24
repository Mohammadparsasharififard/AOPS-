"""Server routes — CRUD, status, deploy, run commands."""
from __future__ import annotations

import shlex
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import SESSION_COOKIE_NAME, require_session
from config import get_settings
from crypto import encrypt_credential
from database.models import AuditLog, Deployment, Server
from database.session import get_db, session_scope
import ssh_service


router = APIRouter()


# --- Helpers ----------------------------------------------------------------

def _get_master_password(request: Request) -> str:
    """Retrieve master password from in-memory cache (set at login)."""
    from api.routes.auth import get_cached_master_password
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Not authenticated")
    pw = get_cached_master_password(token)
    if pw is None:
        raise HTTPException(401, "Session expired — please log in again")
    return pw


def _server_to_dict(s: Server) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "host": s.host,
        "port": s.port,
        "username": s.username,
        "auth_method": s.auth_method,
        "notes": s.notes,
        "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None,
        "last_status": s.last_status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# --- CRUD -------------------------------------------------------------------

class ServerCreate(BaseModel):
    name: str
    host: str
    port: int = 22
    username: str = "root"
    auth_method: str = "password"  # password | key
    password: Optional[str] = None
    private_key: Optional[str] = None
    notes: Optional[str] = None


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    notes: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None


@router.get("", dependencies=[Depends(require_session)])
async def list_servers(db: Session = Depends(get_db)) -> list[dict]:
    servers = db.execute(select(Server).order_by(Server.name)).scalars().all()
    return [_server_to_dict(s) for s in servers]


@router.post("", dependencies=[Depends(require_session)])
async def create_server(req: ServerCreate, request: Request, db: Session = Depends(get_db)) -> dict:
    if req.auth_method == "password" and not req.password:
        raise HTTPException(400, "Password required for password auth")
    if req.auth_method == "key" and not req.private_key:
        raise HTTPException(400, "Private key required for key auth")

    server = Server(
        name=req.name, host=req.host, port=req.port, username=req.username,
        auth_method=req.auth_method, notes=req.notes,
    )
    if req.password:
        server.encrypted_password = encrypt_credential(req.password)
    if req.private_key:
        server.encrypted_private_key = encrypt_credential(req.private_key)
    db.add(server)
    db.commit()
    db.refresh(server)
    return _server_to_dict(server)


@router.get("/{server_id}", dependencies=[Depends(require_session)])
async def get_server(server_id: str, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    result = _server_to_dict(s)
    result["deployments"] = [
        {
            "id": d.id,
            "name": d.name,
            "deploy_path": d.deploy_path,
            "git_url": d.git_url,
            "git_branch": d.git_branch,
            "service_name": d.service_name,
            "deploy_script": d.deploy_script,
            "last_deployed_at": d.last_deployed_at.isoformat() if d.last_deployed_at else None,
            "last_deploy_status": d.last_deploy_status,
        }
        for d in s.deployments
    ]
    return result


@router.put("/{server_id}", dependencies=[Depends(require_session)])
async def update_server(server_id: str, req: ServerUpdate, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    if req.name is not None: s.name = req.name
    if req.host is not None: s.host = req.host
    if req.port is not None: s.port = req.port
    if req.username is not None: s.username = req.username
    if req.notes is not None: s.notes = req.notes
    if req.password is not None:
        s.encrypted_password = encrypt_credential(req.password)
        s.auth_method = "password"
    if req.private_key is not None:
        s.encrypted_private_key = encrypt_credential(req.private_key)
        s.auth_method = "key"
    db.commit()
    db.refresh(s)
    return _server_to_dict(s)


@router.delete("/{server_id}", dependencies=[Depends(require_session)])
async def delete_server(server_id: str, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    db.delete(s)
    db.commit()
    return {"status": "deleted"}


@router.get("/{server_id}/status", dependencies=[Depends(require_session)])
async def get_status(server_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    pw = _get_master_password(request)
    status = ssh_service.get_server_status(s, pw)
    # Update last-seen
    s.last_seen_at = datetime.now(timezone.utc)
    s.last_status = "online" if status.online else "offline"
    db.commit()
    return {
        "online": status.online,
        "hostname": status.hostname,
        "uname": status.uname,
        "uptime": status.uptime,
        "load_avg": status.load_avg,
        "cpu_count": status.cpu_count,
        "mem_total_mb": status.mem_total_mb,
        "mem_used_mb": status.mem_used_mb,
        "disk_total_gb": status.disk_total_gb,
        "disk_used_gb": status.disk_used_gb,
    }


@router.post("/{server_id}/test", dependencies=[Depends(require_session)])
async def test_connection(server_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    pw = _get_master_password(request)
    try:
        status = ssh_service.get_server_status(s, pw)
        return {"ok": status.online, "hostname": status.hostname, "uname": status.uname}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Deployments ------------------------------------------------------------

class DeploymentCreate(BaseModel):
    name: str
    deploy_path: str
    git_url: Optional[str] = None
    git_branch: str = "main"
    service_name: Optional[str] = None
    deploy_script: Optional[str] = None


@router.post("/{server_id}/deployments", dependencies=[Depends(require_session)])
async def create_deployment(server_id: str, req: DeploymentCreate, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    d = Deployment(
        server_id=server_id, name=req.name, deploy_path=req.deploy_path,
        git_url=req.git_url, git_branch=req.git_branch,
        service_name=req.service_name, deploy_script=req.deploy_script,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return {
        "id": d.id, "name": d.name, "deploy_path": d.deploy_path,
        "git_url": d.git_url, "git_branch": d.git_branch,
        "service_name": d.service_name, "deploy_script": d.deploy_script,
    }


@router.post("/{server_id}/deployments/{dep_id}/run", dependencies=[Depends(require_session)])
async def run_deployment(server_id: str, dep_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    d = db.get(Deployment, dep_id)
    if not d or d.server_id != server_id:
        raise HTTPException(404, "Deployment not found")
    pw = _get_master_password(request)
    try:
        result = ssh_service.deploy_to_server(
            db=db, server=s, master_password=pw,
            deploy_path=d.deploy_path, git_url=d.git_url,
            git_branch=d.git_branch, service_name=d.service_name,
            deploy_script=d.deploy_script,
        )
        d.last_deployed_at = datetime.now(timezone.utc)
        d.last_deploy_status = "success" if result.exit_code == 0 else "failed"
        d.last_deploy_log = (result.stdout + "\n" + result.stderr).strip()[:5000]
        db.commit()
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as e:
        d.last_deployed_at = datetime.now(timezone.utc)
        d.last_deploy_status = "failed"
        d.last_deploy_log = str(e)[:5000]
        db.commit()
        raise HTTPException(500, f"Deploy failed: {e}")


# --- Run command ------------------------------------------------------------

class RunCommandRequest(BaseModel):
    command: str


@router.post("/{server_id}/run", dependencies=[Depends(require_session)])
async def run_command(server_id: str, req: RunCommandRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    """Run an arbitrary shell command on the server."""
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    pw = _get_master_password(request)
    try:
        result = ssh_service.run_command(db, s, pw, req.command, timeout=60)
        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as e:
        raise HTTPException(500, f"Command failed: {e}")


# --- Services ---------------------------------------------------------------

@router.get("/{server_id}/services", dependencies=[Depends(require_session)])
async def list_services(server_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    pw = _get_master_password(request)
    result = ssh_service.list_services(db, s, pw)
    return {"output": result.stdout, "exit_code": result.exit_code}


@router.post("/{server_id}/services/{name}/{action}", dependencies=[Depends(require_session)])
async def service_action(server_id: str, name: str, action: str, request: Request, db: Session = Depends(get_db)) -> dict:
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    pw = _get_master_password(request)
    if action == "start":
        result = ssh_service.start_service(db, s, pw, name)
    elif action == "stop":
        result = ssh_service.stop_service(db, s, pw, name)
    elif action == "restart":
        result = ssh_service.restart_service(db, s, pw, name)
    elif action == "status":
        result = ssh_service.service_status(db, s, pw, name)
    else:
        raise HTTPException(400, f"Unknown action: {action}")
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
