# Observability — OpenTelemetry + Grafana Dashboard

## Backend Instrumentation

The backend is instrumented with OpenTelemetry in `main.py`. To enable:

1. Set OTLP endpoint:
   ```bash
   export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
   export OTEL_SERVICE_NAME=log-management-backend
   ```

2. Or set in environment:
   ```
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
   OTEL_SERVICE_NAME=log-management-backend
   ```

3. Install dependencies:
   ```bash
   pip install opentelemetry-api opentelemetry-sdk \
     opentelemetry-instrumentation-fastapi \
     opentelemetry-instrumentation-asyncpg \
     opentelemetry-exporter-otlp
   ```

## Grafana Dashboard

Import the following JSON as a new dashboard in Grafana.

```json
{
  "annotations": {
    "list": []
  },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 0,
  "id": null,
  "links": [],
  "liveNow": false,
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "red", "value": 80}
            ]
          },
          "unit": "reqps"
        }
      },
      "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
      "id": 1,
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
        "textMode": "auto"
      },
      "title": "Request Rate",
      "type": "stat",
      "targets": [{"expr": "rate(http_requests_total[5m])", "refId": "A"}]
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [
              {"color": "green", "value": null},
              {"color": "yellow", "value": 0.5},
              {"color": "red", "value": 1}
            ]
          },
          "unit": "s"
        }
      },
      "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
      "id": 2,
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "justifyMode": "auto",
        "orientation": "auto",
        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": false},
        "textMode": "auto"
      },
      "title": "P99 Latency",
      "type": "stat",
      "targets": [{"expr": "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))", "refId": "A"}]
    },
    {
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "fieldConfig": {
        "defaults": {
          "color": {"mode": "palette-classic"},
          "custom": {
            "axisCenteredZero": false,
            "axisColorMode": "text",
            "axisLabel": "",
            "axisPlacement": "auto",
            "barAlignment": 0,
            "drawStyle": "line",
            "fillOpacity": 20,
            "gradientMode": "none",
            "hideFrom": {"legend": false, "tooltip": false, "viz": false},
            "lineInterpolation": "linear",
            "lineWidth": 2,
            "pointSize": 5,
            "scaleDistribution": {"type": "linear"},
            "showPoints": "auto",
            "spanNulls": false,
            "stacking": {"group": "A", "mode": "none"},
            "thresholdsStyle": {"mode": "off"}
          },
          "mappings": [],
          "thresholds": {
            "mode": "absolute",
            "steps": [{"color": "green", "value": null}]
          },
          "unit": "short"
        }
      },
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 8},
      "id": 3,
      "options": {
        "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": true},
        "tooltip": {"mode": "single", "sort": "none"}
      },
      "targets": [
        {"expr": "rate(logs_ingested_total[5m])", "legendFormat": "Logs Ingested/s", "refId": "A"},
        {"expr": "rate(alerts_triggered_total[5m])", "legendFormat": "Alerts Triggered/s", "refId": "B"},
        {"expr": "rate(logs_queried_total[5m])", "legendFormat": "Logs Queried/s", "refId": "C"}
      ],
      "title": "Ingest & Query Rate",
      "type": "timeseries"
    }
  ],
  "refresh": "10s",
  "schemaVersion": 38,
  "style": "dark",
  "tags": ["log-management", "observability"],
  "templating": {"list": []},
  "time": {"from": "now-1h", "to": "now"},
  "timepicker": {},
  "timezone": "browser",
  "title": "Log Management — Observability",
  "uid": "logmgmt-observability",
  "version": 1,
  "weekStart": ""
}
```

## Metrics Endpoint

The backend exposes metrics at `GET /metrics` (Prometheus format) when OpenTelemetry is configured.

## Tracing

Distributed tracing is enabled via OpenTelemetry FastAPI instrumentation. Spans are exported to the configured OTLP endpoint (Jaeger, Zipkin, or Grafana Tempo compatible).

## Alerts

Add these Grafana alerting rules:

1. **High Ingest Latency**: Alert when P99 > 2s for 5 minutes
2. **Ingest Rate Drop**: Alert when ingest rate drops below 10/s for 10 minutes
3. **High Error Rate**: Alert when error rate > 1% for 5 minutes
