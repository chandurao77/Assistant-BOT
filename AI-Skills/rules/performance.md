# Rule: Performance

## Budgets
Define budgets **before** building. Measure continuously.

### Backend
| Metric | Budget | Measurement |
|--------|--------|-------------|
| API P50 latency | < 100ms | Server-side timing |
| API P95 latency | < 500ms | Server-side timing |
| API P99 latency | < 2s | Server-side timing |
| Database query | < 50ms | EXPLAIN ANALYZE |
| Throughput | > 100 RPS/core | Load test (k6) |
| Memory per request | < 50MB | Profiler |
| Cold start | < 5s | Container startup |

### Frontend
| Metric | Budget | Measurement |
|--------|--------|-------------|
| First Contentful Paint | < 1.5s | Lighthouse |
| Largest Contentful Paint | < 2.5s | Lighthouse |
| Time to Interactive | < 3.5s | Lighthouse |
| Cumulative Layout Shift | < 0.1 | Lighthouse |
| JS bundle (gzipped) | < 200KB | Build output |
| CSS bundle (gzipped) | < 50KB | Build output |
| Image size (per image) | < 200KB | Optimized assets |

## Backend Optimization

### Database
```sql
-- Always check query plans
EXPLAIN ANALYZE SELECT * FROM chunks WHERE space_key = 'ENG';

-- Add indexes for WHERE, JOIN, ORDER BY columns
CREATE INDEX idx_chunks_space ON chunks(space_key);

-- Use keyset pagination (not OFFSET)
SELECT * FROM chunks WHERE id > $last_id ORDER BY id LIMIT 20;
```

| Problem | Fix |
|---------|-----|
| N+1 queries | Eager load / batch fetch (joinedload, selectinload) |
| Full table scan | Add index on filtered columns |
| Large result sets | Paginate, add LIMIT |
| Slow JOINs | Check indexes on join columns, denormalize if needed |
| Lock contention | Shorter transactions, optimistic locking |

### Caching
```
Request → Check cache → Hit? Return cached
                    ↓ Miss
              Compute result → Store in cache → Return
```

| Cache Type | TTL | Use Case |
|-----------|-----|----------|
| HTTP cache (CDN) | 1-24h | Static assets, public API responses |
| Application cache (Redis) | 5-60min | Expensive computations, API responses |
| Semantic cache | 1-24h | LLM responses for similar queries |
| Query cache (DB) | Seconds | Repeated identical queries |
| In-memory (dict/LRU) | Request-scoped | Avoid repeated work within one request |

**Invalidation rules:**
- Invalidate on write — when underlying data changes
- Set TTL — maximum staleness you can tolerate
- Cache-aside pattern — application controls cache population

### Async & Concurrency
```python
# Run independent I/O operations concurrently
results = await asyncio.gather(
    fetch_chunks(query),
    fetch_user_context(user_id),
    check_cache(query),
)

# Use connection pooling — don't create connections per request
pool = asyncpg.create_pool(dsn, min_size=5, max_size=20)
```

## Frontend Optimization

### Bundle Size
```typescript
// Lazy load routes — don't load everything upfront
const Settings = React.lazy(() => import('./pages/Settings'));

// Tree-shake — use named imports
import { debounce } from 'lodash-es';  // Good: ~1KB
import _ from 'lodash';                 // Bad: ~70KB
```

### Rendering
```typescript
// Virtualize long lists — don't render 10,000 DOM nodes
import { useVirtualizer } from '@tanstack/react-virtual';

// Memoize expensive computations (only when profiling shows need)
const processed = useMemo(() => heavyComputation(data), [data]);

// Debounce user input
const debouncedSearch = useDebouncedCallback(onSearch, 300);
```

### Assets
- Serve images in WebP/AVIF with `<picture>` fallback
- Lazy load images below the fold (`loading="lazy"`)
- Use SVG for icons (scalable, cacheable, small)
- Compress: gzip for text, Brotli for static assets

## Anti-Patterns
| Anti-Pattern | Why It's Bad | Fix |
|-------------|-------------|-----|
| Premature optimization | Wasted effort, added complexity | Profile first, optimize bottlenecks |
| Caching everything | Memory bloat, stale data bugs | Cache only expensive + stable data |
| Synchronous I/O in async code | Blocks the event loop | Use async libraries or thread pool |
| No pagination | Memory explosion on large datasets | Always paginate list endpoints |
| Polling every second | Wastes bandwidth and CPU | Use SSE, WebSocket, or long-poll |
| SELECT * | Transfers unnecessary data | Select only needed columns |

## See Also
- [agents/performance-engineer.md](../agents/performance-engineer.md) — profiling and optimization expertise
- [skills/monitoring/README.md](../skills/monitoring/README.md) — tracking performance in production
- [agents/data-engineer.md](../agents/data-engineer.md) — database query optimization
