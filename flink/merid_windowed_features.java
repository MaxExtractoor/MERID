/**
 * MERID Flink Job - Windowed Feature Pipeline with Late Data Handling
 * 
 * Computes rolling features using event-time windows with proper handling of:
 * - Watermarks for out-of-order events
 * - Allowed lateness for late-arriving data
 * - Side outputs for events beyond lateness threshold
 * 
 * Topics:
 *   Input:  prices.{venue}.{symbol}
 *   Output: features.{venue}.{symbol} (windowed aggregates)
 *   Late:   features.late.{venue}.{symbol} (late events for reprocessing)
 */

package merid.flink;

import org.apache.flink.api.common.eventtime.SerializableTimestampAssigner;
import org.apache.flink.api.common.eventtime.WatermarkStrategy;
import org.apache.flink.api.common.functions.AggregateFunction;
import org.apache.flink.api.common.serialization.SimpleStringSchema;
import org.apache.flink.api.common.state.ValueState;
import org.apache.flink.api.common.state.ValueStateDescriptor;
import org.apache.flink.configuration.Configuration;
import org.apache.flink.connector.kafka.sink.KafkaRecordSerializationSchema;
import org.apache.flink.connector.kafka.sink.KafkaSink;
import org.apache.flink.connector.kafka.source.KafkaSource;
import org.apache.flink.streaming.api.datastream.DataStream;
import org.apache.flink.streaming.api.datastream.SingleOutputStreamOperator;
import org.apache.flink.streaming.api.environment.StreamExecutionEnvironment;
import org.apache.flink.streaming.api.functions.windowing.ProcessWindowFunction;
import org.apache.flink.streaming.api.windowing.assigners.TumblingEventTimeWindows;
import org.apache.flink.streaming.api.windowing.time.Time;
import org.apache.flink.streaming.api.windowing.windows.TimeWindow;
import org.apache.flink.util.Collector;
import org.apache.flink.util.OutputTag;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.time.Duration;
import java.util.*;

public class MeridWindowedFeatures {

    // Configuration
    private static final String KAFKA_BOOTSTRAP = System.getenv().getOrDefault(
        "KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"
    );
    private static final String INPUT_TOPIC_PATTERN = "prices\\..*";
    private static final String CONSUMER_GROUP = "merid-flink-windowed";
    
    // Window configuration
    private static final int WINDOW_SIZE_SECONDS = 60;  // 1-minute windows
    private static final int ALLOWED_LATENESS_SECONDS = 30;  // Allow 30s late data
    private static final int WATERMARK_BOUND_SECONDS = 10;  // Expect 10s out-of-order
    
    // Output tags for late data
    private static final OutputTag<PriceTick> LATE_DATA_TAG = 
        new OutputTag<PriceTick>("late-price-data") {};

    public static void main(String[] args) throws Exception {
        StreamExecutionEnvironment env = StreamExecutionEnvironment.getExecutionEnvironment();
        
        // Enable checkpointing for exactly-once
        env.enableCheckpointing(60000);
        env.getCheckpointConfig().setMinPauseBetweenCheckpoints(30000);
        
        // Kafka source
        KafkaSource<String> source = KafkaSource.<String>builder()
            .setBootstrapServers(KAFKA_BOOTSTRAP)
            .setTopicPattern(INPUT_TOPIC_PATTERN)
            .setGroupId(CONSUMER_GROUP)
            .setValueOnlyDeserializer(new SimpleStringSchema())
            .build();

        // Read with event-time watermarks
        DataStream<PriceTick> priceStream = env.fromSource(
            source,
            WatermarkStrategy
                .<String>forBoundedOutOfOrderness(Duration.ofSeconds(WATERMARK_BOUND_SECONDS))
                .withTimestampAssigner(new PriceTimestampAssigner()),
            "kafka-prices"
        )
        .map(MeridWindowedFeatures::parsePriceTick)
        .filter(tick -> tick != null);

        // =================================================================
        // 1-MINUTE WINDOW AGGREGATIONS
        // =================================================================
        SingleOutputStreamOperator<WindowedFeatures> oneMinuteFeatures = priceStream
            .keyBy(PriceTick::getSymbolKey)
            .window(TumblingEventTimeWindows.of(Time.seconds(WINDOW_SIZE_SECONDS)))
            .allowedLateness(Time.seconds(ALLOWED_LATENESS_SECONDS))
            .sideOutputLateData(LATE_DATA_TAG)
            .aggregate(
                new PriceAggregator(),
                new FeatureWindowFunction()
            );

        // Get late data stream
        DataStream<PriceTick> lateDataStream = oneMinuteFeatures.getSideOutput(LATE_DATA_TAG);

        // =================================================================
        // SINK: Main features to Kafka
        // =================================================================
        KafkaSink<String> featuresSink = KafkaSink.<String>builder()
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
            .setDeliveryGuarantee(org.apache.flink.connector.base.DeliveryGuarantee.EXACTLY_ONCE)
            .build();

        oneMinuteFeatures
            .map(f -> new Gson().toJson(f))
            .sinkTo(featuresSink);

        // =================================================================
        // SINK: Late data to separate topic for reprocessing
        // =================================================================
        KafkaSink<String> lateSink = KafkaSink.<String>builder()
            .setBootstrapServers(KAFKA_BOOTSTRAP)
            .setRecordSerializer(
                KafkaRecordSerializationSchema.builder()
                    .setTopicSelector(record -> {
                        JsonObject json = new Gson().fromJson(record, JsonObject.class);
                        String venue = json.get("venue").getAsString();
                        String symbol = json.get("symbol").getAsString();
                        return String.format("features.late.%s.%s", venue, symbol);
                    })
                    .setValueSerializationSchema(new SimpleStringSchema())
                    .build()
            )
            .build();

        lateDataStream
            .map(tick -> new Gson().toJson(tick))
            .sinkTo(lateSink);

        // Execute
        env.execute("MERID Windowed Features Pipeline");
    }

