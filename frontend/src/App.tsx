import { Link, Navigate, NavLink, Route, Routes } from 'react-router-dom';
import { api } from './api/api';
import ErrorBox from './components/ErrorBox';
import StatusBar from './components/StatusBar';
import { useAsync } from './hooks/useAsync';
import { useDraft } from './lib/draftStore';
import BuildsPage from './pages/BuildsPage';
import ConfiguratorPage from './pages/ConfiguratorPage';
import NotFoundPage from './pages/NotFoundPage';
import SharedBuildPage from './pages/SharedBuildPage';

export default function App() {
  const categories = useAsync((signal) => api.categories(signal), []);
  const draft = useDraft();
  const count = draft.items.reduce((n, i) => n + i.quantity, 0);

  return (
    <>
      <header className="header">
        <div className="container header-inner">
          <Link to="/build" className="logo" aria-label="Бонч-Конфигуратор, на главную">
            <img src="/logo.png" alt="Бонч-Конфигуратор ПК" width={150} height={56} />
          </Link>
          <nav className="nav" aria-label="Разделы">
            <NavLink to="/build" className="nav-link">
              Сборка
              {count > 0 && <span className="nav-count">{count}</span>}
            </NavLink>
            <NavLink to="/builds" className="nav-link">
              Мои сборки
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="container main">
        {categories.error && <ErrorBox message={categories.error} onRetry={categories.reload} />}
        <Routes>
          <Route path="/" element={<Navigate to="/build" replace />} />
          {/* старые ссылки на каталог */}
          <Route path="/catalog/*" element={<Navigate to="/build" replace />} />
          <Route path="/build" element={<ConfiguratorPage categories={categories.data} />} />
          <Route path="/builds" element={<BuildsPage />} />
          <Route path="/b/:slug" element={<SharedBuildPage categories={categories.data} />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <StatusBar />
    </>
  );
}