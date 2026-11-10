import { useEffect, useRef, useState } from 'react';
import { api } from '../api/api';
import type { Category, Part, PartsQuery } from '../api/types';
import { useAsync } from '../hooks/useAsync';
import { categoryQuantity, type DraftItem } from '../lib/draftStore';
import { countText, PARTS_FORMS, specValue } from '../lib/format';
import DebouncedInput from './DebouncedInput';
import ErrorBox from './ErrorBox';
import Pagination from './Pagination';
import PartCard from './PartCard';

const PAGE_SIZE = 12;

type Sort = NonNullable<PartsQuery['sort']>;
const SORTS: { value: Sort; label: string }[] = [
  { value: 'price', label: 'Сначала дешёвые' },
  { value: '-price', label: 'Сначала дорогие' },
  { value: 'name', label: 'По названию' },
];
const isSort = (v: string | null): v is Sort => v === 'name' || v === 'price' || v === '-price';

// Сортировка общая для всех слотов и переживает перезагрузку
const SORT_KEY = 'pcc.sort.v1';
function readSort(): Sort {
  try {
    const v = localStorage.getItem(SORT_KEY);
    return isSort(v) ? v : 'price';
  } catch {
    return 'price';
  }
}
function writeSort(s: Sort): void {
  try {
    localStorage.setItem(SORT_KEY, s);
  } catch {
    // без localStorage сортировка просто не запомнится
  }
}

// Фильтры по характеристикам, которые поддерживает GET /parts.
// Показываем только те, для которых в категории есть хотя бы два разных значения.
const FACETS = [
  { key: 'socket', label: 'Сокет' },
  { key: 'form_factor', label: 'Форм-фактор' },
  { key: 'memory_type', label: 'Тип памяти' },
] as const;
type FacetKey = (typeof FACETS)[number]['key'];

// Если поле в specs называется не так, как параметр запроса (массивы)
const SPEC_SOURCE: Record<string, Partial<Record<FacetKey, { spec: string; label: string }>>> = {
  cpu: { memory_type: { spec: 'memory_types', label: 'Тип памяти' } },
  cooler: { socket: { spec: 'sockets', label: 'Сокет' } },
  case: { form_factor: { spec: 'motherboard_form_factors', label: 'Форм-фактор платы' } },
};

function facetOptions(parts: Part[], slug: string, key: FacetKey) {
  const src = SPEC_SOURCE[slug]?.[key];
  const specKey = src?.spec ?? key;
  const values = new Set<string>();
  let label = src?.label;
  for (const p of parts) {
    const v = p.specs[specKey];
    if (typeof v === 'string' && v) values.add(v);
    else if (Array.isArray(v)) for (const x of v) if (typeof x === 'string' && x) values.add(x);
    label ??= p.specs_display.find((s) => s.key === specKey)?.label;
  }
  return { label, values: [...values].sort((a, b) => a.localeCompare(b, 'ru', { numeric: true })) };
}

interface Filters {
  q: string;
  manufacturer: string;
  min_price: string;
  max_price: string;
  has_price: boolean;
  socket: string;
  form_factor: string;
  memory_type: string;
}
const NO_FILTERS: Filters = {
  q: '', manufacturer: '', min_price: '', max_price: '', has_price: false,
  socket: '', form_factor: '', memory_type: '',
};
const FILTER_KEYS = Object.keys(NO_FILTERS) as (keyof Filters)[];

