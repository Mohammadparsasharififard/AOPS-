async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "include" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function apiPost<T>(path: string, body?: any): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function apiPut<T>(path: string, body?: any): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "include",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export interface Server {
  id: string;
  name: string;
  host: string;
  port: number;
  username: string;
  auth_method: string;
  notes?: string | null;
  last_seen_at?: string | null;
  last_status?: string | null;
  created_at?: string;
}

export interface Deployment {
  id: string;
  name: string;
  deploy_path: string;
  git_url?: string | null;
  git_branch: string;
  service_name?: string | null;
  deploy_script?: string | null;
  last_deployed_at?: string | null;
  last_deploy_status?: string | null;
}

export interface ServerStatus {
  online: boolean;
  hostname: string;
  uname: string;
  uptime: string;
  load_avg?: string | null;
  cpu_count?: number | null;
  mem_total_mb?: number | null;
  mem_used_mb?: number | null;
  disk_total_gb?: number | null;
  disk_used_gb?: number | null;
}

export interface AuditEntry {
  id: string;
  action: string;
  server_id?: string | null;
  deployment_id?: string | null;
  command?: string | null;
  exit_code?: number | null;
  started_at: string;
  finished_at?: string | null;
  success: boolean;
  error?: string | null;
}

export const api = {
  auth: {
    status: () => apiGet<{ setup_required: boolean; authenticated: boolean; server_count: number }>("/auth/status"),
    setup: (pw: string) => apiPost("/auth/setup", { master_password: pw }),
    login: (pw: string) => apiPost("/auth/login", { master_password: pw }),
    logout: () => apiPost("/auth/logout"),
  },
  servers: {
    list: () => apiGet<Server[]>("/servers"),
    get: (id: string) => apiGet<Server & { deployments: Deployment[] }>(`/servers/${id}`),
    create: (data: any) => apiPost<Server>("/servers", data),
    update: (id: string, data: any) => apiPut<Server>(`/servers/${id}`, data),
    delete: (id: string) => apiDelete<{ status: string }>(`/servers/${id}`),
    status: (id: string) => apiGet<ServerStatus>(`/servers/${id}/status`),
    test: (id: string) => apiPost<{ ok: boolean; hostname?: string; error?: string }>(`/servers/${id}/test`),
    run: (id: string, command: string) => apiPost<{ exit_code: number; stdout: string; stderr: string; duration_seconds: number }>(`/servers/${id}/run`, { command }),
    services: (id: string) => apiGet<{ output: string; exit_code: number }>(`/servers/${id}/services`),
    serviceAction: (id: string, name: string, action: string) =>
      apiPost<{ exit_code: number; stdout: string; stderr: string }>(`/servers/${id}/services/${name}/${action}`),
    createDeployment: (id: string, data: any) => apiPost(`/servers/${id}/deployments`, data),
    runDeployment: (id: string, depId: string) => apiPost<{ exit_code: number; stdout: string; stderr: string; duration_seconds: number }>(`/servers/${id}/deployments/${depId}/run`),
  },
  audit: {
    list: (limit = 50) => apiGet<AuditEntry[]>(`/audit?limit=${limit}`),
  },
  archive: {
    offlineUrl: () => apiGet<{ frontend_url: string; api_url: string }>("/archive/offline-url"),
  },
};
