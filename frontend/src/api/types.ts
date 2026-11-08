// Типы ответов API. Сверены с samples.json (backend 0.1.0).
// Деньги приходят строкой ("9990.00"): Decimal не теряет точность. Для вывода есть *_display.

export type Money = string;
export type IsoDate = string;
export type Severity = 'error' | 'warning';

export interface Health {
  status: 'ok' | 'degraded';
  db: boolean;
  redis: boolean;
  version: string;
}

export interface SessionCreated {
  anon_token: string;
  token_type: 'bearer';
  expires_at: IsoDate;
  builds_limit: number;
}

export interface SessionInfo {
  expires_at: IsoDate;
  builds_count: number;
  builds_limit: number;
}

export interface Category {
  slug: string;
  name: string;
  is_required: boolean;
  max_items: number;
  part_count: number;
}

export interface Manufacturer {
  slug: string;
  name: string;
  part_count: number;
}

export interface SpecDisplay {
  key: string;
  label: string;
  value: string;
  missing: boolean;
}

export type SpecValue = string | number | boolean | null | string[] | number[];

export interface Part {
  id: number;
  category: string;
  name: string;
  manufacturer: string | null;
  manufacturer_display: string;
  source: string;
  price: Money | null;
  currency: string;
  has_price: boolean;
  price_display: string;
  price_is_estimate: boolean;
  price_note: string | null;
  price_updated_at: IsoDate | null;
  power_w: number | null;
  power_display: string;
  specs: Record<string, SpecValue>;
  specs_display: SpecDisplay[];
  missing_specs: string[];
  is_data_complete: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// type, а не interface: так объект можно передать как query-параметры
export type PartsQuery = {
  category?: string;
  q?: string;
  manufacturer?: string;
  min_price?: number;
  max_price?: number;
  has_price?: boolean;
  socket?: string;
  form_factor?: string;
  memory_type?: string;
  sort?: 'name' | 'price' | '-price';
  limit?: number; // 1..100, по умолчанию 24
  offset?: number;
};

export interface ItemIn {
  part_id: number;
  quantity?: number; // 1..16
}

export interface Issue {
  rule: string;
  code: string;
  severity: Severity;
  message: string;
  part_ids: number[];
  details: Record<string, unknown>;
}

export interface PowerInfo {
  peak_w: number;
  recommended_w: number;
  suggested_psu_w: number;
  base_load_w: number;
  factor: number;
  vendor_min_w: number | null;
  by_category: Record<string, number>;
}

export interface CheckResult {
  is_compatible: boolean;
  is_complete: boolean;
  error_count: number;
  warning_count: number;
  issues: Issue[];
  power: PowerInfo;
  missing_categories: string[];
  total_price: Money | null;
  total_price_display: string;
  total_price_is_estimate: boolean;
  total_price_note: string | null;
  unpriced_part_ids: number[];
  unpriced_count: number;
}

export interface BuildIn {
  name: string; // 1..100
  description?: string | null; // до 2000
  items: ItemIn[]; // до 64
}

export interface BuildItem {
  part: Part;
  quantity: number;
  price_snapshot: Money | null;
  is_available: boolean;
}

export interface Build {
  id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  share_slug: string | null;
  share_path: string | null;
  created_at: IsoDate;
  updated_at: IsoDate;
  items: BuildItem[];
  unavailable_part_ids: number[];
  check: CheckResult;
  total_price: Money | null;
  total_price_display: string;
  total_price_is_estimate: boolean;
  total_price_note: string | null;
  unpriced_count: number;
  is_owner: boolean;
}

export interface BuildSummary {
  id: string;
  name: string;
  is_public: boolean;
  share_slug: string | null;
  total_price: Money | null;
  total_price_display: string;
  total_power_w: number;
  item_count: number;
  updated_at: IsoDate;
}

export interface BuildList {
  items: BuildSummary[];
  count: number;
  limit: number;
}

export interface ShareResult {
  share_slug: string;
  share_path: string;
  api_path: string;
}
