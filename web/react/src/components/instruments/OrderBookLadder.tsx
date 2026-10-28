/**
 * OrderBookLadder — DOM orderbook ladder: asks stacked above a spread row,
 * bids below, intensity bars scaled by size. Click a row -> onPriceSelect.
 * Virtualized with react-window v2 (`List` + rowComponent/rowProps) when
 * total levels exceed 30.
 */

import { memo, useMemo } from 'react';
import type { CSSProperties } from 'react';
import { List } from 'react-window';
import type { RowComponentProps } from 'react-window';
import { cx } from '../../agents/format';

export interface BookLevel {
  /** price in cents (0-100) — callers normalize dollars -> cents. */
  price: number;
  size: number;
}

interface LadderRowData {
  kind: 'ask' | 'bid' | 'spread';
  price?: number;
  size?: number;
  cum?: number;
  frac?: number;
  text?: string;
}

interface RowExtraProps {
  rows: LadderRowData[];
  onPriceSelect?: (price: number) => void;
}

function rowCls(kind: LadderRowData['kind'], clickable: boolean): string {
  return cx(
    'relative flex items-center w-full h-full text-[10px] tabular-nums leading-none',
    kind === 'spread' ? 'bg-slate-800/80 text-slate-400 font-bold justify-center' : 'hover:bg-slate-800/70',
    kind === 'ask' && 'text-red-300',
    kind === 'bid' && 'text-emerald-300',
    clickable && 'cursor-pointer focus:outline-none focus:ring-1 focus:ring-inset focus:ring-blue-500/60',
  );
}

function RowBody({ row }: { row: LadderRowData }) {
  if (row.kind === 'spread') {
    return <span className="w-full text-center tracking-widest">{row.text}</span>;
  }
  return (
    <>
      {/* intensity bar */}
      <span
        className={cx('absolute inset-y-0 right-0', row.kind === 'bid' ? 'bg-emerald-500/15' : 'bg-red-500/15')}
        style={{ width: `${(row.frac ?? 0) * 100}%` }}
        aria-hidden="true"
      />
      <span className="relative z-10 w-16 text-right pr-2 font-bold">{row.price?.toFixed(0)}c</span>
      <span className="relative z-10 flex-1 text-right pr-2 text-slate-300">{row.size}</span>
      <span className="relative z-10 w-14 text-right pr-2 text-slate-500">{row.cum}</span>
    </>
  );
}

/** react-window v2 row component (receives index/style + rowProps). */
function LadderRow({ index, style, rows, onPriceSelect }: RowComponentProps<RowExtraProps>) {
  const row = rows[index];
  if (row.kind === 'spread') {
    return (
      <div style={style} className={rowCls('spread', false)} role="row">
        <RowBody row={row} />
      </div>
    );
  }
  const clickable = !!onPriceSelect;
  const price = row.price;
  return (
    <button
      type="button"
      style={style}
      className={rowCls(row.kind, clickable)}
      onClick={onPriceSelect && price != null ? () => onPriceSelect(price) : undefined}
      disabled={!clickable}
      aria-label={`${row.kind} ${row.price}c size ${row.size}`}
    >
      <RowBody row={row} />
    </button>
  );
}

/* ------------------------------------------------------------------ */

interface OrderBookLadderProps {
  bids?: BookLevel[];
  asks?: BookLevel[];
  /** max levels per side before truncation. */
  maxLevels?: number;
  rowHeight?: number;
  height?: number;
  onPriceSelect?: (price: number) => void;
  className?: string;
}

const VIRT_THRESHOLD = 30;

export const OrderBookLadder = memo(function OrderBookLadder({
  bids,
  asks,
  maxLevels = 16,
  rowHeight = 20,
  height = 320,
  onPriceSelect,
  className = '',
}: OrderBookLadderProps) {
  const rows = useMemo<LadderRowData[]>(() => {
    const cleanBids = (bids ?? [])
      .filter((l) => Number.isFinite(l.price) && Number.isFinite(l.size))
      .sort((a, b) => b.price - a.price)
      .slice(0, maxLevels);
    const cleanAsks = (asks ?? [])
      .filter((l) => Number.isFinite(l.price) && Number.isFinite(l.size))
      .sort((a, b) => a.price - b.price)
      .slice(0, maxLevels);
    const maxSize = Math.max(1, ...cleanBids.map((l) => l.size), ...cleanAsks.map((l) => l.size));

    const out: LadderRowData[] = [];
    let cum = 0;
    // asks rendered worst -> best so the best ask sits directly above spread
    const ascAsks = [...cleanAsks].reverse();
    const askCums: number[] = [];
    for (let i = ascAsks.length - 1; i >= 0; i--) {
      cum += ascAsks[i].size;
      askCums[i] = cum;
    }
    ascAsks.forEach((l, i) => {
      out.push({ kind: 'ask', price: l.price, size: l.size, cum: askCums[i], frac: l.size / maxSize });
    });

    const bestBid = cleanBids[0]?.price;
    const bestAsk = cleanAsks[0]?.price;
    const spreadTxt = bestBid != null && bestAsk != null
      ? `spread ${(bestAsk - bestBid).toFixed(0)}c · mid ${((bestAsk + bestBid) / 2).toFixed(1)}c`
      : 'spread n/a';
    out.push({ kind: 'spread', text: spreadTxt });

    cum = 0;
    for (const l of cleanBids) {
      cum += l.size;
      out.push({ kind: 'bid', price: l.price, size: l.size, cum, frac: l.size / maxSize });
    }
    return out;
  }, [bids, asks, maxLevels]);

  if (!rows.length || rows.length === 1) {
    return (
      <div
        className={cx('flex items-center justify-center rounded-lg border border-dashed border-slate-800 text-[10px] uppercase tracking-widest text-slate-600', className)}
        style={{ height }}
      >
        no book data
      </div>
    );
  }

  const extra: RowExtraProps = { rows, onPriceSelect };
  const listH = Math.min(height, rows.length * rowHeight);

  // header row for plain render (virtual list has its own implicit layout)
  const header = (
    <div className="flex items-center text-[8px] uppercase tracking-widest text-slate-600 tabular-nums px-0 pb-1">
      <span className="w-16 text-right pr-2">price</span>
      <span className="flex-1 text-right pr-2">size</span>
      <span className="w-14 text-right pr-2">cum</span>
    </div>
  );

  return (
    <div className={className}>
      {header}
      {rows.length > VIRT_THRESHOLD ? (
        <List
          rowComponent={LadderRow}
          rowCount={rows.length}
          rowHeight={rowHeight}
          rowProps={extra}
          style={{ height: listH }}
          overscanCount={6}
        />
      ) : (
        <div className="overflow-y-auto rounded" style={{ maxHeight: listH }}>
          {rows.map((row, i) => {
            const style: CSSProperties = { height: rowHeight };
            if (row.kind === 'spread') {
              return (
                <div key={`s-${i}`} style={style} className={rowCls('spread', false)}>
                  <RowBody row={row} />
                </div>
              );
            }
            const price = row.price;
            return (
              <button
                key={`${row.kind}-${row.price}-${i}`}
                type="button"
                style={style}
                className={rowCls(row.kind, !!onPriceSelect)}
                disabled={!onPriceSelect}
                onClick={onPriceSelect && price != null ? () => onPriceSelect(price) : undefined}
                aria-label={`${row.kind} ${row.price}c size ${row.size}`}
              >
                <RowBody row={row} />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
});

export default OrderBookLadder;
