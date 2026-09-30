// k6 Stress Test — find the breaking point
// Usage:  k6 run k6/stress-test.js
//   or:   podman compose --profile loadtest run k6 run /scripts/stress-test.js
//
// Progressively increases load until the system degrades. Use to find
// max concurrency limits before production deployment.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://backend:8000';

const errorRate = new Rate('errors');

export const options = {
  stages: [
    { duration: '30s', target: 10 },   // warm up
    { duration: '1m',  target: 30 },   // moderate load
    { duration: '1m',  target: 50 },   // heavy load
    { duration: '1m',  target: 80 },   // stress
    { duration: '1m',  target: 100 },  // peak
    { duration: '30s', target: 0 },    // recovery
  ],
  thresholds: {
    errors: ['rate<0.30'],              // note degradation above 30%
    http_req_duration: ['p(99)<15000'], // even at stress, 99th < 15s
  },
};

export default function () {
  // Mix of read-heavy endpoints (realistic traffic distribution)
  const rand = Math.random();

  if (rand < 0.40) {
    // 40% — health checks (lightweight, simulates monitoring)
    const res = http.get(`${BASE_URL}/api/health`);
    errorRate.add(res.status !== 200);
    check(res, { 'health ok': (r) => r.status === 200 });

  } else if (rand < 0.70) {
    // 30% — browse conversations
    const res = http.get(`${BASE_URL}/api/conversations`);
    errorRate.add(res.status !== 200);
    check(res, { 'conversations ok': (r) => r.status === 200 });

  } else if (rand < 0.85) {
    // 15% — chat queries
    const payload = JSON.stringify({
      question: 'How do I set up my development environment?',
      conversation_id: `stress-${__VU}-${__ITER}`,
    });
    const params = {
      headers: { 'Content-Type': 'application/json' },
      timeout: '60s',
    };
    const res = http.post(`${BASE_URL}/api/chat/stream`, payload, params);
    errorRate.add(res.status !== 200);
    check(res, { 'chat ok': (r) => r.status === 200 });

  } else {
    // 15% — metrics + feedback stats
    const res = http.get(`${BASE_URL}/api/health/metrics`);
    errorRate.add(res.status !== 200);
    check(res, { 'metrics ok': (r) => r.status === 200 });
  }

  sleep(Math.random() * 0.5);  // 0-500ms think time (aggressive)
}
