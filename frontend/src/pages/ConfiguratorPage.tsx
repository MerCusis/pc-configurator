import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { api } from '../api/api';
import { ApiError } from '../api/client';
import type { Build, BuildIn, Category, Issue, Part } from '../api/types';
import CheckSummary, { IssueList } from '../components/CheckSummary';
import ErrorBox from '../components/ErrorBox';
import PartPicker from '../components/PartPicker';
import { errorText } from '../hooks/useAsync';
import { useBuildCheck } from '../hooks/useBuildCheck';
import { useDocumentTitle } from '../hooks/useDocumentTitle';
import { draft, MAX_QUANTITY, toItemsIn, useDraft, type DraftItem } from '../lib/draftStore';

const DEFAULT_NAME = 'Моя сборка';

/** Ключ встроенной графики в specs зависит от импорта, поэтому проверяем несколько вариантов. */
const IGPU_KEYS = ['integrated_graphics', 'has_igpu', 'igpu', 'graphics'];

function hasIntegratedGraphics(cpu?: Part): boolean {
  if (!cpu) return false;
  return IGPU_KEYS.some((k) => {
    const v = cpu.specs[k];
    if (typeof v === 'boolean') return v;
    if (typeof v === 'string') {
      const s = v.trim();
      return s !== '' && !/^(нет|no|none|false|0|-)$/i.test(s);
    }
    return false;
  });
}

type Need = 'required' | 'optional';

/** PUT, а если сборки уже нет (удалена или сменилась гостевая сессия), то POST. */
async function persist(buildId: string | null, body: BuildIn): Promise<Build> {
  if (!buildId) return api.createBuild(body);
  try {
    return await api.updateBuild(buildId, body);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return api.createBuild(body);
    throw e;
  }
}

function saveErrorText(e: unknown): string {
  if (e instanceof ApiError && e.code === 'build_limit') return `${e.message}. Удалите ненужные на странице «Мои сборки».`;
  return errorText(e);
}

interface SlotItemProps {
  item: DraftItem;
  multi: boolean;
  canAdd: boolean;
}

function SlotItem({ item, multi, canAdd }: SlotItemProps) {
  const p = item.part;
  return (
    <li className="slot-item">
      <div className="slot-item-main">
        <span className="small muted">{p.manufacturer_display}</span>
        <span className="slot-item-name">{p.name}</span>
        {!p.is_data_complete && <span className="badge badge-warn">Характеристики неполные</span>}
      </div>
      {multi && (
        <div className="qty">
          <button type="button" className="btn btn-small" aria-label="Меньше" disabled={item.quantity <= 1}
            onClick={() => draft.setQuantity(p.id, item.quantity - 1)}>
            −
          </button>
          <span aria-label="Количество">{item.quantity}</span>
          <button type="button" className="btn btn-small" aria-label="Больше"
            disabled={!canAdd || item.quantity >= MAX_QUANTITY}
            onClick={() => draft.setQuantity(p.id, item.quantity + 1)}>
            +
          </button>
        </div>
      )}
      <span className="slot-item-price">
        {p.price_is_estimate && '≈ '}
        {p.price_display}
        {item.quantity > 1 && ` × ${item.quantity}`}
      </span>
      <button type="button" className="btn btn-small btn-danger" onClick={() => draft.remove([p.id])}
        aria-label={`Убрать ${p.name}`}>
        Убрать
      </button>
    </li>
  );
}

interface SlotProps {
  category: Category;
  items: DraftItem[];
  issues: Issue[];
  need: Need;
  hint?: string;
  onPick: () => void;
}

