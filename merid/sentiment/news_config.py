"""News & Hashtag Configuration — Category/asset-aware ingestion config.

Central registry of keywords, hashtags, cashtags, subreddits, and target
X/Twitter account IDs for every Kalshi category and crypto asset.

All scraping and sentiment modules import from here so coverage can be
updated in one place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple


# ── Crypto assets ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CryptoAssetConfig:
    symbol: str
    names: Tuple[str, ...]
    hashtags: Tuple[str, ...]
    cashtags: Tuple[str, ...]
    subreddits: Tuple[str, ...]
    newsapi_keywords: Tuple[str, ...]
    target_x_handles: Tuple[str, ...]  # X/Twitter handles (no @)


CRYPTO_ASSETS: Dict[str, CryptoAssetConfig] = {
    "BTC": CryptoAssetConfig(
        symbol="BTC",
        names=("Bitcoin", "BTC"),
        hashtags=(
            "#BTC", "#Bitcoin", "#BTCUSD", "#BitcoinPrice",
            "#BitcoinNews", "#BTCETF", "#BitcoinETF", "#HODL",
            "#BitcoinHalving", "#Sats",
        ),
        cashtags=("$BTC",),
        subreddits=("Bitcoin", "btc", "CryptoCurrency", "BitcoinMarkets"),
        newsapi_keywords=(
            "Bitcoin", "BTC price", "Bitcoin ETF", "Bitcoin halving",
            "Bitcoin whale", "Bitcoin mining", "Satoshi",
        ),
        target_x_handles=(
            "glassnode", "ki_young_ju", "woonomic", "CryptoQuant_CEO",
            "DocumentingBTC", "BitcoinMagazine", "WhalePanda",
            "coinbureau", "Coinglass_com",
        ),
    ),
    "ETH": CryptoAssetConfig(
        symbol="ETH",
        names=("Ethereum", "ETH", "Ether"),
        hashtags=(
            "#ETH", "#Ethereum", "#ETHUSD", "#EthereumNews",
            "#L2", "#DeFi", "#EthereumETF", "#Staking",
            "#EIP", "#EthDenver",
        ),
        cashtags=("$ETH",),
        subreddits=("ethereum", "ethfinance", "CryptoCurrency", "ethtrader"),
        newsapi_keywords=(
            "Ethereum", "ETH price", "Ethereum ETF", "DeFi",
            "Layer 2", "Ethereum staking", "EIP",
        ),
        target_x_handles=(
            "VitalikButerin", "ethereumJoseph", "sassal0x",
            "evan_van_ness", "EthereumFdn", "defipulse",
        ),
    ),
    "SOL": CryptoAssetConfig(
        symbol="SOL",
        names=("Solana", "SOL"),
        hashtags=(
            "#SOL", "#Solana", "#SOLUSD", "#SolanaSeason",
            "#SolanaEcosystem", "#SolanaNFT", "#Breakpoint",
        ),
        cashtags=("$SOL",),
        subreddits=("solana", "CryptoCurrency"),
        newsapi_keywords=(
            "Solana", "SOL price", "Solana ecosystem",
            "Solana NFT", "Solana DeFi",
        ),
        target_x_handles=(
            "aeyakovenko", "rajgokal", "solana", "SolanaFloor",
        ),
    ),
    "DOGE": CryptoAssetConfig(
        symbol="DOGE",
        names=("Dogecoin", "DOGE"),
        hashtags=(
            "#DOGE", "#Dogecoin", "#DOGEUSD", "#DogecoinToTheMoon",
            "#DogeArmy", "#1Doge1Dollar",
        ),
        cashtags=("$DOGE",),
        subreddits=("dogecoin", "CryptoCurrency"),
        newsapi_keywords=(
            "Dogecoin", "DOGE price", "Elon Musk Dogecoin",
        ),
        target_x_handles=(
            "BillyM2k", "dogecoin", "elonmusk",
        ),
    ),
    "XRP": CryptoAssetConfig(
        symbol="XRP",
        names=("XRP", "Ripple"),
        hashtags=(
            "#XRP", "#Ripple", "#XRPArmy", "#XRPUSD",
            "#XRPLedger", "#XRPL", "#SEC",
        ),
        cashtags=("$XRP",),
        subreddits=("Ripple", "XRP", "CryptoCurrency"),
        newsapi_keywords=(
            "XRP", "Ripple", "XRP SEC", "Ripple lawsuit",
            "XRP ETF", "XRPL",
        ),
        target_x_handles=(
            "Ripple", "bgarlinghouse", "JoelKatz", "WietseWind",
        ),
    ),
}

# Generic crypto hashtags/keywords (not asset-specific)
GENERIC_CRYPTO_HASHTAGS: Tuple[str, ...] = (
    "#crypto", "#cryptocurrency", "#cryptotrading", "#cryptonews",
    "#web3", "#blockchain", "#altcoins", "#DeFi", "#NFT",
    "#memecoins", "#cryptomarket", "#HODL", "#altseason",
)

GENERIC_CRYPTO_KEYWORDS: Tuple[str, ...] = (
    "crypto", "cryptocurrency", "altcoins", "DeFi", "NFT",
    "memecoins", "blockchain", "web3", "stablecoin",
    "liquidations", "open interest", "funding rates",
    "coinglass", "long squeeze", "short squeeze", "CVD",
)

LIQUIDITY_HASHTAGS: Tuple[str, ...] = (
    "#Coinglass", "#liquidations", "#funding", "#perps",
    "#onchain", "#openinterest", "#CVD",
)


# ── Kalshi category configs ────────────────────────────────────────────────

@dataclass
class CategoryConfig:
    name: str
    kalshi_categories: Tuple[str, ...]   # Kalshi API category slugs
    keywords: Tuple[str, ...]
    hashtags: Tuple[str, ...]
    subreddits: Tuple[str, ...]
    newsapi_keywords: Tuple[str, ...]
    target_x_handles: Tuple[str, ...]
    related_assets: Tuple[str, ...]      # crypto assets that correlate


NEWS_TOPICS: Dict[str, CategoryConfig] = {
    "crypto": CategoryConfig(
        name="Crypto",
        kalshi_categories=("crypto", "cryptocurrency", "bitcoin", "ethereum"),
        keywords=(
            "Bitcoin", "Ethereum", "Solana", "Dogecoin", "XRP",
            "crypto", "cryptocurrency", "altcoin", "DeFi", "NFT",
            "blockchain", "stablecoin", "ETF", "halving",
            "liquidations", "open interest", "funding rates",
            "coinglass", "Glassnode", "IntoTheBlock",
        ),
        hashtags=GENERIC_CRYPTO_HASHTAGS + LIQUIDITY_HASHTAGS + (
            "#BTC", "#ETH", "#SOL", "#DOGE", "#XRP",
            "#BitcoinETF", "#CryptoRegulation",
        ),
        subreddits=(
            "CryptoCurrency", "Bitcoin", "ethereum", "solana",
            "dogecoin", "Ripple", "CryptoMarkets", "BitcoinMarkets",
        ),
        newsapi_keywords=(
            "cryptocurrency", "Bitcoin ETF", "crypto regulation",
            "DeFi protocol", "NFT market", "crypto exchange",
        ),
        target_x_handles=(
            "glassnode", "Coinglass_com", "ki_young_ju",
            "woonomic", "CryptoQuant_CEO", "IntoTheBlock",
            "coinbureau", "DocumentingBTC",
        ),
        related_assets=("BTC", "ETH", "SOL", "DOGE", "XRP"),
    ),

    "politics": CategoryConfig(
        name="Politics",
        kalshi_categories=("politics", "elections", "congress", "presidency"),
        keywords=(
            "election", "elections", "primary", "runoff", "polls",
            "Congress", "Senate", "House", "president", "White House",
            "GOP", "Democrats", "Republicans", "bill", "law",
            "referendum", "ballot", "vote", "polling", "approval rating",
            "POTUS", "midterms", "swing state", "electoral college",
        ),
        hashtags=(
            "#politics", "#election", "#Election2026", "#Vote",
            "#Congress", "#Senate", "#House", "#POTUS",
            "#GOP", "#Democrats", "#Republicans",
            "#Midterms", "#PrimaryElection", "#SwingState",
        ),
        subreddits=(
            "politics", "PoliticalDiscussion", "news",
            "Conservative", "Liberal", "moderatepolitics",
        ),
        newsapi_keywords=(
            "election polls", "Congress vote", "presidential approval",
            "Senate bill", "House vote", "primary election",
            "electoral college", "swing state",
        ),
        target_x_handles=(
            "FiveThirtyEight", "Nate_Cohn", "PredictIt",
            "RealClearNews", "politico", "thehill",
            "AP", "Reuters",
        ),
        related_assets=(),
    ),

    "sports": CategoryConfig(
        name="Sports",
        kalshi_categories=("sports", "nfl", "nba", "mlb", "nhl", "soccer"),
        keywords=(
            "NFL", "NBA", "MLB", "NHL", "Premier League", "World Cup",
            "Super Bowl", "playoffs", "odds", "spread", "injury",
            "quarterback", "championship", "finals", "draft",
            "trade deadline", "free agency", "roster", "standings",
        ),
        hashtags=(
            "#NFL", "#NBA", "#MLB", "#NHL", "#soccer",
            "#WorldCup", "#SuperBowl", "#sportsbetting",
            "#playoffs", "#championship", "#MarchMadness",
            "#NFLDraft", "#NBADraft",
        ),
        subreddits=(
            "nfl", "nba", "baseball", "hockey", "soccer",
            "CFB", "fantasyfootball", "sportsbook",
        ),
        newsapi_keywords=(
            "NFL game", "NBA game", "MLB game", "NHL game",
            "Super Bowl", "NBA Finals", "World Series",
            "sports betting odds", "injury report",
        ),
        target_x_handles=(
            "AdamSchefter", "RapSheet", "wojespn",
            "ShamsCharania", "Ken_Rosenthal",
            "DraftKings", "FanDuel", "BetMGM",
        ),
        related_assets=(),
    ),

    "culture": CategoryConfig(
        name="Culture",
        kalshi_categories=("culture", "entertainment", "awards", "movies", "music"),
        keywords=(
            "Oscars", "Academy Awards", "box office", "opening weekend",
            "Grammy", "Emmy", "Taylor Swift", "concert", "tour",
            "Netflix", "Disney", "Marvel", "streaming", "album",
            "Billboard", "chart", "premiere", "sequel",
        ),
        hashtags=(
            "#Oscars", "#boxoffice", "#movies", "#Netflix",
            "#TaylorSwift", "#music", "#concert", "#Grammy",
            "#Emmy", "#Disney", "#Marvel", "#Hollywood",
            "#Spotify", "#Billboard",
        ),
        subreddits=(
            "movies", "television", "Music", "popculturechat",
            "entertainment", "TaylorSwift", "marvelstudios",
        ),
        newsapi_keywords=(
            "box office", "Academy Awards", "Grammy nominations",
            "Netflix release", "Disney movie", "Taylor Swift",
            "concert tour", "streaming numbers",
        ),
        target_x_handles=(
            "TheAcademy", "GRAMMYs", "boxofficemojo",
            "Variety", "THR", "Deadline",
        ),
        related_assets=(),
    ),

    "economics": CategoryConfig(
        name="Economics",
        kalshi_categories=("economics", "economy", "fed", "inflation", "jobs"),
        keywords=(
            "CPI", "inflation", "jobs report", "payrolls", "unemployment",
            "GDP", "Fed", "FOMC", "interest rates", "hike", "cut",
            "quantitative easing", "recession", "soft landing",
            "credit", "liquidity", "PCE", "PPI", "NFP",
            "Federal Reserve", "Jerome Powell", "Treasury",
            "yield curve", "10-year", "2-year", "spread",
        ),
        hashtags=(
            "#CPI", "#inflation", "#jobsreport", "#NFP",
            "#FOMC", "#Fed", "#recession", "#economy",
            "#FederalReserve", "#interestrates", "#GDP",
            "#unemployment", "#PCE", "#yieldcurve",
        ),
        subreddits=(
            "economics", "economy", "investing",
            "wallstreetbets", "stocks", "finance",
        ),
        newsapi_keywords=(
            "CPI report", "Federal Reserve rate", "jobs report",
            "GDP growth", "inflation data", "FOMC meeting",
            "Jerome Powell", "Treasury yield",
        ),
        target_x_handles=(
            "NickTimiraos", "GregIpWSJ", "federalreserve",
            "BLS_gov", "USTreasury", "economics",
            "RealEconTV", "LizAnnSonders",
        ),
        related_assets=("BTC", "ETH"),
    ),

    "climate": CategoryConfig(
        name="Climate",
        kalshi_categories=("climate", "weather", "environment"),
        keywords=(
            "climate change", "global warming", "carbon", "emissions",
            "CO2", "ESG", "hurricane", "wildfire", "heatwave",
            "drought", "flood", "tornado", "NOAA", "EPA",
            "Paris Agreement", "carbon credits", "net zero",
        ),
        hashtags=(
            "#climate", "#climatechange", "#globalwarming",
            "#emissions", "#ESG", "#ClimateAction",
            "#NetZero", "#CarbonCredits", "#hurricane",
            "#wildfire",
        ),
        subreddits=(
            "climate", "environment", "ClimateOffensive",
            "weather", "climateskeptics",
        ),
        newsapi_keywords=(
            "climate change", "hurricane forecast", "wildfire",
            "carbon emissions", "ESG investing", "net zero",
            "NOAA forecast",
        ),
        target_x_handles=(
            "NOAA", "EPA", "ClimateReality",
            "GretaThunberg", "NASAClimate",
        ),
        related_assets=(),
    ),

    "companies": CategoryConfig(
        name="Companies",
        kalshi_categories=("companies", "earnings", "stocks", "ipo"),
        keywords=(
            "earnings", "EPS", "guidance", "downgrade", "upgrade",
            "layoffs", "IPO", "M&A", "acquisition", "merger",
            "revenue", "profit", "loss", "quarterly results",
            "NVIDIA", "Apple", "Microsoft", "Tesla", "Meta",
            "Amazon", "Google", "Alphabet", "S&P 500", "SPX",
        ),
        hashtags=(
            "#stocks", "#earnings", "#options", "#SPX",
            "#SP500", "#NVDA", "#TSLA", "#AAPL",
            "#wallstreetbets", "#investing", "#IPO",
            "#layoffs", "#merger",
        ),
        subreddits=(
            "stocks", "investing", "wallstreetbets",
            "SecurityAnalysis", "StockMarket",
        ),
        newsapi_keywords=(
            "earnings report", "EPS beat", "guidance raised",
            "layoffs announced", "IPO filing", "merger acquisition",
            "stock downgrade", "analyst upgrade",
        ),
        target_x_handles=(
            "jimcramer", "chamath", "elonmusk",
            "WSJmarkets", "BloombergTV", "CNBCFastMoney",
        ),
        related_assets=("BTC", "ETH"),
    ),

    "financials": CategoryConfig(
        name="Financials",
        kalshi_categories=("financials", "banks", "credit"),
        keywords=(
            "bank", "banking", "credit", "liquidity", "credit spread",
            "JPMorgan", "Goldman Sachs", "Morgan Stanley",
            "Bank of America", "Wells Fargo", "Citigroup",
            "FDIC", "SVB", "bank run", "deposit", "loan",
            "mortgage", "credit default swap", "CDS",
        ),
        hashtags=(
            "#banks", "#banking", "#credit", "#liquidity",
            "#JPMorgan", "#GoldmanSachs", "#Fintech",
            "#creditspread", "#CDS",
        ),
        subreddits=(
            "finance", "investing", "economics",
            "personalfinance", "banking",
        ),
        newsapi_keywords=(
            "bank earnings", "credit conditions", "bank liquidity",
            "credit spreads", "FDIC", "bank failure",
        ),
        target_x_handles=(
            "zerohedge", "markets", "FT",
            "BloombergTV", "WSJmarkets",
        ),
        related_assets=("BTC",),
    ),

    "tech_science": CategoryConfig(
        name="Tech & Science",
        kalshi_categories=("tech", "science", "ai", "space", "biotech"),
        keywords=(
            "AI", "artificial intelligence", "ChatGPT", "OpenAI",
            "semiconductors", "NVIDIA", "chips", "space", "NASA",
            "SpaceX", "biotech", "FDA", "clinical trial",
            "quantum computing", "robotics", "autonomous",
            "LLM", "AGI", "Gemini", "Claude", "GPT",
        ),
        hashtags=(
            "#AI", "#semiconductor", "#Fintech", "#BigTech",
            "#OpenAI", "#ChatGPT", "#NVIDIA", "#SpaceX",
            "#biotech", "#FDA", "#AGI", "#MachineLearning",
            "#tech", "#innovation",
        ),
        subreddits=(
            "technology", "artificial", "MachineLearning",
            "singularity", "space", "Futurology",
        ),
        newsapi_keywords=(
            "AI model release", "NVIDIA earnings", "OpenAI",
            "SpaceX launch", "FDA approval", "biotech trial",
            "semiconductor supply", "quantum computing",
        ),
        target_x_handles=(
            "sama", "ylecun", "karpathy",
            "elonmusk", "NASA", "SpaceX",
            "OpenAI", "AnthropicAI",
        ),
        related_assets=("BTC", "ETH"),
    ),

    "mentions": CategoryConfig(
        name="Mentions",
        kalshi_categories=("mentions", "celebrity", "brand"),
        keywords=(
            "trending", "viral", "celebrity", "influencer",
            "brand mention", "media coverage", "press",
        ),
        hashtags=(
            "#trending", "#viral", "#celebrity",
            "#influencer", "#brand",
        ),
        subreddits=("OutOfTheLoop", "explainlikeimfive", "news"),
        newsapi_keywords=(
            "trending topic", "viral story", "celebrity news",
        ),
        target_x_handles=(),
        related_assets=(),
    ),
}


# ── Subreddit → category mapping ──────────────────────────────────────────

SUBREDDIT_CATEGORY_MAP: Dict[str, str] = {
    "Bitcoin": "crypto",
    "btc": "crypto",
    "ethereum": "crypto",
    "solana": "crypto",
    "dogecoin": "crypto",
    "Ripple": "crypto",
    "XRP": "crypto",
    "CryptoCurrency": "crypto",
    "CryptoMarkets": "crypto",
    "BitcoinMarkets": "crypto",
    "politics": "politics",
    "PoliticalDiscussion": "politics",
    "nfl": "sports",
    "nba": "sports",
    "baseball": "sports",
    "hockey": "sports",
    "soccer": "sports",
    "sportsbook": "sports",
    "movies": "culture",
    "television": "culture",
    "Music": "culture",
    "economics": "economics",
    "economy": "economics",
    "investing": "companies",
    "stocks": "companies",
    "wallstreetbets": "companies",
    "StockMarket": "companies",
    "finance": "financials",
    "technology": "tech_science",
    "artificial": "tech_science",
    "MachineLearning": "tech_science",
    "space": "tech_science",
}


# ── Kalshi category slug → NEWS_TOPICS key ────────────────────────────────

KALSHI_CATEGORY_TO_TOPIC: Dict[str, str] = {
    "crypto": "crypto",
    "cryptocurrency": "crypto",
    "bitcoin": "crypto",
    "ethereum": "crypto",
    "politics": "politics",
    "elections": "politics",
    "congress": "politics",
    "presidency": "politics",
    "sports": "sports",
    "nfl": "sports",
    "nba": "sports",
    "mlb": "sports",
    "nhl": "sports",
    "soccer": "sports",
    "culture": "culture",
    "entertainment": "culture",
    "awards": "culture",
    "movies": "culture",
    "music": "culture",
    "economics": "economics",
    "economy": "economics",
    "fed": "economics",
    "inflation": "economics",
    "jobs": "economics",
    "climate": "climate",
    "weather": "climate",
    "environment": "climate",
    "companies": "companies",
    "earnings": "companies",
    "stocks": "companies",
    "ipo": "companies",
    "financials": "financials",
    "banks": "financials",
    "credit": "financials",
    "tech": "tech_science",
    "science": "tech_science",
    "ai": "tech_science",
    "space": "tech_science",
    "biotech": "tech_science",
    "mentions": "mentions",
    "celebrity": "mentions",
    "brand": "mentions",
}


# ── Kalshi event title → asset heuristic ─────────────────────────────────

TITLE_ASSET_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("bitcoin", "BTC"),
    ("btc", "BTC"),
    ("ethereum", "ETH"),
    ("eth ", "ETH"),
    ("solana", "SOL"),
    ("sol ", "SOL"),
    ("dogecoin", "DOGE"),
    ("doge", "DOGE"),
    ("ripple", "XRP"),
    ("xrp", "XRP"),
)


def infer_asset_from_title(title: str) -> Optional[str]:
    """Infer crypto asset from Kalshi event title."""
    t = title.lower()
    for pattern, asset in TITLE_ASSET_PATTERNS:
        if pattern in t:
            return asset
    return None


def get_topic_for_kalshi_category(category_slug: str) -> Optional[str]:
    """Map a Kalshi category slug to a NEWS_TOPICS key."""
    return KALSHI_CATEGORY_TO_TOPIC.get(category_slug.lower())


def get_all_hashtags_for_asset(asset: str) -> List[str]:
    """Return all hashtags for a crypto asset."""
    cfg = CRYPTO_ASSETS.get(asset)
    if not cfg:
        return []
    return list(cfg.hashtags) + list(cfg.cashtags)


def get_all_hashtags_for_category(category: str) -> List[str]:
    """Return all hashtags for a Kalshi category topic."""
    cfg = NEWS_TOPICS.get(category)
    if not cfg:
        return []
    return list(cfg.hashtags)


# ── Align with canonical Kalshi crypto universe (import-time check) ───────

def _validate_crypto_assets_vs_config() -> None:
    from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS

    cfg_set = set(ACTIVE_CRYPTO_ASSETS)
    news_set = set(CRYPTO_ASSETS.keys())
    if cfg_set != news_set:
        raise ValueError(
            "merid.sentiment.news_config.CRYPTO_ASSETS keys must match "
            "config.kalshi_crypto_config.ACTIVE_CRYPTO_ASSETS "
            f"(cfg={sorted(cfg_set)}, news={sorted(news_set)})"
        )


_validate_crypto_assets_vs_config()
