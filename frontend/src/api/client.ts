import type { SessionCreated } from './types';

const BASE = '/api/v1';
const TOKEN_KEY = 'pcc.anon_token';

/** Ошибка API. Бэкенд отвечает {"detail": {"code", "message"}}, а при ошибке валидации {"detail": [...]}. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type Query = Record<string, string | number | boolean | undefined | null>;

function toQueryString(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // не JSON (например, 502 от nginx)
  }
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && 'code' in detail) {
    const d = detail as { code: string; message?: string };
    return new ApiError(res.status, d.code, d.message ?? 'Ошибка запроса', detail);
  }
  if (Array.isArray(detail)) {
    return new ApiError(res.status, 'validation_error', 'Некорректные данные запроса', detail);
  }
  const message = res.status >= 500 ? 'Сервер недоступен, попробуйте позже' : 'Ошибка запроса';
  return new ApiError(res.status, `http_${res.status}`, message);
}

// localStorage может быть недоступен (приватный режим, запрет cookies)
function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function writeToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // токен проживёт только до перезагрузки страницы
  }
}

let memoryToken: string | null = null;
let pendingSession: Promise<string> | null = null;

async function createSession(): Promise<string> {
  const res = await fetch(`${BASE}/session`, { method: 'POST', headers: { Accept: 'application/json' } });
  if (!res.ok) throw await toApiError(res);
  const data = (await res.json()) as SessionCreated;
  memoryToken = data.anon_token;
  writeToken(data.anon_token);
  return data.anon_token;
}

/** Возвращает токен гостя, при необходимости создаёт сессию. Параллельные вызовы получают одну сессию. */
export function ensureToken(): Promise<string> {
  const token = memoryToken ?? readToken();
  if (token) return Promise.resolve(token);
  pendingSession ??= createSession().finally(() => {
    pendingSession = null;
  });
  return pendingSession;
}

function resetToken(): void {
  memoryToken = null;
  writeToken(null);
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  query?: Query;
  auth?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const send = (token?: string) => {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    return fetch(`${BASE}${path}${toQueryString(opts.query)}`, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  };

  let res = await send(opts.auth ? await ensureToken() : undefined);
  // Токен истёк или удалён из БД: заводим новую сессию и повторяем запрос один раз.
  // Сборки старой сессии при этом недоступны, это ожидаемое поведение гостевого режима.
  if (opts.auth && res.status === 401) {
    resetToken();
    res = await send(await ensureToken());
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
