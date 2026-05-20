/**
 * TradingSettingsTab - Trading settings configuration
 * 
 * Trading settings section of Settings view.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

import { validateLeverage } from '../../utils/validators';
import type { TradingSettings } from './types';

interface TradingSettingsTabProps {
  tradingSettings: TradingSettings;
  setTradingSettings: (settings: TradingSettings) => void;
}

export function TradingSettingsTab({ tradingSettings, setTradingSettings }: TradingSettingsTabProps) {
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white">Trading Settings</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor="default-order-size" className="block text-sm font-medium text-slate-400 mb-2">Default Order Size</label>
          <input aria-label="Default Order Size"
            id="default-order-size"
            name="defaultOrderSize"
            type="number"
            title="Enter default order size"
            placeholder="Default order size"
            value={tradingSettings.defaultOrderSize}
            onChange={(e) => setTradingSettings({ ...tradingSettings, defaultOrderSize: Number(e.target.value) })}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="max-leverage" className="block text-sm font-medium text-slate-400 mb-2">Max Leverage</label>
          <input aria-label="Max Leverage"
            id="max-leverage"
            name="maxLeverage"
            type="number"
            title="Enter maximum leverage"
            placeholder="Max leverage"
            value={tradingSettings.maxLeverage}
            onChange={(e) => {
              const value = Number(e.target.value);
              const validation = validateLeverage(value);
              if (validation.valid) {
                setTradingSettings({ ...tradingSettings, maxLeverage: value });
              }
            }}
            step="0.1"
            min="1"
            max="100"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="stop-loss" className="block text-sm font-medium text-slate-400 mb-2">Stop Loss (%)</label>
          <input aria-label="Stop Loss (%)"
            id="stop-loss"
            name="stopLoss"
            type="number"
            title="Enter stop loss percentage"
            placeholder="Stop loss %"
            value={tradingSettings.stopLossPercent}
            onChange={(e) => setTradingSettings({ ...tradingSettings, stopLossPercent: Number(e.target.value) })}
            step="0.1"
            min="0"
            max="100"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="take-profit" className="block text-sm font-medium text-slate-400 mb-2">Take Profit (%)</label>
          <input aria-label="Take Profit (%)"
            id="take-profit"
            name="takeProfit"
            type="number"
            title="Enter take profit percentage"
            placeholder="Take profit %"
            value={tradingSettings.takeProfitPercent}
            onChange={(e) => setTradingSettings({ ...tradingSettings, takeProfitPercent: Number(e.target.value) })}
            step="0.1"
            min="0"
            max="100"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="max-position-size" className="block text-sm font-medium text-slate-400 mb-2">Max Position Size</label>
          <input aria-label="Max Position Size"
            id="max-position-size"
            name="maxPositionSize"
            type="number"
            title="Enter maximum position size"
            placeholder="Max position size"
            value={tradingSettings.maxPositionSize}
            onChange={(e) => setTradingSettings({ ...tradingSettings, maxPositionSize: Number(e.target.value) })}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          />
        </div>

        <div>
          <label htmlFor="trading-refresh-interval" className="block text-sm font-medium text-slate-400 mb-2">Auto Refresh Interval (ms)</label>
          <select aria-label="Auto Refresh Interval (ms)"
            id="trading-refresh-interval"
            name="refreshInterval"
            title="Select auto refresh interval"
            value={tradingSettings.refreshInterval}
            onChange={(e) => setTradingSettings({ ...tradingSettings, refreshInterval: Number(e.target.value) })}
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
          >
            <option value={1000}>1 second</option>
            <option value={5000}>5 seconds</option>
            <option value={10000}>10 seconds</option>
            <option value={30000}>30 seconds</option>
          </select>
        </div>
      </div>

      <div className="space-y-4">
        <label className="flex items-center gap-3">
          <input aria-label="Trading Settings"
            id="confirm-orders"
            name="confirmOrders"
            type="checkbox"
            checked={tradingSettings.confirmOrders}
            onChange={(e) => setTradingSettings({ ...tradingSettings, confirmOrders: e.target.checked })}
            className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-white">Confirm orders before execution</span>
        </label>

        <label className="flex items-center gap-3">
          <input aria-label="Confirm orders before execution"
            id="show-advanced-options"
            name="showAdvancedOptions"
            type="checkbox"
            checked={tradingSettings.showAdvancedOptions}
            onChange={(e) => setTradingSettings({ ...tradingSettings, showAdvancedOptions: e.target.checked })}
            className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-white">Show advanced trading options</span>
        </label>

        <label className="flex items-center gap-3">
          <input aria-label="Show advanced trading options"
            id="auto-refresh"
            name="autoRefresh"
            type="checkbox"
            checked={tradingSettings.autoRefresh}
            onChange={(e) => setTradingSettings({ ...tradingSettings, autoRefresh: e.target.checked })}
            className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          <span className="text-white">Auto-refresh trading data</span>
        </label>
      </div>
    </div>
  );
}
