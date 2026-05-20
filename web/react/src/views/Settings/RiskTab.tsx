/**
 * RiskTab - Risk management parameters
 * 
 * Risk parameters section of Settings view.
 * 
 * Tier 4: Settings.tsx Split (953→4 files)
 */

export function RiskTab() {
  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white">Risk Management Parameters</h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <label htmlFor="max-portfolio-risk" className="block text-sm font-medium text-slate-400 mb-2">Max Portfolio Risk (%)</label>
          <input aria-label="Max Portfolio Risk (%)"
            id="max-portfolio-risk"
            name="maxPortfolioRisk"
            type="number"
            min="1"
            max="100"
            defaultValue="25"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="25"
          />
        </div>

        <div>
          <label htmlFor="max-position-size-risk" className="block text-sm font-medium text-slate-400 mb-2">Max Position Size (%)</label>
          <input aria-label="Max Position Size (%)"
            id="max-position-size-risk"
            name="maxPositionSizeRisk"
            type="number"
            min="1"
            max="50"
            defaultValue="10"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="10"
          />
        </div>

        <div>
          <label htmlFor="stop-loss-default" className="block text-sm font-medium text-slate-400 mb-2">Stop Loss Default (%)</label>
          <input aria-label="Stop Loss Default (%)"
            id="stop-loss-default"
            name="stopLossDefault"
            type="number"
            min="1"
            max="20"
            step="0.5"
            defaultValue="5"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="5"
          />
        </div>

        <div>
          <label htmlFor="max-drawdown" className="block text-sm font-medium text-slate-400 mb-2">Max Drawdown Limit (%)</label>
          <input aria-label="Max Drawdown Limit (%)"
            id="max-drawdown"
            name="maxDrawdown"
            type="number"
            min="5"
            max="50"
            defaultValue="15"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="15"
          />
        </div>

        <div>
          <label htmlFor="max-correlation" className="block text-sm font-medium text-slate-400 mb-2">Max Correlation</label>
          <input aria-label="Max Correlation"
            id="max-correlation"
            name="maxCorrelation"
            type="number"
            min="0"
            max="1"
            step="0.05"
            defaultValue="0.7"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="0.7"
          />
        </div>

        <div>
          <label htmlFor="var-confidence" className="block text-sm font-medium text-slate-400 mb-2">VaR Confidence Level (%)</label>
          <input aria-label="VaR Confidence Level (%)"
            id="var-confidence"
            name="varConfidence"
            type="number"
            min="90"
            max="99"
            defaultValue="95"
            className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500"
            placeholder="95"
          />
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-md font-medium text-white">Risk Controls</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="flex items-center gap-3">
            <input aria-label="Risk Controls"
              id="auto-stop-losses"
              name="autoStopLosses"
              type="checkbox"
              defaultChecked
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Enable automatic stop losses</span>
          </label>
          <label className="flex items-center gap-3">
            <input aria-label="Enable automatic stop losses"
              id="position-size-limits"
              name="positionSizeLimits"
              type="checkbox"
              defaultChecked
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Enable position size limits</span>
          </label>
          <label className="flex items-center gap-3">
            <input aria-label="Enable position size limits"
              id="correlation-checks"
              name="correlationChecks"
              type="checkbox"
              defaultChecked
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Enable correlation checks</span>
          </label>
          <label className="flex items-center gap-3">
            <input aria-label="Enable correlation checks"
              id="pause-high-volatility"
              name="pauseHighVolatility"
              type="checkbox"
              className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
            />
            <span className="text-white">Pause trading on high volatility</span>
          </label>
        </div>
      </div>
    </div>
  );
}
