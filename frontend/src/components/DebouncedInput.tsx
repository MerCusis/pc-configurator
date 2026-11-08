import { useEffect, useState, type InputHTMLAttributes } from 'react';

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'> & {
  value: string;
  onChange: (value: string) => void;
  delay?: number;
};

/** Сообщает новое значение с задержкой, чтобы не отправлять запрос на каждую букву. */
export default function DebouncedInput({ value, onChange, delay = 400, ...rest }: Props) {
  const [local, setLocal] = useState(value);

  // значение поменялось снаружи (например, «Сбросить фильтры»)
  useEffect(() => setLocal(value), [value]);

  useEffect(() => {
    if (local === value) return;
    const t = window.setTimeout(() => onChange(local), delay);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local]);

  return <input {...rest} value={local} onChange={(e) => setLocal(e.target.value)} />;
}
