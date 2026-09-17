// ============================================================
// Shared formatting helpers for the dashboard.
// ============================================================

export function fmtMoney(value: number | null | undefined, symbol = 'R$'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}${symbol}${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}${symbol}${(abs / 1_000).toFixed(1)}k`;
  return `${sign}${symbol}${abs.toFixed(2)}`;
}

export function fmtNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtPctRaw(value: number | null | undefined, digits = 1): string {
  // for values already expressed in percent (e.g. change_pct = -90.6)
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}%`;
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function fmtUsd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `$${value.toFixed(value < 1 ? 6 : 2)}`;
}

/** Map a governance status (SUPPORTED / ABSTAIN / WEAK / …) to a chip class. */
export function statusClass(status: string | null | undefined): string {
  switch ((status ?? '').toUpperCase()) {
    case 'ABSTAIN':
      return 'st-abstain';
    case 'WEAK':
    case 'WEAK_DRIVER':
      return 'st-weak';
    case 'SUPPORTED':
      return 'st-supported';
    case 'CONTRADICTED':
      return 'st-contradicted';
    default:
      return 'st-other';
  }
}

/** Minimal markdown renderer: **bold**, headings via lines. */
export function renderStory(text: string): string {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.+?)`/g, '<code>$1</code>');
}