import { Link } from 'react-router-dom';
import type { Category } from '../api/types';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { countText, PARTS_FORMS } from '../lib/format';

interface Props {
  categories?: Category[];
  loading: boolean;
}

export default function HomePage({ categories, loading }: Props) {
  useDocumentTitle('');
  return (
    <>
      <h1>Каталог комплектующих</h1>
      <p className="muted">Выберите категорию, чтобы посмотреть товары.</p>
      {loading && !categories && <p className="muted">Загрузка…</p>}
      {categories && (
        <ul className="category-grid">
          {categories.map((c) => (
            <li key={c.slug}>
              <Link to={`/catalog/${c.slug}`} className="card category-card">
                <span className="category-name">{c.name}</span>
                <span className="small muted">
                  {countText(c.part_count, PARTS_FORMS)}
                  {c.is_required ? ' · обязательно для сборки' : ''}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
