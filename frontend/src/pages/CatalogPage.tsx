import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/api';
import type { Category, Part, PartsQuery } from '../api/types';
import DebouncedInput from '../components/DebouncedInput';
import ErrorBox from '../components/ErrorBox';
import Pagination from '../components/Pagination';
import PartCard from '../components/PartCard';
import { useAsync } from '../hooks/useAsync';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { countText, PARTS_FORMS, specValue } from '../lib/format';
import NotFoundPage from './NotFoundPage';


const PAGE_SIZE = 24;

type Sort = NonNullable<PartsQuery['sort']>;
const SORTS: { value: Sort; label: string }[] = [
  { value: 'price', label: 'Сначала дешёвые' },
  { value: '-price', label: 'Сначала дорогие' },
  { value: 'name', label: 'По названию' },
];
const isSort = (v: string | null): v is Sort => v === 'name' || v === 'price' || v === '-price';

// Фильтры по характеристикам, которые поддерживает GET /parts.
// Показываем только те, для которых в категории есть хотя бы два разных значения.
const FACETS = [
  { key: 'socket', label: 'Сокет' },
  { key: 'form_factor', label: 'Форм-фактор' },
  { key: 'memory_type', label: 'Тип памяти' },
] as const;
type FacetKey = (typeof FACETS)[number]['key'];

const FILTER_KEYS = ['q', 'manufacturer', 'min_price', 'max_price', 'has_price', 'socket', 'form_factor', 'memory_type'];

function toPrice(v: string | null): number | undefined {
  if (!v) return undefined;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

// Если поле в specs называется не так, как параметр запроса (массивы).
// Бэкенд ищет по ним (проверено: cpu+DDR4 → 3, cooler+LGA1700 → 2, case+ATX → 2).
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

interface Props {
  slug: string;
  categories?: Category[];
}

export default function CatalogPage({ slug, categories }: Props) {
  const [params, setParams] = useSearchParams();
  const category = categories?.find((c) => c.slug === slug);
  useDocumentTitle(category?.name ?? 'Каталог');

  const get = (key: string) => params.get(key) ?? '';
  const sortParam = params.get('sort');
  const sort: Sort = isSort(sortParam) ? sortParam : 'price';
  const page = Math.max(1, Number.parseInt(get('page'), 10) || 1);

  const query: PartsQuery = {
    category: slug,
    q: get('q').trim() || undefined,
    manufacturer: get('manufacturer') || undefined,
    min_price: toPrice(params.get('min_price')),
    max_price: toPrice(params.get('max_price')),
    has_price: get('has_price') === '1' ? true : undefined,
    socket: get('socket') || undefined,
    form_factor: get('form_factor') || undefined,
    memory_type: get('memory_type') || undefined,
    sort,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };

  const parts = useAsync((signal) => api.parts(query, signal), [JSON.stringify(query)]);
  const manufacturers = useAsync((signal) => api.manufacturers(slug, signal), [slug]);
  // Выборка товаров категории, из неё берём варианты для фильтров по характеристикам
  const sample = useAsync((signal) => api.parts({ category: slug, limit: 100 }, signal), [slug]);

  if (categories && !category) return <NotFoundPage />;

  /** Меняет параметры в адресе. Любой новый фильтр возвращает на первую страницу. */
  const update = (patch: Record<string, string | undefined>, keepPage = false) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (!keepPage) next.delete('page');
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v);
          else next.delete(k);
        }
        return next;
      },
      { replace: !keepPage },
    );
  };

  const goToPage = (p: number) => {
    update({ page: p > 1 ? String(p) : undefined }, true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const hasFilters = FILTER_KEYS.some((k) => params.has(k));
  const resetFilters = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams();
        const s = prev.get('sort');
        if (s) next.set('sort', s);
        return next;
      },
      { replace: true },
    );
  };

  const facets = FACETS.map((f) => {
    const opt = facetOptions(sample.data?.items ?? [], slug, f.key);
    const current = get(f.key);
    const values = current && !opt.values.includes(current) ? [...opt.values, current] : opt.values;
    return { key: f.key, label: opt.label ?? f.label, current, values };
  }).filter((f) => f.values.length > 1 || f.current !== '');

  const data = parts.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <nav className="breadcrumbs" aria-label="Навигация">
        <Link to="/">Каталог</Link> / <span>{category?.name ?? '…'}</span>
      </nav>

      <div className="catalog-head">
        <h1>{category?.name ?? 'Каталог'}</h1>
        <label className="sort">
          <span className="small muted">Сортировка</span>
          <select value={sort} onChange={(e) => update({ sort: e.target.value })}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="catalog">
        <aside className="filters card" aria-label="Фильтры">
          <label className="field">
            <span>Поиск</span>
            <DebouncedInput
              type="search"
              placeholder="Название или модель"
              value={get('q')}
              onChange={(v) => update({ q: v.trim() || undefined })}
            />
          </label>

          {manufacturers.data && manufacturers.data.length > 1 && (
            <label className="field">
              <span>Производитель</span>
              <select value={get('manufacturer')} onChange={(e) => update({ manufacturer: e.target.value })}>
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
              <DebouncedInput
                type="number"
                min={0}
                step={1000}
                inputMode="numeric"
                placeholder="от"
                aria-label="Цена от"
                value={get('min_price')}
                onChange={(v) => update({ min_price: v })}
              />
              <DebouncedInput
                type="number"
                min={0}
                step={1000}
                inputMode="numeric"
                placeholder="до"
                aria-label="Цена до"
                value={get('max_price')}
                onChange={(v) => update({ max_price: v })}
              />
            </div>
          </fieldset>

          {facets.map((f) => (
            <label key={f.key} className="field">
              <span>{f.label}</span>
              <select value={f.current} onChange={(e) => update({ [f.key]: e.target.value })}>
                <option value="">Любой</option>
                {f.values.map((v) => (
                  <option key={v} value={v}>
                    {specValue(f.key, v)}
                  </option>
                ))}
              </select>
            </label>
          ))}

          <label className="check">
            <input
              type="checkbox"
              checked={get('has_price') === '1'}
              onChange={(e) => update({ has_price: e.target.checked ? '1' : undefined })}
            />
            Только с ценой
          </label>

          {hasFilters && (
            <button type="button" className="btn btn-link" onClick={resetFilters}>
              Сбросить фильтры
            </button>
          )}
        </aside>

        <section className="results" aria-label="Товары" aria-busy={parts.loading}>
          {parts.error && <ErrorBox message={parts.error} onRetry={parts.reload} />}
          {!data && parts.loading && <p className="muted">Загрузка…</p>}
          {data && (
            <p className="muted" aria-live="polite">
              Найдено {countText(data.total, PARTS_FORMS)}
            </p>
          )}

          {data && data.items.length === 0 && (
            <div className="card empty">
              <p>По этим условиям ничего не нашлось.</p>
              {hasFilters && (
                <button type="button" className="btn" onClick={resetFilters}>
                  Сбросить фильтры
                </button>
              )}
            </div>
          )}

          {data && data.items.length > 0 && (
            <ul className={parts.loading ? 'part-grid is-loading' : 'part-grid'}>
              {data.items.map((p) => (
                <li key={p.id}>
                  <PartCard part={p} />
                </li>
              ))}
            </ul>
          )}

          <Pagination page={page} pages={pages} onChange={goToPage} />
        </section>
      </div>
    </>
  );
}
