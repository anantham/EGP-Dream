# EGP Dream

> **"A Magic Mirror for Collective Inquiry"**

EGP Dream is a voice-driven generative art installation. It listens to a stream of consciousness, identifies deep or salient questions, and visualizes them instantly as high-resolution artwork.

## 🌟 Features

*   **Voice-to-Art:** Speak a question, see it visualized.
*   **Dual-Mode Audio:**
    *   **Local:** Uses `TheWhisper` on Apple Silicon for ultra-fast, private transcription.
    *   **Cloud:** Uses OpenAI Realtime or Gemini Flash Audio for enhanced understanding.
*   **Multi-Model Support:** Switch between Gemini 2.5 Flash, GPT-4o, and OpenRouter models on the fly.
*   **Session Recording:** Automatically saves all detected questions and generated images.
*   **Live Metrics:** Tracks latency and estimated cost ($) in real-time.

## 🚀 Quick Start

### Prerequisites
*   macOS (Apple Silicon recommended)
*   Python 3.10+
*   Node.js 18+
*   `ffmpeg` (optional, for audio encoding)

### Installation

1.  **Backend**
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r backend/requirements.txt
    ```

2.  **Frontend**
    ```bash
    cd frontend
    npm install
    ```

### Running the App

1.  **Start the Server (Dual Process)**
    ```bash
    # Terminal 1 (Backend)
    source .venv/bin/activate
    uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

    # Terminal 2 (Frontend)
    cd frontend
    npm run dev
    ```

2.  **Open the App**
    *   Go to `http://localhost:5173`
    *   Click **Settings** (bottom right) to enter your API Keys (Gemini, OpenAI, or OpenRouter).
    *   Click **Mic** (bottom left) to start dreaming.

## 📂 Project Structure

*   `backend/` - FastAPI server, audio processing, and logic.
    *   `main.py` - WebSocket handler and state management.
    *   `processors.py` - Audio pipeline (Whisper, Realtime, Batched).
    *   `generators.py` - Image generation logic.
    *   `pricing.py` - Cost estimation.
*   `frontend/` - React + Vite application.
*   `docs/` - Architecture decisions.

## 🔑 Configuration

| Key | Purpose | Required For |
| --- | --- | --- |
| `GEMINI_API_KEY` | Question extraction, Image gen | Default Mode |
| `OPENAI_API_KEY` | Realtime Audio, GPT-4o | Cloud Mode |
| `OPENROUTER_KEY` | Alternative LLMs/Images | Phase B/C (Optional) |

## ⚠️ Known Limitations
*   **Single Session:** Designed as a kiosk. Multiple open tabs will share the same state.
*   **Audio Buffering:** In "Cloud Batched" mode, the very last few seconds of speech may be dropped when you hit pause.
