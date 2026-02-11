/**
 * Hook for fetching stocks, forex, and commodities market data
 */

import { useState, useEffect } from 'react';
import { API_ENDPOINTS, DEFAULTS } from '../config/constants';

export interface StockData {
  symbol: string;
  price: number;
  bid: number;
  ask: number;
  volume: number;
  change_pct: number;
  timestamp: number;
  source: string;
  market_cap?: number;
  pe_ratio?: number;
}

export interface ForexData {
  pair: string;
  rate: number;
  bid: number;
  ask: number;
  timestamp: number;
  source: string;
}

export interface CommodityData {
  symbol: string;
  name: string;
  price: number;
  unit: string;
  change_pct: number;
  timestamp: number;
  source: string;
}

interface StocksResponse {
  stocks: StockData[];
  count: number;
  timestamp: number;
}

interface ForexResponse {
  forex: ForexData[];
  count: number;
  timestamp: number;
}

interface CommoditiesResponse {
  commodities: CommodityData[];
  count: number;
  timestamp: number;
}

export function useStocks(symbols?: string) {
  const [data, setData] = useState<StockData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchStocks = async () => {
      try {
        const url = symbols 
          ? `${API_ENDPOINTS.MARKETS_STOCKS}?symbols=${symbols}`
          : API_ENDPOINTS.MARKETS_STOCKS;
        
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch stocks');
        
        const result: StocksResponse = await response.json();
        setData(result.stocks);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchStocks();
    const interval = setInterval(fetchStocks, DEFAULTS.POLLING_INTERVALS.FAST_REFRESH); // Update every 5s
    return () => clearInterval(interval);
  }, [symbols]);

  return { data, loading, error };
}

export function useForex(pairs?: string) {
  const [data, setData] = useState<ForexData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchForex = async () => {
      try {
        const url = pairs 
          ? `${API_ENDPOINTS.MARKETS_FOREX}?pairs=${pairs}`
          : API_ENDPOINTS.MARKETS_FOREX;
        
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch forex');
        
        const result: ForexResponse = await response.json();
        setData(result.forex);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchForex();
    const interval = setInterval(fetchForex, DEFAULTS.POLLING_INTERVALS.STANDARD); // Update every 10s
    return () => clearInterval(interval);
  }, [pairs]);

  return { data, loading, error };
}

export function useCommodities(symbols?: string) {
  const [data, setData] = useState<CommodityData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchCommodities = async () => {
      try {
        const url = symbols 
          ? `${API_ENDPOINTS.MARKETS_COMMODITIES}?symbols=${symbols}`
          : API_ENDPOINTS.MARKETS_COMMODITIES;
        
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch commodities');
        
        const result: CommoditiesResponse = await response.json();
        setData(result.commodities);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchCommodities();
    const interval = setInterval(fetchCommodities, DEFAULTS.POLLING_INTERVALS.RISK); // Update every 30s
    return () => clearInterval(interval);
  }, [symbols]);

  return { data, loading, error };
}

export function useAllMarkets() {
  const [stocks, setStocks] = useState<StockData[]>([]);
  const [forex, setForex] = useState<ForexData[]>([]);
  const [commodities, setCommodities] = useState<CommodityData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchAllMarkets = async () => {
      try {
        const response = await fetch(API_ENDPOINTS.MARKETS_ALL);
        if (!response.ok) throw new Error('Failed to fetch markets');
        
        const result = await response.json();
        setStocks(result.stocks || []);
        setForex(result.forex || []);
        setCommodities(result.commodities || []);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    fetchAllMarkets();
    const interval = setInterval(fetchAllMarkets, DEFAULTS.POLLING_INTERVALS.STANDARD); // Update every 10s
    return () => clearInterval(interval);
  }, []);

  return { stocks, forex, commodities, loading, error };
}
