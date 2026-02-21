/**
 * Local Orderbook State Manager
 * Maintains orderbook state from Kalshi snapshots and deltas
 * 
 * Price conventions:
 * - YES side: bid at price/100 (dollar probability)
 * - NO side: ask at (100-price)/100
 * 
 * Sequence numbers prevent out-of-order updates
 */

type Side = "yes" | "no";

interface LocalBook {
  seq: number;
  yesLevels: Map<number, number>; // price_int -> size
  noLevels: Map<number, number>;
  lastUpdate: number;
}

export interface BestQuote {
  bestBid: number | null;  // Dollar probability (0-1)
  bestAsk: number | null;
  mid: number | null;
  spread: number | null;
  bidDepth: number;
  askDepth: number;
  imbalance: number;
}

export class LocalOrderbook {
  private books = new Map<string, LocalBook>();

  /**
   * Apply initial snapshot from Kalshi
   */
  applySnapshot(
    ticker: string,
    yes: [number, number][],
    no: [number, number][],
    seq: number
  ): void {
    const yesLevels = new Map<number, number>();
    const noLevels = new Map<number, number>();

    yes.forEach(([price, qty]) => {
      if (qty > 0) yesLevels.set(price, qty);
    });

    no.forEach(([price, qty]) => {
      if (qty > 0) noLevels.set(price, qty);
    });

    this.books.set(ticker, {
      seq,
      yesLevels,
      noLevels,
      lastUpdate: Date.now(),
    });

    console.log(
      `[Orderbook] Snapshot applied: ${ticker} seq=${seq} ` +
      `yes_levels=${yesLevels.size} no_levels=${noLevels.size}`
    );
  }

  /**
   * Apply incremental delta from Kalshi
   * Ignores out-of-order updates (seq <= current)
   */
  applyDelta(
    ticker: string,
    side: Side,
    price: number,
    delta: number,
    seq: number
  ): boolean {
    const book = this.books.get(ticker);

    if (!book) {
      console.warn(`[Orderbook] Delta for unknown book: ${ticker}`);
      return false;
    }

    // Reject out-of-order or duplicate updates
    if (seq <= book.seq) {
      console.warn(
        `[Orderbook] Out-of-order delta ignored: ${ticker} ` +
        `seq=${seq} current=${book.seq}`
      );
      return false;
    }

    // Apply delta to appropriate side
    const levels = side === "yes" ? book.yesLevels : book.noLevels;
    const prev = levels.get(price) ?? 0;
    const next = prev + delta;

    if (next <= 0) {
      // Remove level if size becomes zero or negative
      levels.delete(price);
    } else {
      levels.set(price, next);
    }

    book.seq = seq;
    book.lastUpdate = Date.now();

    return true;
  }

  /**
   * Get best YES bid price (integer 0-100)
   */
  getBestYesBid(ticker: string): number | null {
    const book = this.books.get(ticker);
    if (!book || !book.yesLevels.size) return null;
    return Math.max(...Array.from(book.yesLevels.keys()));
  }

  /**
   * Get best NO bid price (integer 0-100)
   */
  getBestNoBid(ticker: string): number | null {
    const book = this.books.get(ticker);
    if (!book || !book.noLevels.size) return null;
    return Math.max(...Array.from(book.noLevels.keys()));
  }

  /**
   * Get best bid/ask quotes for a market
   * 
   * Returns prices in dollar probability space (0-1)
   */
  toBestBidAsk(ticker: string): BestQuote {
    const book = this.books.get(ticker);

    if (!book) {
      return {
        bestBid: null,
        bestAsk: null,
        mid: null,
        spread: null,
        bidDepth: 0,
        askDepth: 0,
        imbalance: 0,
      };
    }

    // YES levels = bids (buy YES)
    const yesPrices = Array.from(book.yesLevels.entries())
      .filter(([_, qty]) => qty > 0)
      .map(([price]) => price);

    // NO levels = asks (buy NO = sell YES)
    const noPrices = Array.from(book.noLevels.entries())
      .filter(([_, qty]) => qty > 0)
      .map(([price]) => price);

    // Best YES = highest price on YES side
    const bestYesInt = yesPrices.length ? Math.max(...yesPrices) : null;
    // Best NO = lowest price on NO side
    const bestNoInt = noPrices.length ? Math.min(...noPrices) : null;

    // Convert to dollar probabilities
    // YES price: bid at price/100
    // NO price: ask at (100-price)/100 (since NO at X = YES at 100-X)
    const bestBid = bestYesInt !== null ? bestYesInt / 100 : null;
    const bestAsk = bestNoInt !== null ? (100 - bestNoInt) / 100 : null;

    // Compute mid and spread
    let mid: number | null = null;
    let spread: number | null = null;

    if (bestBid !== null && bestAsk !== null) {
      mid = (bestBid + bestAsk) / 2;
      spread = bestAsk - bestBid;
    }

    // Compute depth (total size at best levels)
    const bidDepth = bestYesInt !== null
      ? (book.yesLevels.get(bestYesInt) ?? 0)
      : 0;
    const askDepth = bestNoInt !== null
      ? (book.noLevels.get(bestNoInt) ?? 0)
      : 0;

    // Imbalance: positive = more bid depth, negative = more ask depth
    const totalDepth = bidDepth + askDepth;
    const imbalance = totalDepth > 0
      ? (bidDepth - askDepth) / totalDepth
      : 0;

    return {
      bestBid,
      bestAsk,
      mid,
      spread,
      bidDepth,
      askDepth,
      imbalance,
    };
  }

  /**
   * Get full depth curve for a side (up to N levels)
   */
  getDepthCurve(ticker: string, side: Side, maxLevels: number = 10): [number, number][] {
    const book = this.books.get(ticker);
    if (!book) return [];

    const levels = side === "yes" ? book.yesLevels : book.noLevels;
    const entries = Array.from(levels.entries())
      .filter(([_, qty]) => qty > 0)
      .sort(([a], [b]) => {
        // YES: descending (best = highest)
        // NO: ascending (best = lowest)
        return side === "yes" ? b - a : a - b;
      })
      .slice(0, maxLevels);

    // Convert to dollar probabilities
    return entries.map(([price, qty]) => {
      const dollarPrice = side === "yes"
        ? price / 100
        : (100 - price) / 100;
      return [dollarPrice, qty];
    });
  }

  /**
   * Check if book is stale (no updates in X ms)
   */
  isStale(ticker: string, thresholdMs: number = 30000): boolean {
    const book = this.books.get(ticker);
    if (!book) return true;
    return Date.now() - book.lastUpdate > thresholdMs;
  }

  /**
   * Get current sequence number for a market
   */
  getSeq(ticker: string): number | null {
    const book = this.books.get(ticker);
    return book?.seq ?? null;
  }

  /**
   * Clear book for a market (e.g., on reconnect)
   */
  clear(ticker: string): void {
    this.books.delete(ticker);
  }

  /**
   * Get all tracked tickers
   */
  getTickers(): string[] {
    return Array.from(this.books.keys());
  }
}
