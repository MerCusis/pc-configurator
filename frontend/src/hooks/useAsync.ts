import { useCallback, useEffect, useState, type DependencyList } from 'react';
import { ApiError } from '../api/client';

export interface AsyncState<T> {
  data?: T;
  error?: string;
  loading: boolean;
}

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : 'Не удалось связаться с сервером';
}

/**
 * Загружает данные и отменяет запрос, если зависимости изменились или компонент размонтирован.
 * Пока идёт повторная загрузка, старые данные остаются на экране (без мигания при смене страницы).
 */
export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ loading: true });
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState((s) => ({ data: s.data, loading: true }));
    fn(ctrl.signal).then(
      (data) => {
        if (!ctrl.signal.aborted) setState({ data, loading: false });
      },
      (e: unknown) => {
        if (!ctrl.signal.aborted) setState({ error: errorText(e), loading: false });
      },
    );
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
