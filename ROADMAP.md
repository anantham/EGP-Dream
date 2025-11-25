# Roadmap

## Phase 1: Stabilization (Immediate)
- [ ] **Async I/O:** Refactor image saving and metric writing to use `aiofiles` or run in a thread pool to prevent audio stutter.
- [ ] **Connection Isolation:** Refactor `State` to support multiple clients (or strictly enforce Broadcast mode).
- [ ] **Buffer Flush:** Implement `flush()` in `CloudAudioProcessor` to process the final audio chunk upon disconnect.
- [ ] **Error Handling:** Add `finally` blocks to Instrumentation to ensure failed API calls are recorded as errors (or at least allow the timer to close).

## Phase 2: "Scribe" Features
- [ ] **Read-Aloud:** Add Text-to-Speech (TTS) to read back the collected list of questions at the end of a session.
- [ ] **Export Formats:** Support PDF export of the session log with embedded thumbnails.
- [ ] **Topic Clustering:** Use an LLM to group questions by theme in the "Questions List" view.

## Phase 3: Advanced Audio
- [ ] **Speaker Diarization:** Distinguish between different speakers in the room.
- [ ] **VAD Tuning:** Expose Voice Activity Detection thresholds in Settings to handle noisy environments better.
- [ ] **Input Audio:** Allow uploading pre-recorded files for processing.

## Phase 4: Deployment
- [ ] **Docker Container:** Package the backend and frontend for easy deployment on non-macOS systems.
- [ ] **Remote Access:** Add authentication for accessing the UI over a local network.