    // =================================================================
    // DATA TYPES
    // =================================================================
    
    public static class PriceTick {
        public String symbol;
        public String venue;
        public double price;
        public double volume;
        public long timestamp;  // epoch millis
        
        public String getSymbolKey() {
            return venue + ":" + symbol;
        }
    }

    public static class PriceAccumulator {
        public String symbol;
        public String venue;
        public double open;
        public double high;
        public double low;
        public double close;
        public double volumeSum;
        public double priceVolumeSum;  // For VWAP
        public int tickCount;
        public List<Double> prices = new ArrayList<>();
        public long firstTimestamp;
        public long lastTimestamp;
    }

    public static class WindowedFeatures {
        // Identity
        public String symbol;
        public String venue;
        public long windowStart;
        public long windowEnd;
        
        // OHLCV
        public double open;
        public double high;
        public double low;
        public double close;
        public double volume;
        
        // Derived features
        public double vwap;
        public double returnPct;
        public double volatility;
        public double range;
        public double rangePercent;
        public int tickCount;
        
        // Metadata
        public String schemaVersion = "1.0";
        public long processedAt;
        public boolean isLateUpdate;
    }

    // =================================================================
    // TIMESTAMP ASSIGNER
    // =================================================================
    
    public static class PriceTimestampAssigner 
            implements SerializableTimestampAssigner<String> {
        private final Gson gson = new Gson();
        
        @Override
        public long extractTimestamp(String json, long recordTimestamp) {
            try {
                JsonObject obj = gson.fromJson(json, JsonObject.class);
                if (obj.has("timestamp")) {
                    double ts = obj.get("timestamp").getAsDouble();
                    // Handle both seconds and milliseconds
                    if (ts < 1e12) {
                        return (long) (ts * 1000);
                    }
                    return (long) ts;
                }
            } catch (Exception e) {
                // Fall through
            }
            return recordTimestamp > 0 ? recordTimestamp : System.currentTimeMillis();
        }
    }

    // =================================================================
    // PARSER
    // =================================================================
    
    private static PriceTick parsePriceTick(String json) {
        try {
            Gson gson = new Gson();
            JsonObject obj = gson.fromJson(json, JsonObject.class);
            
            PriceTick tick = new PriceTick();
            tick.symbol = obj.has("symbol") ? obj.get("symbol").getAsString() : "UNKNOWN";
            tick.venue = obj.has("venue") ? obj.get("venue").getAsString() : "unknown";
            tick.price = obj.has("price") ? obj.get("price").getAsDouble() : 0.0;
            tick.volume = obj.has("volume") ? obj.get("volume").getAsDouble() : 0.0;
            
            if (obj.has("timestamp")) {
                double ts = obj.get("timestamp").getAsDouble();
                tick.timestamp = ts < 1e12 ? (long) (ts * 1000) : (long) ts;
            } else {
                tick.timestamp = System.currentTimeMillis();
            }
            
            return tick;
        } catch (Exception e) {
            return null;
        }
    }

