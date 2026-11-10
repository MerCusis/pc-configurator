import { useNavigate, useParams } from 'react-router-dom';
import { api } from '../api/api';
import { ApiError } from '../api/client';
import type { Build, Category } from '../api/types';
import CheckSummary, { IssueList } from '../components/CheckSummary';
import ErrorBox from '../components/ErrorBox';
import { useAsync } from '../hooks/useAsync';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { draft, useDraft } from '../lib/draftStore';

const SLUG_RE = /^[A-Za-z0-9_-]{8,16}$/; // как SLUG_PATTERN в builds.py

export default function SharedBuildPage({ categories }: { categories?: Category[] }) {
  const { slug = '' } = useParams();
  const shared = useAsync(
    () => SLUG_RE.test(slug)
      ? api.shared(slug)
      : Promise.reject<Build>(new ApiError(404, 'build_not_found', 'Сборка не найдена или ссылка отозвана')),
    [slug],
  );
  const b = shared.data;
  useDocumentTitle(b?.name ?? 'Сборка');
  const d = useDraft();
  const navigate = useNavigate();
  const categoryName = (s: string) => categories?.find((c) => c.slug === s)?.name ?? s;

  function copy() {
    if (!b) return;
    if (d.dirty && d.items.length > 0 && !window.confirm('Текущий черновик с несохранёнными изменениями будет заменён. Продолжить?')) return;
    navigate('/build', { state: { dropped: draft.copy(b) } });
  }

  if (shared.error) return <ErrorBox message={shared.error} onRetry={shared.reload} />;
  if (!b) return <p className="muted">Загрузка…</p>;

  return (
    <>
      <nav className="breadcrumbs">Сборка по ссылке</nav>
      <div className="catalog-head">
        <div>
          <h1>{b.name}</h1>
          {b.description && <p className="muted">{b.description}</p>}
        </div>
        <button type="button" className="btn btn-primary" onClick={copy}>
          Изменить копию
        </button>
      </div>

      <div className="configurator">
        <section className="card shared-items">
          {b.items.length === 0 ? (
            <p className="muted">В сборке нет деталей.</p>
          ) : (
            <table className="parts-table">
              <thead>
                <tr>
                  <th>Категория</th>
                  <th>Деталь</th>
                  <th>Кол-во</th>
                  <th>Цена</th>
                </tr>
              </thead>
              <tbody>
                {b.items.map((i) => (
                  <tr key={i.part.id} className={i.is_available ? undefined : 'is-unavailable'}>
                    <td className="muted">{categoryName(i.part.category)}</td>
                    <td>
                      {i.part.name}
                      {!i.is_available && <span className="badge badge-warn">снята с продажи</span>}
                    </td>
                    <td>{i.quantity}</td>
                    <td className="nowrap">
                      {i.part.price_is_estimate && '≈ '}
                      {i.part.price_display}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <aside className="summary-panel card" aria-label="Итог">
          <h2>Итог</h2>
          <CheckSummary result={b.check} categoryName={categoryName} />
          <IssueList issues={b.check.issues} />
        </aside>
      </div>
    </>
  );
}