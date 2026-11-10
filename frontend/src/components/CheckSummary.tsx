import type { CheckResult, Issue } from '../api/types';

export function IssueList({ issues }: { issues: Issue[] }) {
  if (issues.length === 0) return null;
  return (
    <ul className="issues">
      {issues.map((i, n) => (
        <li key={`${i.rule}:${i.code}:${n}`} className={i.severity === 'error' ? 'issue issue-error' : 'issue issue-warning'}>
          {i.message}
        </li>
      ))}
    </ul>
  );
}

function status(r: CheckResult): { cls: string; text: string; note?: string } {
  if (r.error_count > 0) {
    return { cls: 'status-error', text: 'Детали несовместимы', note: 'Что не так, написано у слотов с красной рамкой.' };
  }
  const note = r.warning_count > 0
    ? 'Есть замечания, они написаны у слотов с жёлтой рамкой. Сохранить сборку можно.'
    : undefined;
  if (r.missing_categories.length > 0) return { cls: 'status-warn', text: 'Сборка не закончена', note };
  if (r.warning_count > 0) return { cls: 'status-ok', text: 'Детали совместимы', note };
  return { cls: 'status-ok', text: 'Сборка совместима' };
}

interface Props {
  result?: CheckResult;
  loading?: boolean;
  categoryName: (slug: string) => string;
}

export default function CheckSummary({ result, loading, categoryName }: Props) {
  if (!result) {
    return <p className="small muted">{loading ? 'Проверка…' : 'Выберите детали, чтобы увидеть итог.'}</p>;
  }
  const s = status(result);
  const p = result.power;
  return (
    <div className={loading ? 'summary is-loading' : 'summary'}>
      <p className={`status ${s.cls}`} aria-live="polite">
        {s.text}
      </p>
      {result.missing_categories.length > 0 && (
        <p className="small">Не хватает: {result.missing_categories.map(categoryName).join(', ')}</p>
      )}
      {s.note && <p className="small muted">{s.note}</p>}
      <dl className="totals">
        <div>
          <dt>Итого</dt>
          <dd className="price">
            {result.total_price_is_estimate && '≈ '}
            {result.total_price_display}
          </dd>
        </div>
        <div>
          <dt>Пиковое потребление</dt>
          <dd>{p.peak_w}&nbsp;Вт</dd>
        </div>
        <div>
          <dt>Блок питания</dt>
          <dd>от {p.suggested_psu_w}&nbsp;Вт</dd>
        </div>
      </dl>
      {result.total_price_note && <p className="small muted">{result.total_price_note}</p>}
    </div>
  );
}