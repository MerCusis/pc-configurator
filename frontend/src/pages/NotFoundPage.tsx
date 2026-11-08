import { Link } from 'react-router-dom';
import { useDocumentTitle } from '../hooks/useDocumentTitle';

export default function NotFoundPage() {
  useDocumentTitle('Страница не найдена');
  return (
    <>
      <h1>Страница не найдена</h1>
      <p>
        <Link to="/">Вернуться в каталог</Link>
      </p>
    </>
  );
}
