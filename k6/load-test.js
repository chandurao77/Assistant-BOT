// k6 Load Test — sustained traffic simulation
// Usage:  k6 run k6/load-test.js
//   or:   podman compose --profile loadtest run k6 run /scripts/load-test.js
//
// Simulates realistic usage: health checks, conversations browsing, chat queries.

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://backend:8000';

// Custom metrics
const chatSuccessRate = new Rate('chat_success_rate');
const chatDuration = new Trend('chat_duration', true);

export const options = {
  stages: [
    { duration: '30s', target: 5 },   // ramp up to 5 VUs
    { duration: '2m',  target: 10 },   // hold at 10 VUs
    { duration: '1m',  target: 20 },   // peak at 20 VUs
    { duration: '30s', target: 0 },    // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<5000'],   // 95% under 5s (LLM responses are slow)
    http_req_failed: ['rate<0.05'],      // <5% failure rate
    chat_success_rate: ['rate>0.90'],    // 90%+ chat completions
  },
};

// ── Test scenarios ──────────────────────────────────────────────────────────

export default function () {
  group('health_check', () => {
    const res = http.get(`${BASE_URL}/api/health`);
    check(res, { 'health 200': (r) => r.status === 200 });
  });

  group('browse_conversations', () => {
    const listRes = http.get(`${BASE_URL}/api/conversations`);
    check(listRes, { 'list conversations 200': (r) => r.status === 200 });

    // If there are conversations, fetch the first one
    if (listRes.status === 200) {
      try {
        const conversations = JSON.parse(listRes.body);
        if (Array.isArray(conversations) && conversations.length > 0) {
          const convId = conversations[0].id;
          const detailRes = http.get(`${BASE_URL}/api/conversations/${convId}`);
          check(detailRes, { 'conversation detail 200': (r) => r.status === 200 });
        }
      } catch (_) {
        // ignore parse errors
      }
    }
  });

  group('chat_query', () => {
    const conversationId = `loadtest-${__VU}-${__ITER}`;
    const payload = JSON.stringify({
      question: 'What is the onboarding process?',
      conversation_id: conversationId,
    });
    const params = {
      headers: { 'Content-Type': 'application/json' },
      timeout: '60s',
    };

    const start = Date.now();
    const res = http.post(`${BASE_URL}/api/chat/stream`, payload, params);
    const duration = Date.now() - start;

    chatDuration.add(duration);
    const success = res.status === 200;
    chatSuccessRate.add(success);

    check(res, {
      'chat stream 200': (r) => r.status === 200,
      'chat has content': (r) => r.body && r.body.length > 0,
    });
  });

  group('metrics_and_feedback', () => {
    const metricsRes = http.get(`${BASE_URL}/api/health/metrics`);
    check(metricsRes, { 'metrics 200': (r) => r.status === 200 });

    const statsRes = http.get(`${BASE_URL}/api/feedback/stats`);
    check(statsRes, { 'feedback stats 200': (r) => r.status === 200 });
  });

  sleep(Math.random() * 2 + 1);  // 1-3s think time
}
