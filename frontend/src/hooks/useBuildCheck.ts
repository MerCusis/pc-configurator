import { useEffect, useState } from 'react';
import { api } from '../api/api';
import { ApiError } from '../api/client';
import type { CheckResult, ItemIn } from '../api/types';
import { draft, type DraftItem } from '../lib/draftStore';
import { errorText } from './useAsync';

interface State {
  result?: CheckResult;
  error?: string;
  loading: boolean;
}

/** Проверяет черновик через POST /compatibility/check через 300 мс после последнего изменения. */
export function useBuildCheck(items: DraftItem[]): State & { removed: number } {
  const key = items.map((i) => `${i.part.id}:${i.quantity}`).join(',');
  const [state, setState] = useState<State>({ loading: false });
  const [removed, setRemoved] = useState(0);

  useEffect(() => {
    if (!key) {
      setState({ loading: false });
      return;
    }
    const payload: ItemIn[] = key.split(',').map((pair) => {
      const [id, qty] = pair.split(':');
      return { part_id: Number(id), quantity: Number(qty) };
    });
    const ctrl = new AbortController();
    setState((s) => ({ result: s.result, loading: true }));
    const timer = window.setTimeout(() => {
      api.check(payload, ctrl.signal).then(
        (result) => {
          if (!ctrl.signal.aborted) setState({ result, loading: false });
        },
        (e: unknown) => {
          if (ctrl.signal.aborted) return;
          // Деталь сняли с продажи, пока она лежала в черновике: убираем её и проверяем заново
          const ids = e instanceof ApiError && e.code === 'unknown_parts'
            ? (e.details as { part_ids?: unknown } | undefined)?.part_ids
            : undefined;
          const list = Array.isArray(ids) ? ids.filter((x): x is number => typeof x === 'number') : [];
          if (list.length > 0) {
            setRemoved((n) => n + list.length);
            setState({ loading: false });
            draft.remove(list);
            return;
          }
          setState({ error: errorText(e), loading: false });
        },
      );
    }, 300);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [key]);

  return { ...state, removed };
}