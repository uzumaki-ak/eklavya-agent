"""Load test — verifies the API stays responsive under concurrent users.

Run against a running docker compose stack:
    pip install locust
    locust -f loadtest/locustfile.py --host http://localhost:3000

Then open http://localhost:8089 and set users=100, spawn-rate=10.

What to actually watch (this is an LLM app, not a throughput benchmark):
  - POST /api/generate must stay fast (~tens of ms). It only enqueues; if this
    slows down, the API is blocking on something it shouldn't be.
  - Job completion time is dominated by Anthropic's latency and your rate limit,
    NOT by this stack. Seeing slow completions with a fast enqueue is correct.
  - Repeated topics should return cache_hit=true and complete instantly — that
    is the single-flight + cache path working.
  - 429s from Anthropic mean LLM_MAX_CONCURRENCY is set too high for your tier.
"""

import random
import uuid

from locust import HttpUser, between, task

# A small topic pool on purpose: real classroom traffic is highly repetitive,
# so this also exercises the cache and single-flight paths.
TOPICS = [
    (4, "Types of angles"),
    (4, "Fractions"),
    (3, "The water cycle"),
    (5, "States of matter"),
    (6, "Photosynthesis"),
]


class LearnerUser(HttpUser):
    wait_time = between(1, 4)

    def on_start(self):
        self.session_id = str(uuid.uuid4())

    @task(3)
    def generate_and_poll(self):
        grade, topic = random.choice(TOPICS)

        with self.client.post(
            "/api/generate",
            json={"grade": grade, "topic": topic},
            headers={
                "X-Session-Id": self.session_id,
                "Idempotency-Key": str(uuid.uuid4()),
            },
            name="POST /api/generate",
            catch_response=True,
        ) as response:
            if response.status_code != 202:
                response.failure(f"expected 202, got {response.status_code}")
                return
            job_id = response.json()["job_id"]

        # One poll only — this measures API responsiveness, not LLM latency.
        self.client.get(f"/api/jobs/{job_id}", name="GET /api/jobs/[id]")

    @task(1)
    def health(self):
        self.client.get("/health", name="GET /health")

    @task(1)
    def idempotency_replay(self):
        """The same key twice must produce one job, not two."""
        key = str(uuid.uuid4())
        grade, topic = random.choice(TOPICS)
        payload = {"grade": grade, "topic": topic}
        headers = {"X-Session-Id": self.session_id, "Idempotency-Key": key}

        first = self.client.post(
            "/api/generate", json=payload, headers=headers, name="POST /api/generate [idem]"
        )
        second = self.client.post(
            "/api/generate", json=payload, headers=headers, name="POST /api/generate [idem replay]"
        )

        if first.status_code == 202 and second.status_code == 202:
            if first.json()["job_id"] != second.json()["job_id"]:
                second.failure("idempotency key produced two different jobs")