function Slot({ category, items, issues, need, hint, onPick }: SlotProps) {
  const used = items.reduce((n, i) => n + i.quantity, 0);
  const multi = category.max_items > 1;
  const canAdd = used < category.max_items;
  const hasError = issues.some((i) => i.severity === 'error');
  const empty = items.length === 0;

  let tone = '';
  if (hasError) tone = ' slot-error';
  else if (issues.length > 0) tone = ' slot-warn';
  else if (empty && need === 'required') tone = ' slot-error';
  else if (empty) tone = ' slot-warn';

  return (
    <li className={`slot card${tone}`}>
      <div className="slot-head">
        <div>
          <h2 className="slot-title">{category.name}</h2>
          {multi && <p className="small muted">до {category.max_items} шт.</p>}
        </div>
        <button type="button" className={empty ? 'btn btn-primary' : 'btn'} onClick={onPick}
          disabled={multi && !canAdd}>
          {empty ? 'Выбрать' : multi ? 'Добавить' : 'Заменить'}
        </button>
      </div>
      {!empty && (
        <ul className="slot-items">
          {items.map((i) => (
            <SlotItem key={i.part.id} item={i} multi={multi} canAdd={canAdd} />
          ))}
        </ul>
      )}
      {hint && <p className="small muted">{hint}</p>}
      <IssueList issues={issues} />
    </li>
  );
}

interface Props {
  categories?: Category[];
}

