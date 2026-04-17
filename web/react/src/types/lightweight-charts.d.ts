// Type stub for lightweight-charts - install the package for full functionality
declare module 'lightweight-charts' {
  export interface ChartOptions {
    width?: number;
    height?: number;
    layout?: {
      background?: { color?: string };
      textColor?: string;
    };
    grid?: {
      vertLines?: { color?: string };
      horzLines?: { color?: string };
    };
    crosshair?: { mode?: number };
    rightPriceScale?: { borderColor?: string };
    timeScale?: { borderColor?: string };
  }

  export interface LineSeriesOptions {
    color?: string;
    lineWidth?: number;
  }

  export interface PricePoint {
    time: number;
    value: number;
  }

  export interface LineSeries {
    update(point: PricePoint): void;
  }

  export interface Chart {
    addLineSeries(options?: LineSeriesOptions): LineSeries;
    remove(): void;
  }

  export function createChart(container: HTMLElement, options?: ChartOptions): Chart;
}
