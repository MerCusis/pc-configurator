interface Props {
  page: number;
  pages: number;
  onChange: (page: number) => void;
}

export default function Pagination({ page, pages, onChange }: Props) {
  if (pages <= 1) return null;
  return (
    <nav className="pagination" aria-label="Страницы">
      <button type="button" className="btn" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Назад
      </button>
      <span>
        Страница {page} из {pages}
      </span>
      <button type="button" className="btn" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        Вперёд →
      </button>
    </nav>
  );
}
