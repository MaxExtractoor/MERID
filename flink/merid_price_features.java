/**
 * MERID Flink Job - Price Features Pipeline
 * 
 * Reads raw price ticks from Kafka, computes rolling features,
 * and writes enriched streams back to Kafka for agent consumption.
 * 
 * Topics:
 *   Input:  prices.{venue}.{symbol}  (e.g., prices.KRAKEN.BTCUSD)
 *   Output: features.{venue}.{symbol} (enriched with rolling stats)
 * 
 * Features computed:
 *   - Rolling returns (1m, 5m, 15m, 1h)
 *   - Volatility (rolling std dev)
 *   - VWAP
 *   - Price momentum
 *   - Volume profile
 * 
 * To run:
 *   flink run -c merid.flink.MeridPriceFeatures merid-flink-job.jar
 */

package merid.flink;

import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.MapFunction;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.KeyedProcessFunction;
import org.apache.flink.util.Collector;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.time.Duration;
import java.util.*;

public class MeridPriceFeatures {

    // Configuration
    private static final String KAFKA_BOOTSTRAP = System.getenv().getOrDefault(
        "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
    );
    private static final String INPUT_TOPIC_PATTERN = "prices\\..*";
    private static final String CONSUMER_GROUP = "merid-flink-features";
    
    // Feature windows
    private static final int[] RETURN_WINDOWS_SECONDS = {60, 300, 900, 3600}; // 1m, 5m, 15m, 1h
    private static final int VOLATILITY_WINDOW_SECONDS = 300; // 5m volatility
    private static final int MAX_HISTORY_SIZE = 1000;

    public static void main(String[] args) throws Exception {
        // Set up execution environment
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        
        // Enable checkpointing for exactly-once semantics
        env.enableCheckpointing(60000); // 1 minute checkpoints
        
        // Kafka source with pattern subscription for all price topics
        KafkaSource<String> source = KafkaSource.<String>builder()
            .setBootstrapServers(KAFKA_BOOTSTRAP)
            .setTopicPattern(INPUT_TOPIC_PATTERN)
            .setGroupId(CONSUMER_GROUP)
            .setValueOnlyDeserializer(new SimpleStringSchema())
            .build();

        // Read raw price ticks
        DataStream<String> rawPrices = env.fromSource(
            source,
            WatermarkStrategy.<String>forBoundedOutOfOrderness(Duration.ofSeconds(5))
                .withTimestampAssigner((event, timestamp) -> extractTimestamp(event)),
            "kafka-prices"
        );

        // Parse, key by symbol, compute features
        DataStream<EnrichedPrice> enriched = rawPrices
            .map(new PriceParser())
            .filter(price -> price != null)
            .keyBy(EnrichedPrice::getSymbol)
            .process(new RollingFeaturesProcessor());

        // Kafka sink - write to features topics
        KafkaSink<String> sink = KafkaSink.<String>builder()
            .setBootstrapServers(KAFKA_BOOTSTRAP)
            .setRecordSerializer(
                KafkaRecordSerializationSchema.builder()
                    .setTopicSelector(record -> {
                        JsonObject json = new Gson().fromJson(record, JsonObject.class);
                        String venue = json.get("venue").getAsString();
                        String symbol = json.get("symbol").getAsString();
                        return String.format("features.%s.%s", venue, symbol);
                    })
                    .setValueSerializationSchema(new SimpleStringSchema())
                    .build()
            )
            .build();

        // Serialize and sink
        enriched
            .map(new EnrichedPriceSerializer())
            .sinkTo(sink);

        // Execute the Flink job
        env.execute("MERID Price Features Pipeline");
    }

    /**
     * Extract timestamp from JSON price event.
     */
    private static long extractTimestamp(String json) {
        try {
            JsonObject obj = new Gson().fromJson(json, JsonObject.class);
            if (obj.has("timestamp")) {
                return (long) (obj.get("timestamp").getAsDouble() * 1000);
            }
        } catch (Exception e) {
            // Fall back to processing time
        }
        return System.currentTimeMillis();
    }

    /**
     * Price data with computed features.
     */
    public static class EnrichedPrice {
        public String symbol;
        public String venue;
        public double price;
        public double volume;
        public long timestamp;
        
        // Rolling returns
        public double return1m;
        public double return5m;
        public double return15m;
        public double return1h;
        
        // Volatility
        public double volatility5m;
        
        // VWAP
        public double vwap;
        
        // Momentum
        public double momentum;
        public double priceChange;
        
        // Volume profile
        public double volumeMA;
        public double volumeRatio;
        
        // Metadata
        public String schemaVersion = "1.0";
        public long processedAt;

        public String getSymbol() {
            return symbol;
        }
    }

    /**
     * Parse JSON price tick into EnrichedPrice POJO.
     */
    public static class PriceParser implements MapFunction<String, EnrichedPrice> {
        private final Gson gson = new Gson();

        @Override
        public EnrichedPrice map(String json) throws Exception {
            try {
                JsonObject obj = gson.fromJson(json, JsonObject.class);
                EnrichedPrice price = new EnrichedPrice();
                
                price.symbol = obj.has("symbol") ? obj.get("symbol").getAsString() : "UNKNOWN";
                price.venue = obj.has("venue") ? obj.get("venue").getAsString() : "unknown";
                price.price = obj.has("price") ? obj.get("price").getAsDouble() : 0.0;
                price.volume = obj.has("volume") ? obj.get("volume").getAsDouble() : 0.0;
                price.timestamp = obj.has("timestamp") 
                    ? (long) (obj.get("timestamp").getAsDouble() * 1000)
                    : System.currentTimeMillis();
                
                return price;
            } catch (Exception e) {
                return null;
            }
        }
    }

