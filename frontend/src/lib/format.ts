export type PluralForms = [one: string, few: string, many: string];

export function plural(n: number, forms: PluralForms): string {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return forms[2];
  if (b > 1 && b < 5) return forms[1];
  if (b === 1) return forms[0];
  return forms[2];
}

export const countText = (n: number, forms: PluralForms): string =>
  `${n.toLocaleString('ru-RU')} ${plural(n, forms)}`;

export const PARTS_FORMS: PluralForms = ['товар', 'товара', 'товаров'];

export function specValue(key: string, value: string): string {
  if (key === 'interface') return value === 'nvme' ? 'NVMe' : value === 'sata' ? 'SATA' : value;
  if (key === 'form_factor' && /^\d+(\.\d+)?$/.test(value)) return `${value}″`;
  return value;
}