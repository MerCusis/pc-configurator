import type { ReactNode } from 'react';
import type { Part } from '../api/types';
import { specValue } from '../lib/format';

interface Props {
  part: Part;
  /** Кнопка действия, например «Выбрать» в конфигураторе. */
  action?: ReactNode;
}

export default function PartCard({ part, action }: Props) {
  return (
    <article className="card part">
      <div>
        <p className="part-maker small muted">{part.manufacturer_display}</p>
        <h3 className="part-name">{part.name}</h3>
      </div>

      {part.specs_display.length > 0 && (
        <dl className="specs">
          {part.specs_display.map((s) => (
            <div key={s.key} className="spec">
              <dt>{s.label}</dt>
              <dd className={s.missing ? 'muted' : undefined}>{s.missing ? s.value : specValue(s.key, s.value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {!part.is_data_complete && <p className="badge badge-warn">Характеристики неполные</p>}

      <div className="part-footer">
        <div>
          <span className={part.has_price ? 'price' : 'price muted'}>
            {part.price_is_estimate && <span title="Оценочная цена">≈ </span>}
            {part.price_display}
          </span>
          {part.price_note && <p className="price-note small muted">{part.price_note}</p>}
        </div>
        {part.power_w !== null && (
          <span className="small muted" title="Пиковое потребление">
            {part.power_display}
          </span>
        )}
      </div>
      {action}
    </article>
  );
}
