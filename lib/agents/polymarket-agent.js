const axios = require('axios');

async function getBtcPrice() {
  try {
    const response = await axios.get('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd');
    return { price: response.data.bitcoin.usd, source: 'CoinGecko' };
  } catch (error) {
    console.warn('CoinGecko failed, falling back to Binance...');
    const binance = await axios.get('https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT');
    return { price: parseFloat(binance.data.price), source: 'Binance' };
  }
}

process.stdin.on('data', async (data) => {
  const input = data.toString().trim();
  const params = JSON.parse(input || '{}');

  if (params.action === 'get_btc_price') {
    const result = await getBtcPrice();
    console.log(JSON.stringify(result));
  } else {
    console.log(JSON.stringify({ error: 'Unknown action' }));
  }
});
