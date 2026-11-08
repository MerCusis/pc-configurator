import { api } from '../api/api';
import { useAsync } from '../hooks/useAsync';

export default function StatusBar() {
  const health = useAsync((signal) => api.health(signal), []);
  const h = health.data;
  let text = 'Проверка API…';
  if (health.error) text = 'API недоступен';
  else if (h) {
    text = `API ${h.version}: база ${h.db ? 'доступна' : 'недоступна'}, Redis ${h.redis ? 'доступен' : 'недоступен'}`;
  }
  return (
    <footer className="footer">
      <div className="container small muted">{text}</div>
    </footer>
  );
}
