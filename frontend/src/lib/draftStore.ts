import { useSyncExternalStore } from 'react';
import type { Build, ItemIn, Part } from '../api/types';

export interface DraftItem {
  part: Part;
  quantity: number;
}

/** Черновик сборки. Хранится в localStorage: переживает перезагрузку и общий для всех вкладок. */
export interface Draft {
  buildId: string | null; // сохранённая сборка, которую редактируем
  name: string;
  description: string;
  items: DraftItem[];
  shareSlug: string | null;
  dirty: boolean; // есть изменения после последнего сохранения
}

const KEY = 'pcc.draft.v1';
export const MAX_QUANTITY = 16; // как build_items.quantity_range

const emptyDraft = (): Draft => ({
  buildId: null, name: '', description: '', items: [], shareSlug: null, dirty: false,
});

function isItem(v: unknown): v is DraftItem {
  if (!v || typeof v !== 'object') return false;
  const i = v as { part?: { id?: unknown; category?: unknown }; quantity?: unknown };
  return (
    !!i.part && typeof i.part.id === 'number' && typeof i.part.category === 'string' &&
    Number.isInteger(i.quantity) && (i.quantity as number) >= 1 && (i.quantity as number) <= MAX_QUANTITY
  );
}

function read(): Draft {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return emptyDraft();
    const d = JSON.parse(raw) as Partial<Record<keyof Draft, unknown>>;
    return {
      buildId: typeof d.buildId === 'string' ? d.buildId : null,
      name: typeof d.name === 'string' ? d.name.slice(0, 100) : '',
      description: typeof d.description === 'string' ? d.description.slice(0, 2000) : '',
      items: Array.isArray(d.items) ? d.items.filter(isItem) : [],
      shareSlug: typeof d.shareSlug === 'string' ? d.shareSlug : null,
      dirty: d.dirty === true,
    };
  } catch {
    return emptyDraft();
  }
}

let state: Draft = read();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

function commit(next: Draft): void {
  state = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    // localStorage недоступен: черновик проживёт до перезагрузки
  }
  emit();
}

// Черновик поменяли в другой вкладке
window.addEventListener('storage', (e) => {
  if (e.key === KEY || e.key === null) {
    state = read();
    emit();
  }
});

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const editItems = (fn: (items: DraftItem[]) => DraftItem[]) =>
  commit({ ...state, items: fn(state.items), dirty: true });

export const categoryQuantity = (items: DraftItem[], category: string): number =>
  items.filter((i) => i.part.category === category).reduce((n, i) => n + i.quantity, 0);

export const toItemsIn = (items: DraftItem[]): ItemIn[] =>
  items.map((i) => ({ part_id: i.part.id, quantity: i.quantity }));

function fromBuild(build: Build): { items: DraftItem[]; dropped: number } {
  const items = build.items.filter((i) => i.is_available).map((i) => ({ part: i.part, quantity: i.quantity }));
  return { items, dropped: build.items.length - items.length };
}

export const draft = {
  /** Слот на одну деталь: замена. Многоместный слот: новая позиция или +1 к количеству. */
  choose(part: Part, maxItems: number): void {
    editItems((items) => {
      if (maxItems <= 1) return [...items.filter((i) => i.part.category !== part.category), { part, quantity: 1 }];
      if (items.some((i) => i.part.id === part.id)) {
        return items.map((i) =>
          i.part.id === part.id ? { ...i, quantity: Math.min(i.quantity + 1, MAX_QUANTITY) } : i,
        );
      }
      return [...items, { part, quantity: 1 }];
    });
  },
  setQuantity(partId: number, quantity: number): void {
    const q = Math.min(Math.max(1, Math.round(quantity)), MAX_QUANTITY);
    editItems((items) => items.map((i) => (i.part.id === partId ? { ...i, quantity: q } : i)));
  },
  remove(partIds: number[]): void {
    const ids = new Set(partIds);
    editItems((items) => items.filter((i) => !ids.has(i.part.id)));
  },
  setName(name: string): void {
    commit({ ...state, name, dirty: true });
  },
  reset(): void {
    commit(emptyDraft());
  },
  /** Открыть свою сохранённую сборку. Возвращает число убранных деталей, снятых с продажи. */
  open(build: Build): number {
    const { items, dropped } = fromBuild(build);
    commit({
      buildId: build.id, name: build.name, description: build.description ?? '',
      items, shareSlug: build.share_slug, dirty: dropped > 0,
    });
    return dropped;
  },
  /** Чужая сборка по ссылке становится новым черновиком. */
  copy(build: Build): number {
    const { items, dropped } = fromBuild(build);
    commit({
      buildId: null, name: `${build.name} (копия)`.slice(0, 100), description: build.description ?? '',
      items, shareSlug: null, dirty: true,
    });
    return dropped;
  },
  /** snapshot: состояние на момент отправки. Если во время сохранения что-то поменяли, черновик остаётся изменённым. */
  saved(build: Build, snapshot: Draft): void {
    const untouched = state === snapshot;
    commit({
      ...state,
      buildId: build.id,
      name: untouched ? build.name : state.name,
      description: build.description ?? '',
      shareSlug: build.share_slug,
      dirty: !untouched,
    });
  },
  setShare(slug: string | null): void {
    commit({ ...state, shareSlug: slug });
  },
  /** Сборку удалили на сервере: черновик остаётся, следующее сохранение создаст новую. */
  detach(): void {
    commit({ ...state, buildId: null, shareSlug: null, dirty: true });
  },
};

export function useDraft(): Draft {
  return useSyncExternalStore(subscribe, () => state);
}