    // =================================================================
    // AGGREGATOR
    // =================================================================
    
    public static class PriceAggregator 
            implements AggregateFunction<PriceTick, PriceAccumulator, PriceAccumulator> {
        
        @Override
        public PriceAccumulator createAccumulator() {
            return new PriceAccumulator();
        }

        @Override
        public PriceAccumulator add(PriceTick tick, PriceAccumulator acc) {
            if (acc.tickCount == 0) {
                acc.symbol = tick.symbol;
                acc.venue = tick.venue;
                acc.open = tick.price;
                acc.high = tick.price;
                acc.low = tick.price;
                acc.firstTimestamp = tick.timestamp;
            }
            
            acc.high = Math.max(acc.high, tick.price);
            acc.low = Math.min(acc.low, tick.price);
            acc.close = tick.price;
            acc.volumeSum += tick.volume;
            acc.priceVolumeSum += tick.price * tick.volume;
            acc.tickCount++;
            acc.prices.add(tick.price);
            acc.lastTimestamp = tick.timestamp;
            
            return acc;
        }

        @Override
        public PriceAccumulator getResult(PriceAccumulator acc) {
            return acc;
        }

        @Override
        public PriceAccumulator merge(PriceAccumulator a, PriceAccumulator b) {
            PriceAccumulator merged = new PriceAccumulator();
            merged.symbol = a.symbol;
            merged.venue = a.venue;
            
            if (a.firstTimestamp <= b.firstTimestamp) {
                merged.open = a.open;
                merged.firstTimestamp = a.firstTimestamp;
            } else {
                merged.open = b.open;
                merged.firstTimestamp = b.firstTimestamp;
            }
            
            if (a.lastTimestamp >= b.lastTimestamp) {
                merged.close = a.close;
                merged.lastTimestamp = a.lastTimestamp;
            } else {
                merged.close = b.close;
                merged.lastTimestamp = b.lastTimestamp;
            }
            
            merged.high = Math.max(a.high, b.high);
            merged.low = Math.min(a.low, b.low);
            merged.volumeSum = a.volumeSum + b.volumeSum;
            merged.priceVolumeSum = a.priceVolumeSum + b.priceVolumeSum;
            merged.tickCount = a.tickCount + b.tickCount;
            merged.prices.addAll(a.prices);
            merged.prices.addAll(b.prices);
            
            return merged;
        }
    }

    // =================================================================
    // WINDOW FUNCTION - Computes final features
    // =================================================================
    
    public static class FeatureWindowFunction 
            extends ProcessWindowFunction<PriceAccumulator, WindowedFeatures, String, TimeWindow> {
        
        @Override
        public void process(
                String key,
                Context context,
                Iterable<PriceAccumulator> elements,
                Collector<WindowedFeatures> out) {
            
            PriceAccumulator acc = elements.iterator().next();
            WindowedFeatures features = new WindowedFeatures();
            
            // Identity
            features.symbol = acc.symbol;
            features.venue = acc.venue;
            features.windowStart = context.window().getStart();
            features.windowEnd = context.window().getEnd();
            
            // OHLCV
            features.open = acc.open;
            features.high = acc.high;
            features.low = acc.low;
            features.close = acc.close;
            features.volume = acc.volumeSum;
            
            // VWAP
            features.vwap = acc.volumeSum > 0 
                ? acc.priceVolumeSum / acc.volumeSum 
                : acc.close;
            
            // Return
            features.returnPct = acc.open > 0 
                ? (acc.close - acc.open) / acc.open 
                : 0.0;
            
            // Volatility (standard deviation of prices)
            features.volatility = computeVolatility(acc.prices);
            
            // Range
            features.range = acc.high - acc.low;
            features.rangePercent = acc.low > 0 
                ? features.range / acc.low 
                : 0.0;
            
            // Metadata
            features.tickCount = acc.tickCount;
            features.processedAt = System.currentTimeMillis();
            
            // Check if this is a late update (window already fired once)
            features.isLateUpdate = context.currentWatermark() > context.window().getEnd();
            
            out.collect(features);
        }
        
        private double computeVolatility(List<Double> prices) {
            if (prices.size() < 2) return 0.0;
            
            double mean = prices.stream()
                .mapToDouble(p -> p)
                .average()
                .orElse(0.0);
            
            double variance = prices.stream()
                .mapToDouble(p -> Math.pow(p - mean, 2))
                .average()
                .orElse(0.0);
            
            return Math.sqrt(variance);
        }
    }
}
