import express from "express";
import cors from "cors";
import axios from "axios";
import dotenv from "dotenv";

dotenv.config();

const app = express();
app.use(cors());
app.use(express.json());

app.get("/health", (req, res) => {
  res.json({ status: "MERID API ONLINE" });
});

app.get("/btc", async (req, res) => {
  try {
    const response = await axios.get(
      "https://api.coingecko.com/api/v3/simple/price",
      {
        params: {
          ids: "bitcoin",
          vs_currencies: "usd",
        },
      }
    );

    res.json({
      asset: "BTC",
      price_usd: response.data.bitcoin.usd,
      source: "CoinGecko",
      timestamp: new Date().toISOString(),
    });
  } catch (err) {
    res.status(500).json({ error: "Failed to fetch BTC price" });
  }
});

app.listen(4000, () => {
  console.log("🔥 MERID API running on http://localhost:4000");
});
