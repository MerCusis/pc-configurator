import { request } from './client';
import type {
  Build, BuildIn, BuildList, Category, CheckResult, Health, ItemIn,
  Manufacturer, Page, Part, PartsQuery, SessionInfo, ShareResult,
} from './types';

const id = (v: string | number) => encodeURIComponent(String(v));

export const api = {
  /** /health отвечает 503 с тем же JSON, если БД или Redis недоступны, поэтому без request(). */
  async health(signal?: AbortSignal): Promise<Health> {
    const res = await fetch('/api/v1/health', { signal });
    return (await res.json()) as Health;
  },

  session: () => request<SessionInfo>('/session', { auth: true }),

  categories: (signal?: AbortSignal) => request<Category[]>('/categories', { signal }),
  manufacturers: (category?: string, signal?: AbortSignal) =>
    request<Manufacturer[]>('/manufacturers', { query: { category }, signal }),
  parts: (query: PartsQuery = {}, signal?: AbortSignal) =>
    request<Page<Part>>('/parts', { query, signal }),
  part: (partId: number, signal?: AbortSignal) => request<Part>(`/parts/${id(partId)}`, { signal }),

  check: (items: ItemIn[], signal?: AbortSignal) =>
    request<CheckResult>('/compatibility/check', { method: 'POST', body: { items }, signal }),

  builds: () => request<BuildList>('/builds', { auth: true }),
  build: (buildId: string) => request<Build>(`/builds/${id(buildId)}`, { auth: true }),
  createBuild: (data: BuildIn) => request<Build>('/builds', { method: 'POST', body: data, auth: true }),
  updateBuild: (buildId: string, data: BuildIn) =>
    request<Build>(`/builds/${id(buildId)}`, { method: 'PUT', body: data, auth: true }),
  deleteBuild: (buildId: string) => request<void>(`/builds/${id(buildId)}`, { method: 'DELETE', auth: true }),

  share: (buildId: string) => request<ShareResult>(`/builds/${id(buildId)}/share`, { method: 'POST', auth: true }),
  unshare: (buildId: string) =>
    request<void>(`/builds/${id(buildId)}/share`, { method: 'DELETE', auth: true }),
  shared: (slug: string) => request<Build>(`/shared/${id(slug)}`),
};
