# MERID Flink Jobs

This directory contains compiled Flink job JARs for deployment.

## Building Jobs

```bash
cd flink
mvn clean package -P fat-jar
```

This produces a fat JAR at `target/merid-flink-jobs-1.0.0.jar`.

## Deploying Jobs

### Via Docker

```bash
# Copy JAR to jobs directory
cp target/merid-flink-jobs-1.0.0.jar jobs/

# Submit to Flink cluster
docker exec merid-flink-jm flink run /opt/flink/jobs/merid-flink-jobs-1.0.0.jar
```

### Via Flink CLI

```bash
flink run -m localhost:8081 jobs/merid-flink-jobs-1.0.0.jar
```

### With Savepoint

```bash
flink run -s /path/to/savepoint jobs/merid-flink-jobs-1.0.0.jar
```

## Available Jobs

| Job Class | Description |
|-----------|-------------|
| `MeridPriceFeatures` | Basic price→features pipeline |
| `MeridWindowedFeatures` | Event-time windowed OHLCV + metrics |

## Configuration

Jobs read configuration from environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `redpanda:9092` | Kafka broker address |
| `FLINK_PARALLELISM` | `2` | Job parallelism |
| `CHECKPOINT_INTERVAL_MS` | `60000` | Checkpoint interval |

## Flink SQL Alternative

For simpler deployments, use Flink SQL:

```bash
docker exec -it merid-flink-jm bin/sql-client.sh -f /opt/flink/sql/merid_tables.sql
```

See `sql/merid_tables.sql` for table definitions and streaming jobs.
