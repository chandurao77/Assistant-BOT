// k6 Smoke Test — quick validation (1 VU, 30s)
// Usage:  k6 run k6/smoke-test.js
//   or:   podman compose --profile loadtest run k6 run /scripts/smoke-test.js

import http from 'k6/http';
import { check, sleep } from 'k6';

const BASE_URL = __ENV.BASE_URL || 'http://backend:8000';

export const options = {
  vus: 1,
  duration: '30s',
  thresholds: {
    http_req_duration: ['p(95)<2000'],  // 95% of requests under 2s
    http_req_failed: ['rate<0.01'],      // <1% failure rate
  },
};

export default function () {
  // Health check
  const healthRes = http.get(`${BASE_URL}/api/health`);
  check(healthRes, {
    'health status 200': (r) => r.status === 200,
    'health body has status': (r) => JSON.parse(r.body).status !== undefined,
  });

  // List conversations
  const convRes = http.get(`${BASE_URL}/api/conversations`);
  check(convRes, {
    'conversations status 200': (r) => r.status === 200,
  });

  // Chat suggestions
  const suggestRes = http.get(`${BASE_URL}/api/chat/suggestions`);
  check(suggestRes, {
    'suggestions status 200': (r) => r.status === 200,
  });

  // Feedback stats
  const feedbackRes = http.get(`${BASE_URL}/api/feedback/stats`);
  check(feedbackRes, {
    'feedback stats status 200': (r) => r.status === 200,
  });

  sleep(1);
}