export default function ConfiguratorPage({ categories }: Props) {
  useDocumentTitle('Сборка');
  const d = useDraft();
  const check = useBuildCheck(d.items);
  const location = useLocation();
    const navigate = useNavigate();
  const [dropped] = useState(() => (location.state as { dropped?: number } | null)?.dropped ?? 0);
  useEffect(() => {
    if (location.state) navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

  const [picker, setPicker] = useState<Category | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState<string>();
  const [copied, setCopied] = useState(false);

  const closePicker = useCallback(() => setPicker(null), []);
  const categoryName = useCallback(
    (slug: string) => categories?.find((c) => c.slug === slug)?.name ?? slug,
    [categories],
  );

  const result = check.result;
  // Проблема показывается у каждого слота, к деталям которого она относится
  const { bySlot, general } = useMemo(() => {
    const catOf = new Map(d.items.map((i) => [i.part.id, i.part.category] as const));
    const slots = new Map<string, Issue[]>();
    const rest: Issue[] = [];
    for (const issue of result?.issues ?? []) {
      const cats = new Set(issue.part_ids.map((id) => catOf.get(id)).filter((c): c is string => !!c));
      if (cats.size === 0) rest.push(issue);
      for (const c of cats) slots.set(c, [...(slots.get(c) ?? []), issue]);
    }
    return { bySlot: slots, general: rest };
  }, [result, d.items]);

  // Все пустые слоты красные. Видеокарта жёлтая, если у процессора есть встроенная графика.
  const cpu = d.items.find((i) => i.part.category === 'cpu')?.part;
  const igpu = hasIntegratedGraphics(cpu);
  const needOf = (c: Category): Need => {
    if (c.slug === 'gpu' && igpu) return 'optional';
    return 'required';
  };

  const hasErrors = (result?.error_count ?? 0) > 0;
  const canSave = d.items.length > 0 && !hasErrors && !saving && !check.loading && (d.dirty || !d.buildId);
  const shareUrl = d.shareSlug ? `${window.location.origin}/b/${d.shareSlug}` : null;
  const removed = dropped + check.removed;

  async function save() {
    const snapshot = d;
    const body: BuildIn = {
      name: d.name.trim() || DEFAULT_NAME,
      description: d.description.trim() || null,
      items: toItemsIn(d.items),
    };
    setSaving(true);
    setSaveError(undefined);
    try {
      draft.saved(await persist(d.buildId, body), snapshot);
    } catch (e) {
      setSaveError(saveErrorText(e));
    } finally {
      setSaving(false);
    }
  }

  async function share() {
    if (!d.buildId) return;
    setShareBusy(true);
    setShareError(undefined);
    try {
      draft.setShare((await api.share(d.buildId)).share_slug);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) draft.detach();
      setShareError(errorText(e));
    } finally {
      setShareBusy(false);
    }
  }

  async function unshare() {
    if (!d.buildId) return;
    if (!window.confirm('Ссылка перестанет открываться. При повторной публикации будет новая. Продолжить?')) return;
    setShareBusy(true);
    setShareError(undefined);
    try {
      await api.unshare(d.buildId);
      draft.setShare(null);
    } catch (e) {
      setShareError(errorText(e));
    } finally {
      setShareBusy(false);
    }
  }

  async function copyLink() {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setShareError('Не удалось скопировать, выделите ссылку вручную');
    }
  }

  function startNew() {
    if (d.dirty && d.items.length > 0 && !window.confirm('Несохранённые изменения пропадут. Начать новую сборку?')) return;
    draft.reset();
  }

  const psuHint = result && d.items.length > 0
    ? `Рекомендуется от ${result.power.suggested_psu_w} Вт (пик ${result.power.peak_w} Вт)`
    : undefined;

  return (
    <>
      <div className="catalog-head">
        <div>
          <h1>{d.buildId ? 'Редактирование сборки' : 'Новая сборка'}</h1>
          <p className="small muted">
            {d.buildId
              ? d.dirty ? 'Есть несохранённые изменения' : 'Все изменения сохранены'
              : 'Черновик хранится в этом браузере'}
          </p>
        </div>
        <div className="head-actions">
          <Link to="/builds" className="btn">Мои сборки</Link>
          <button type="button" className="btn" onClick={startNew} disabled={d.items.length === 0 && !d.buildId}>
            Новая сборка
          </button>
        </div>
      </div>

      {removed > 0 && (
        <div className="alert alert-info">Детали, снятые с продажи, убраны из сборки: {removed} шт.</div>
      )}
      {check.error && <ErrorBox message={check.error} />}
      {!categories && <p className="muted">Загрузка…</p>}

      <div className="configurator">
        <ol className="slots">
          {categories?.map((c) => (
            <Slot
              key={c.slug}
              category={c}
              items={d.items.filter((i) => i.part.category === c.slug)}
              issues={bySlot.get(c.slug) ?? []}
              need={needOf(c)}
              hint={c.slug === 'psu' ? psuHint : undefined}
              onPick={() => setPicker(c)}
            />
          ))}
        </ol>

        <aside className="summary-panel card" aria-label="Итог">
          <h2>Итог</h2>
          <CheckSummary result={result} loading={check.loading} categoryName={categoryName} />
          <IssueList issues={general} />

          <label className="field">
            <span>Название</span>
            <input value={d.name} maxLength={100} placeholder={DEFAULT_NAME}
              onChange={(e) => draft.setName(e.target.value)} />
          </label>
          <button type="button" className="btn btn-primary" disabled={!canSave} onClick={() => void save()}>
            {saving ? 'Сохранение…' : d.buildId ? 'Сохранить изменения' : 'Сохранить сборку'}
          </button>
          {hasErrors && <p className="small muted">Исправьте ошибки совместимости, чтобы сохранить.</p>}
          {saveError && <ErrorBox message={saveError} />}

          {d.buildId && !d.dirty && (
            <div className="share">
              <span className="small"><b>Ссылка на сборку</b></span>
              {shareUrl ? (
                <>
                  <div className="share-row">
                    <input readOnly value={shareUrl} aria-label="Ссылка на сборку"
                      onFocus={(e) => e.currentTarget.select()} />
                    <button type="button" className="btn" onClick={() => void copyLink()}>
                      {copied ? 'Скопировано' : 'Копировать'}
                    </button>
                  </div>
                  <button type="button" className="btn btn-link" disabled={shareBusy} onClick={() => void unshare()}>
                    Закрыть доступ по ссылке
                  </button>
                </>
              ) : (
                <button type="button" className="btn" disabled={shareBusy} onClick={() => void share()}>
                  {shareBusy ? 'Публикация…' : 'Получить ссылку'}
                </button>
              )}
              {shareError && <ErrorBox message={shareError} />}
            </div>
          )}
          {d.buildId && d.dirty && d.shareSlug && (
            <p className="small muted">По ссылке видна последняя сохранённая версия.</p>
          )}
        </aside>
      </div>

      {picker && (
        <PartPicker
          category={picker}
          items={d.items}
          onClose={closePicker}
          onPick={(p) => {
            draft.choose(p, picker.max_items);
            setPicker(null);
          }}
        />
      )}
    </>
  );
}