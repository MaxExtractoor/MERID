"""One-shot script to migrate hardcoded fetch URLs in components to API_ENDPOINTS constants."""
import re
from pathlib import Path

COMPS = Path(__file__).resolve().parent.parent / "web" / "react" / "src" / "components"

# Map: hardcoded URL -> API_ENDPOINTS constant name
URL_MAP = {
    "/api/v1/risk-metrics/agents": "API_ENDPOINTS.RISK_AGENTS",
    "/api/v1/signals/alerts/history": "API_ENDPOINTS.SIGNALS_ALERTS_HISTORY",
    "/api/v1/analytics/overview": "API_ENDPOINTS.ANALYTICS_OVERVIEW",
    "/api/v1/arbitrage/opportunities": "API_ENDPOINTS.ARBITRAGE_OPPORTUNITIES",
    "/api/v1/arbitrage/execute": "API_ENDPOINTS.ARBITRAGE_EXECUTE",
    "/api/v1/arbitrage/scanner": "API_ENDPOINTS.ARBITRAGE_SCANNER",
    "/api/v1/blockchain/compliance": "API_ENDPOINTS.BLOCKCHAIN_COMPLIANCE",
    "/api/v1/blockchain/health": "API_ENDPOINTS.BLOCKCHAIN_HEALTH",
    "/api/v1/consensus/status": "API_ENDPOINTS.CONSENSUS_STATUS",
    "/api/v1/consensus/plans": "API_ENDPOINTS.CONSENSUS_PLANS",
    "/api/v1/consensus/votes": "API_ENDPOINTS.CONSENSUS_VOTES",
    "/api/v1/consensus/metrics": "API_ENDPOINTS.CONSENSUS_METRICS",
    "/api/v1/consensus/opinions": "API_ENDPOINTS.CONSENSUS_OPINIONS",
    "/api/prime/status": "API_ENDPOINTS.PRIME_STATUS",
    "/api/v1/data/freshness": "API_ENDPOINTS.DATA_FRESHNESS",
    "/api/v1/us-compliant/drift-signals": "API_ENDPOINTS.DRIFT_SIGNALS",
    "/api/v1/explainability/decisions": "API_ENDPOINTS.EXPLAINABILITY_DECISIONS",
    "/api/v1/portfolio/summary": "API_ENDPOINTS.PORTFOLIO_SUMMARY",
    "/api/portfolio/summary": "API_ENDPOINTS.PORTFOLIO_LIVE",
    "/api/v1/pipeline/summary": "API_ENDPOINTS.PIPELINE_SUMMARY",
    "/api/v1/pipeline/venues": "API_ENDPOINTS.PIPELINE_VENUES",
    "/api/v1/pipeline/venue/mode": "API_ENDPOINTS.PIPELINE_VENUE_MODE",
    "/api/v1/pipeline/leaderboard": "API_ENDPOINTS.PIPELINE_LEADERBOARD",
    "/api/v1/quadratic-funding/proposals": "API_ENDPOINTS.QUADRATIC_FUNDING_PROPOSALS",
    "/api/v1/quadratic-funding/rounds/summary": "API_ENDPOINTS.QUADRATIC_FUNDING_ROUNDS",
    "/api/v1/reflection/summary": "API_ENDPOINTS.REFLECTION_SUMMARY",
    "/api/v1/reflection/reflections": "API_ENDPOINTS.REFLECTION_LIST",
    "/api/v1/simulation/status": "API_ENDPOINTS.SIMULATION_STATUS",
    "/api/v1/simulation/reset": "API_ENDPOINTS.SIMULATION_RESET",
    "/api/v1/simulation/save": "API_ENDPOINTS.SIMULATION_SAVE",
    "/api/v1/swarm/status": "API_ENDPOINTS.SWARM_STATUS",
    "/api/v1/notifications/read-all": "API_ENDPOINTS.NOTIFICATIONS_READ_ALL",
    "/api/v1/notifications/telegram/log": "API_ENDPOINTS.NOTIFICATIONS_TELEGRAM_LOG",
    "/api/v1/notifications": "API_ENDPOINTS.NOTIFICATIONS",
    "/api/v1/risk/halt-status": "API_ENDPOINTS.RISK_HALT_STATUS",
    "/api/v1/risk/staleness": "API_ENDPOINTS.RISK_STALENESS",
    "/api/v1/risk/halt": "API_ENDPOINTS.RISK_HALT",
    "/api/v1/risk/resume": "API_ENDPOINTS.RISK_RESUME",
    "/api/v1/orchestrator/summary": "API_ENDPOINTS.ORCHESTRATOR_SUMMARY",
    "/api/v1/rewards/leaderboard": "API_ENDPOINTS.REWARDS_LEADERBOARD",
}

IMPORT_LINE = "import { API_ENDPOINTS } from '../config/constants';"
CHART_IMPORT = "import { API_ENDPOINTS } from '../../config/constants';"


def migrate():
    changed = []
    for f in sorted(COMPS.rglob("*.tsx")):
        if "__tests__" in str(f):
            continue
        text = f.read_text(encoding="utf-8")
        original = text

        has_match = any(url in text for url in URL_MAP)
        if not has_match:
            continue

        # Replace URLs (longest first to avoid partial matches)
        for url in sorted(URL_MAP.keys(), key=len, reverse=True):
            const = URL_MAP[url]
            for q in ["'", '"', "`"]:
                # With query params: '/api/v1/foo?bar=baz' -> API_ENDPOINTS.FOO + '?bar=baz'
                pat = re.compile(re.escape(q + url) + r"(\?[^" + q + r"]+)" + re.escape(q))
                text = pat.sub(const + " + '" + r"\1" + "'", text)
                # Without query params
                text = text.replace(q + url + q, const)

        if text != original:
            # Add import if not present
            if "API_ENDPOINTS" not in original:
                is_chart = "/charts/" in str(f).replace("\\", "/")
                imp = CHART_IMPORT if is_chart else IMPORT_LINE
                lines = text.split("\n")
                last_import = 0
                for i, line in enumerate(lines):
                    if line.startswith("import ") or (line.startswith("} from ") and i > 0):
                        last_import = i
                lines.insert(last_import + 1, imp)
                text = "\n".join(lines)

            f.write_text(text, encoding="utf-8")
            changed.append(f.name)

    print(f"Migrated {len(changed)} components:")
    for c in changed:
        print(f"  {c}")


if __name__ == "__main__":
    migrate()
