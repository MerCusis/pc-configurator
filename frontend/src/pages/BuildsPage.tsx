import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/api';
import type { BuildSummary } from '../api/types';
import ErrorBox from '../components/ErrorBox';
import { errorText, useAsync } from '../hooks/useAsync';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { draft, useDraft } from '../lib/draftStore';
import { countText, type PluralForms } from '../lib/format';

const ITEM_FORMS: PluralForms = ['деталь', 'детали', 'деталей'];
const dateText = (iso: string) => new Date(iso).toLocaleString('ru-RU', { dateStyle: 'medium', timeStyle: 'short' });

export default function BuildsPage() {
  useDocumentTitle('Мои сборки');
  const navigate = useNavigate();
  const d = useDraft();
  const list = useAsync(() => api.builds(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string>();

  async function open(b: BuildSummary) {
    // Эта сборка уже открыта с правками: не затираем их версией с сервера
    if (d.buildId === b.id && d.dirty) {
      navigate('/build');
      return;
    }
    if (d.dirty && d.items.length > 0 && !window.confirm('Несохранённые изменения текущего черновика пропадут. Продолжить?')) return;
    setBusy(b.id);
    setError(undefined);
    try {
      const dropped = draft.open(await api.build(b.id));
      navigate('/build', { state: { dropped } });
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  }

  async function remove(b: BuildSummary) {
    if (!window.confirm(`Удалить сборку «${b.name}»? Ссылка на неё тоже перестанет работать.`)) return;
    setBusy(b.id);
    setError(undefined);
    try {
      await api.deleteBuild(b.id);
      if (d.buildId === b.id) draft.detach();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
      list.reload();
    }
  }

  const data = list.data;
  return (
    <>
      <div className="catalog-head">
        <h1>Мои сборки</h1>
        <Link to="/build" className="btn btn-primary">
          {d.items.length > 0 ? 'Вернуться к сборке' : 'Собрать ПК'}
        </Link>
      </div>
      <p className="small muted">
        Сборки привязаны к этому браузеру.{data ? ` Сохранено ${data.count} из ${data.limit}.` : ''}
      </p>

      {list.error && <ErrorBox message={list.error} onRetry={list.reload} />}
      {error && <ErrorBox message={error} />}
      {!data && list.loading && <p className="muted">Загрузка…</p>}

      {data && data.items.length === 0 && (
        <div className="card empty">
          <p>Сохранённых сборок пока нет.</p>
          <Link to="/build" className="btn">Собрать ПК</Link>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="build-list">
          {data.items.map((b) => (
            <li key={b.id} className="card build-row">
              <div>
                <h2 className="slot-title">
                  {b.name}
                  {d.buildId === b.id && <span className="badge badge-info">открыта</span>}
                </h2>
                <p className="small muted">
                  {countText(b.item_count, ITEM_FORMS)} · {b.total_power_w ?? 0} Вт · изменена {dateText(b.updated_at)}
                  {b.is_public ? ' · доступна по ссылке' : ''}
                </p>
              </div>
              <span className="price">{b.total_price_display}</span>
              <div className="head-actions">
                {b.share_slug && (
                  <Link to={`/b/${b.share_slug}`} className="btn btn-small">Ссылка</Link>
                )}
                <button type="button" className="btn btn-small" disabled={busy === b.id} onClick={() => void open(b)}>
                  Открыть
                </button>
                <button type="button" className="btn btn-small btn-danger" disabled={busy === b.id}
                  onClick={() => void remove(b)}>
                  Удалить
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}