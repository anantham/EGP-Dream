# ADR 001: EGP Dream Architecture (v1)

## Status
Accepted / Prototype

## Context
We are building "EGP Dream," a voice-driven generative art installation. Users speak into a microphone; the system detects philosophical questions and generates full-screen artwork.
**Constraints:**
- Low latency is critical for "Magic Mirror" feel.
- Must support both Local (Privacy/Cost) and Cloud (Quality) models.
- Must run on macOS (Apple Silicon).

## Decisions

### 1. Hybrid Audio Pipeline
We support two distinct pipelines accessible via configuration:
*   **Local Pipeline:** `TheWhisper` (Streaming) → Text → Gemini/OpenRouter (Extraction).
    *   *Pros:* Immediate transcription feedback, free, high privacy.
    *   *Cons:* Multi-step latency (Phase A + Phase B).
*   **Cloud Pipeline:** Buffered Audio (6s) → Native API (Audio-to-Text/Question).
    *   *Pros:* potentially higher understanding of prosody.
    *   *Cons:* Minimum 6s latency (wait for buffer).

### 2. Global State Management
*   **Decision:** We use a singleton `State` class with global `asyncio.Queue`s.
*   **Implication:** This architecture assumes a **Single-Instance / Kiosk** deployment.
*   **Risk:** If multiple browser tabs connect, they will compete for the same queues (Race Condition).
*   **Mitigation:** Currently accepted for prototype. Future v2 will require `ConnectionManager` for per-client isolation or explicit Broadcast mode.

### 3. Synchronous Persistence
*   **Decision:** Images and logs are written to disk using standard blocking I/O (`open`, `json.dump`) within async handlers.
*   **Implication:** High I/O load will block the WebSocket heartbeat and audio processing.
*   **Acceptance:** Acceptable for < 1 image generation per 10 seconds. Unacceptable for high-load.

### 4. Instrumentation & Pricing
*   **Decision:** Metrics are persisted to `metrics.json` on every sample.
*   **Implication:** Provides crash-resilience for data, but introduces write amplification.

## Consequences
*   **Positive:** Extremely fast iteration speed; "plug-and-play" model switching.
*   **Negative:** The server is not thread-safe for multiple concurrent users. The audio buffer logic drops the last chunk on disconnect.
