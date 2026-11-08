import { Link, NavLink, Route, Routes, useParams } from 'react-router-dom';
import { api } from './api/api';
import type { Category } from './api/types';
import ErrorBox from './components/ErrorBox';
import StatusBar from './components/StatusBar';
import { useAsync } from './hooks/useAsync';
import CatalogPage from './pages/CatalogPage';
import HomePage from './pages/HomePage';
import NotFoundPage from './pages/NotFoundPage';

function CatalogRoute({ categories }: { categories?: Category[] }) {
  const { slug = '' } = useParams();
  // key пересоздаёт страницу при смене категории: фильтры и данные прошлой категории не мелькают
  return <CatalogPage key={slug} slug={slug} categories={categories} />;
}

export default function App() {
  const categories = useAsync((signal) => api.categories(signal), []);

  return (
    <>
      <header className="header">
        <div className="container header-inner">
          <Link to="/" className="logo">
            Конфигуратор ПК
          </Link>
          <nav className="nav" aria-label="Категории">
            {categories.data?.map((c) => (
              <NavLink key={c.slug} to={`/catalog/${c.slug}`} className="nav-link">
                {c.name}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="container main">
        {categories.error && <ErrorBox message={categories.error} onRetry={categories.reload} />}
        <Routes>
          <Route path="/" element={<HomePage categories={categories.data} loading={categories.loading} />} />
          <Route path="/catalog/:slug" element={<CatalogRoute categories={categories.data} />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <StatusBar />
    </>
  );
}
