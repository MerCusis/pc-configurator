import { api } from '../api/api';
import { useAsync } from '../hooks/useAsync';

const DEVELOPERS = ['YaUstalVerit', 'KejStark1', 'fryxand9'];

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
      <div className="container small muted">
        <div>{text}</div>
        <div className="footer-credits">
          Разработчики Грязнульки с Бибинто:{' '}
          {DEVELOPERS.map((name, i) => (
            <span key={name}>
              {i > 0 && ', '}
              <a href={`https://t.me/${name}`} target="_blank" rel="noopener noreferrer">
                @{name}
              </a>
            </span>
          ))}
        </div>
      </div>
    </footer>
  );
}