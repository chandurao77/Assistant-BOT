---
name: monitoring
description: "Monitoring and observability — structured logging, metrics, distributed tracing, alerting, and dashboards. USE FOR: set up logging, add metrics, configure tracing, create alerts, build dashboards, add health checks."
argument-hint: "Describe the monitoring task, e.g. 'add Prometheus metrics and Grafana dashboard for API latency'"
---

# Skill: Monitoring & Observability

## Purpose
Set up and maintain observability across applications — structured logging, metrics, tracing, and alerting.

## Three Pillars

### 1. Logging
```python
# Structured JSON logging (Python)
import structlog
logger = structlog.get_logger()
logger.info("request_processed", method="POST", path="/api/chat", duration_ms=142, status=200)
```

**Rules:**
- Use structured (JSON) logging — never plain text in production
- Include: timestamp, level, message, correlation_id, service_name
- Log at appropriate levels:

| Level | When |
|-------|------|
| `ERROR` | Something failed and needs attention |
| `WARN` | Something unexpected but handled |
| `INFO` | Business events (request served, job completed) |
| `DEBUG` | Detailed diagnostic info (dev only) |

- **Never log**: passwords, tokens, PII, full request bodies with sensitive data
- Include `request_id` / `correlation_id` in every log line for tracing

### 2. Metrics
```python
# Prometheus metrics (Python)
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter("http_requests_total", "Total requests", ["method", "endpoint", "status"])
REQUEST_DURATION = Histogram("http_request_duration_seconds", "Request latency", ["endpoint"])
```

**Key Metrics (RED Method):**
| Metric | What | Alert When |
|--------|------|------------|
| **R**ate | Requests per second | Sudden drop > 50% |
| **E**rrors | Error rate (%) | > 1% of requests |
| **D**uration | Latency (p50, p95, p99) | p95 > 2s |

**Additional Metrics:**
- Queue depth / consumer lag
- Cache hit rate
- Database connection pool usage
- Memory / CPU utilization
- Active users / concurrent sessions

### 3. Tracing
```python
# OpenTelemetry (Python)
from opentelemetry import trace
tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("process_query") as span:
    span.set_attribute("query.length", len(query))
    span.set_attribute("retrieval.chunks", len(chunks))
```

**Rules:**
- Instrument entry points (API routes, queue consumers, cron jobs)
- Propagate trace context across service boundaries
- Add attributes for business-relevant data (query type, result count)
- Sample in production (10-20%) to control costs

## Alerting

### Alert Levels
| Level | Response Time | Channel | Example |
|-------|--------------|---------|---------|
| P1 Critical | < 15 min | PagerDuty + Slack | Service down, data loss |
| P2 High | < 1 hour | Slack #alerts | Error rate > 5% |
| P3 Medium | < 4 hours | Slack #monitoring | Latency degraded |
| P4 Low | Next business day | Email / ticket | Disk usage > 80% |

### Alert Rules
- Alert on **symptoms** (user impact), not causes
- Every alert must have a runbook link
- No alert should fire more than once per hour (aggregate)
- Test alerts regularly — an alert that never fires might be broken

## Dashboard Template
```
┌─────────────────────────────────────────────┐
│  Service Health Dashboard                    │
├──────────────┬──────────────┬───────────────┤
│  Request Rate│  Error Rate  │  p95 Latency  │
│  ████ 142/s  │  ░░ 0.3%     │  ██ 280ms     │
├──────────────┴──────────────┴───────────────┤
│  Recent Errors (last 1h)                    │
│  • TimeoutError in /api/chat (x3)           │
│  • ConnectionRefused qdrant:6333 (x1)       │
├─────────────────────────────────────────────┤
│  Dependencies        Status    Latency      │
│  PostgreSQL          ✅ UP     12ms         │
│  Qdrant              ✅ UP     8ms          │
│  Ollama/LLM          ✅ UP     1.2s         │
│  Redis               ✅ UP     2ms          │
└─────────────────────────────────────────────┘
```

## Tools
| Category | Tools |
|----------|-------|
| Metrics | Prometheus, Grafana, Datadog |
| Logging | ELK Stack, Loki, CloudWatch |
| Tracing | Jaeger, Zipkin, Tempo |
| Alerting | PagerDuty, OpsGenie, Alertmanager |
| APM | New Relic, Datadog APM, Elastic APM |

## See Also
- [agents/devops-engineer.md](../agents/devops-engineer.md) — infrastructure and monitoring setup
- [skills/deploy/README.md](../skills/deploy/README.md) — post-deploy monitoring checklist
- [rules/security.md](../rules/security.md) — incident response logging requirements