    /**
     * Compute rolling features using Flink keyed state.
     */
    public static class RollingFeaturesProcessor 
            extends KeyedProcessFunction<String, EnrichedPrice, EnrichedPrice> {
        
        // State for price history
        private transient ValueState<List<PricePoint>> priceHistoryState;
        
        @Override
        public void open(Configuration parameters) throws Exception {
            ValueStateDescriptor<List<PricePoint>> descriptor = 
                new ValueStateDescriptor<>("priceHistory", List.class);
            priceHistoryState = getRuntimeContext().getState(descriptor);
        }

        @Override
        public void processElement(
                EnrichedPrice price,
                Context ctx,
                Collector<EnrichedPrice> out) throws Exception {
            
            // Get or initialize price history
            List<PricePoint> history = priceHistoryState.value();
            if (history == null) {
                history = new ArrayList<>();
            }
            
            long now = price.timestamp;
            
            // Add current price to history
            history.add(new PricePoint(now, price.price, price.volume));
            
            // Prune old data (keep last hour)
            long cutoff = now - 3600 * 1000;
            history.removeIf(p -> p.timestamp < cutoff);
            
            // Limit history size
            if (history.size() > MAX_HISTORY_SIZE) {
                history = new ArrayList<>(history.subList(history.size() - MAX_HISTORY_SIZE, history.size()));
            }
            
            // Compute rolling returns
            price.return1m = computeReturn(history, now, 60 * 1000);
            price.return5m = computeReturn(history, now, 300 * 1000);
            price.return15m = computeReturn(history, now, 900 * 1000);
            price.return1h = computeReturn(history, now, 3600 * 1000);
            
            // Compute volatility (5m rolling std dev of returns)
            price.volatility5m = computeVolatility(history, now, 300 * 1000);
            
            // Compute VWAP
            price.vwap = computeVWAP(history, now, 300 * 1000);
            
            // Compute momentum (price vs VWAP)
            price.momentum = price.vwap > 0 ? (price.price - price.vwap) / price.vwap : 0;
            
            // Price change from previous
            if (history.size() >= 2) {
                PricePoint prev = history.get(history.size() - 2);
                price.priceChange = (price.price - prev.price) / prev.price;
            }
            
            // Volume analysis
            price.volumeMA = computeVolumeMA(history, now, 300 * 1000);
            price.volumeRatio = price.volumeMA > 0 ? price.volume / price.volumeMA : 1.0;
            
            // Metadata
            price.processedAt = System.currentTimeMillis();
            
            // Update state
            priceHistoryState.update(history);
            
            // Emit enriched price
            out.collect(price);
        }
        
        private double computeReturn(List<PricePoint> history, long now, long windowMs) {
            if (history.size() < 2) return 0.0;
            
            PricePoint current = history.get(history.size() - 1);
            long targetTime = now - windowMs;
            
            // Find price closest to target time
            PricePoint past = null;
            for (PricePoint p : history) {
                if (p.timestamp <= targetTime) {
                    past = p;
                } else {
                    break;
                }
            }
            
            if (past == null || past.price == 0) return 0.0;
            return (current.price - past.price) / past.price;
        }
        
        private double computeVolatility(List<PricePoint> history, long now, long windowMs) {
            long cutoff = now - windowMs;
            List<Double> returns = new ArrayList<>();
            
            PricePoint prev = null;
            for (PricePoint p : history) {
                if (p.timestamp >= cutoff) {
                    if (prev != null && prev.price > 0) {
                        returns.add((p.price - prev.price) / prev.price);
                    }
                }
                prev = p;
            }
            
            if (returns.size() < 2) return 0.0;
            
            // Compute standard deviation
            double mean = returns.stream().mapToDouble(r -> r).average().orElse(0.0);
            double variance = returns.stream()
                .mapToDouble(r -> Math.pow(r - mean, 2))
                .average()
                .orElse(0.0);
            
            return Math.sqrt(variance);
        }
        
        private double computeVWAP(List<PricePoint> history, long now, long windowMs) {
            long cutoff = now - windowMs;
            double sumPV = 0;
            double sumV = 0;
            
            for (PricePoint p : history) {
                if (p.timestamp >= cutoff) {
                    sumPV += p.price * p.volume;
                    sumV += p.volume;
                }
            }
            
            return sumV > 0 ? sumPV / sumV : 0;
        }
        
        private double computeVolumeMA(List<PricePoint> history, long now, long windowMs) {
            long cutoff = now - windowMs;
            int count = 0;
            double sum = 0;
            
            for (PricePoint p : history) {
                if (p.timestamp >= cutoff) {
                    sum += p.volume;
                    count++;
                }
            }
            
            return count > 0 ? sum / count : 0;
        }
    }

    /**
     * Price point for history tracking.
     */
    public static class PricePoint implements java.io.Serializable {
        public long timestamp;
        public double price;
        public double volume;
        
        public PricePoint(long timestamp, double price, double volume) {
            this.timestamp = timestamp;
            this.price = price;
            this.volume = volume;
        }
    }

    /**
     * Serialize EnrichedPrice to JSON.
     */
    public static class EnrichedPriceSerializer implements MapFunction<EnrichedPrice, String> {
        private final Gson gson = new Gson();

        @Override
        public String map(EnrichedPrice price) throws Exception {
            return gson.toJson(price);
        }
    }
}
