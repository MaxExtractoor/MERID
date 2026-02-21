# MERID React Hooks Usage Examples

This guide shows common usage patterns for the shared hooks in `web/react/src/hooks`.

## useApiData

```tsx
const { data, loading, error, refetch } = useApiData<PortfolioSummary>(
  "/api/v1/portfolio/summary",
  { pollingInterval: 5000 }
);
```

## useKafkaStream

```tsx
const { events, connected } = useKafkaStream("/ws/trades", {
  filterTypes: ["order_filled", "order_cancelled"],
  maxEvents: 200,
});
```

## useMeridSocket

```tsx
const { socket, connected } = useMeridSocket();

useEffect(() => {
  if (!socket) return;
  const onUpdate = (payload: any) => console.log(payload);
  socket.on("order:updated", onUpdate);
  return () => socket.off("order:updated", onUpdate);
}, [socket]);
```

## useOpenOrders

```tsx
const { rows, meta, loading } = useOpenOrders();
```

## usePredictions

```tsx
const { markets, meta, loading } = usePredictions();
```

## useRiskMetrics

```tsx
const { metrics, alerts } = useRiskMetrics();
```

## useRiskProtections

```tsx
const { data, resetCircuit, toggleKillSwitch } = useRiskProtections();
```

## useAgentsHealth

```tsx
const { rows, meta, loading } = useAgentsHealth();
```

## useRealtimeData

```tsx
const [payload, connected, error] = useRealtimeData<PriceTick>("price_tick");
```

## useLocalStorage

```tsx
const [preferences, setPreferences] = useLocalStorage("user-preferences", defaultPrefs);
```

## useWebSocket

```tsx
const { socket, connected, send } = useWebSocket({
  url: "ws://127.0.0.1:8000/ws/live",
  autoConnect: true,
});
```
