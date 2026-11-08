interface Props {
  message: string;
  onRetry?: () => void;
}

export default function ErrorBox({ message, onRetry }: Props) {
  return (
    <div role="alert" className="alert">
      <span>{message}</span>
      {onRetry && (
        <button type="button" className="btn btn-small" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}