function toPrice(v: string): number | undefined {
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

function specStr(part: Part | undefined, key: string): string | undefined {
  const v = part?.specs[key];
  return typeof v === 'string' && v ? v : undefined;
}

/**
 * Фильтры по уже выбранным деталям. Только те, что умеет GET /parts и что есть в данных импорта:
 * у кулеров из docyx нет sockets, поэтому фильтр по сокету для них не включаем.
 */
function compatFilters(slug: string, items: DraftItem[]) {
  const pick = (cat: string) => items.find((i) => i.part.category === cat)?.part;
  const cpu = pick('cpu');
  const mb = pick('motherboard');
  const ram = pick('ram');
  let socket: string | undefined;
  let memory: string | undefined;
  if (slug === 'cpu') {
    socket = specStr(mb, 'socket');
    memory = specStr(ram, 'memory_type');
  } else if (slug === 'motherboard') {
    socket = specStr(cpu, 'socket');
    memory = specStr(ram, 'memory_type');
  } else if (slug === 'ram') {
    memory = specStr(mb, 'memory_type');
    const types = cpu?.specs.memory_types;
    const first = Array.isArray(types) && types.length === 1 ? types[0] : undefined;
    if (!memory && typeof first === 'string') memory = first;
  }
  const labels = [socket ? `сокет ${socket}` : '', memory ?? ''].filter(Boolean);
  const filters: Partial<Record<FacetKey, string>> = { socket, memory_type: memory };
  return { filters, labels };
}

interface Props {
  category: Category;
  items: DraftItem[];
  onPick: (part: Part) => void;
  onClose: () => void;
}

export default function PartPicker({ category, items, onPick, onClose }: Props) {
  const slug = category.slug;
  const [f, setF] = useState<Filters>(NO_FILTERS);
  const [sort, setSort] = useState<Sort>(readSort);
  const [page, setPage] = useState(1);
  const [compatible, setCompatible] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);

  const set = (patch: Partial<Filters>) => {
    setF((prev) => ({ ...prev, ...patch }));
    setPage(1);
  };
  const changeSort = (s: Sort) => {
    setSort(s);
    writeSort(s);
    setPage(1);
  };
  const resetFilters = () => {
    setF(NO_FILTERS);
    setPage(1);
  };

  // «Только подходящие» фиксирует сокет и тип памяти по уже выбранным деталям
  const { filters, labels } = compatFilters(slug, items);
  const locked: Partial<Record<FacetKey, string>> = compatible ? filters : {};

  const query: PartsQuery = {
    category: slug,
    q: f.q.trim() || undefined,
    manufacturer: f.manufacturer || undefined,
    min_price: toPrice(f.min_price),
    max_price: toPrice(f.max_price),
    has_price: f.has_price || undefined,
    socket: locked.socket ?? (f.socket || undefined),
    form_factor: locked.form_factor ?? (f.form_factor || undefined),
    memory_type: locked.memory_type ?? (f.memory_type || undefined),
    sort,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };
  const parts = useAsync((signal) => api.parts(query, signal), [JSON.stringify(query)]);
  const manufacturers = useAsync((signal) => api.manufacturers(slug, signal), [slug]);
  // Выборка товаров категории, из неё берём варианты для фильтров по характеристикам
  const sample = useAsync((signal) => api.parts({ category: slug, limit: 100 }, signal), [slug]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const facets = FACETS.map((x) => {
    const opt = facetOptions(sample.data?.items ?? [], slug, x.key);
    const lock = locked[x.key];
    const current = lock ?? f[x.key];
    const values = current && !opt.values.includes(current) ? [...opt.values, current] : opt.values;
    return { key: x.key, label: opt.label ?? x.label, current, isLocked: !!lock, values };
  }).filter((x) => x.values.length > 1 || x.current !== '');

  const hasFilters = FILTER_KEYS.some((k) => f[k] !== NO_FILTERS[k]);
  const activeCount = FILTER_KEYS.filter((k) => k !== 'q' && f[k] !== NO_FILTERS[k]).length;

  const used = categoryQuantity(items, slug);
  const single = category.max_items <= 1;
  const current = single ? items.find((i) => i.part.category === slug) : undefined;
  const data = parts.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  const action = (p: Part) => {
    const inBuild = items.find((i) => i.part.id === p.id);
    let label: string;
    let disabled = false;
    if (single) {
      label = inBuild ? 'Уже в сборке' : current ? 'Заменить' : 'Выбрать';
      disabled = !!inBuild;
    } else {
      label = inBuild ? `Ещё одну (сейчас ${inBuild.quantity})` : 'Добавить';
      disabled = used >= category.max_items;
    }
    return (
      <button type="button" className="btn btn-primary" disabled={disabled} onClick={() => onPick(p)}>
        {label}
      </button>
    );
  };

  const goToPage = (p: number) => {
    setPage(p);
    bodyRef.current?.scrollTo({ top: 0 });
  };

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="picker card" role="dialog" aria-modal="true" aria-labelledby="picker-title">
        <div className="picker-head">
          <div>
            <h2 id="picker-title">{category.name}</h2>
            {!single && (
              <p className="small muted">
                Выбрано {used} из {category.max_items} шт.
              </p>
            )}
          </div>
          <button type="button" className="btn btn-icon" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>

        <div className="picker-toolbar">
          <DebouncedInput
            type="search"
            autoFocus
            aria-label="Поиск"
            placeholder="Название или модель"
            value={f.q}
            onChange={(v) => set({ q: v })}
          />
          <select aria-label="Сортировка" value={sort} onChange={(e) => changeSort(e.target.value as Sort)}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn filters-toggle"
            aria-expanded={showFilters}
            onClick={() => setShowFilters((v) => !v)}
          >
            Фильтры{activeCount > 0 ? ` (${activeCount})` : ''}
          </button>
        </div>

        {labels.length > 0 && (
          <label className="check compat">
            <input
              type="checkbox"
              checked={compatible}
              onChange={(e) => {
                setCompatible(e.target.checked);
                setPage(1);
              }}
            />
            Только подходящие: {labels.join(', ')}
          </label>
        )}

        <div className="picker-layout">
          <aside className={showFilters ? 'picker-filters is-open' : 'picker-filters'} aria-label="Фильтры">
            {manufacturers.data && manufacturers.data.length > 1 && (
              <label className="field">
                <span>Производитель</span>
                <select value={f.manufacturer} onChange={(e) => set({ manufacturer: e.target.value })}>
                  <option value="">Все</option>
                  {manufacturers.data.map((m) => (
                    <option key={m.slug} value={m.slug}>
                      {m.name} ({m.part_count})
                    </option>
                  ))}
                </select>
              </label>
            )}

            <fieldset className="field">
              <legend>Цена, ₽</legend>
              <div className="price-range">
                <DebouncedInput type="number" min={0} step={1000} inputMode="numeric" placeholder="от"
                  aria-label="Цена от" value={f.min_price} onChange={(v) => set({ min_price: v })} />
                <DebouncedInput type="number" min={0} step={1000} inputMode="numeric" placeholder="до"
                  aria-label="Цена до" value={f.max_price} onChange={(v) => set({ max_price: v })} />
              </div>
            </fieldset>

            {facets.map((x) => (
              <label key={x.key} className="field">
                <span>{x.label}</span>
                <select
                  value={x.current}
                  disabled={x.isLocked}
                  title={x.isLocked ? 'Задано выбранными деталями. Снимите «Только подходящие», чтобы изменить.' : undefined}
                  onChange={(e) => set({ [x.key]: e.target.value } as Partial<Filters>)}
                >
                  <option value="">Любой</option>
                  {x.values.map((v) => (
                    <option key={v} value={v}>
                      {specValue(x.key, v)}
                    </option>
                  ))}
                </select>
              </label>
            ))}

            <label className="check">
              <input type="checkbox" checked={f.has_price} onChange={(e) => set({ has_price: e.target.checked })} />
              Только с ценой
            </label>

            {hasFilters && (
              <button type="button" className="btn btn-link" onClick={resetFilters}>
                Сбросить фильтры
              </button>
            )}
          </aside>

          <div className="picker-body" ref={bodyRef} aria-busy={parts.loading}>
            {parts.error && <ErrorBox message={parts.error} onRetry={parts.reload} />}
            {!data && parts.loading && <p className="muted">Загрузка…</p>}
            {data && (
              <p className="small muted" aria-live="polite">
                Найдено {countText(data.total, PARTS_FORMS)}
              </p>
            )}
            {data && data.items.length === 0 && (
              <div className="empty">
                <p>Ничего не нашлось.</p>
                <div className="head-actions">
                  {hasFilters && (
                    <button type="button" className="btn" onClick={resetFilters}>
                      Сбросить фильтры
                    </button>
                  )}
                  {compatible && labels.length > 0 && (
                    <button type="button" className="btn" onClick={() => setCompatible(false)}>
                      Показать неподходящие
                    </button>
                  )}
                </div>
              </div>
            )}
            {data && data.items.length > 0 && (
              <ul className={parts.loading ? 'part-grid is-loading' : 'part-grid'}>
                {data.items.map((p) => (
                  <li key={p.id}>
                    <PartCard part={p} action={action(p)} />
                  </li>
                ))}
              </ul>
            )}
            <Pagination page={page} pages={pages} onChange={goToPage} />
          </div>
        </div>
      </div>
    </div>
  );
}