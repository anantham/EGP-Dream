import os
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Audio Models (Phase A or Phase A+B)
AUDIO_MODELS = {
    "local_whisper": "Local Whisper (TheWhisper) - Streaming (low latency)",
    "gemini_flash_audio": "Gemini 2.5 Flash (Native) - Batched ~4-6s, overlapping for completeness",
    "openai_realtime_4o": "GPT-4o Realtime (WebSocket) - Streaming (lowest latency)",
    "openai_realtime_mini": "GPT-4o Mini Realtime (WebSocket) - Streaming (low latency, cheaper)",
    "openai_rest_whisper": "Whisper V1 (REST) - Batched ~4-6s (slower, simpler)",
}

# Question Models (Phase B)
QUESTION_MODELS = {
    "gemini-2.5-flash": "Gemini 2.5 Flash (Native)",
    "google/gemini-2.5-flash-lite-preview-09-2025": "Gemini 2.5 Flash Lite Preview (OpenRouter)",
    "google/gemini-2.5-flash-lite": "Gemini 2.5 Flash Lite (OpenRouter)",
    "google/gemini-2.5-flash": "Gemini 2.5 Flash (OpenRouter)",
    "openai/gpt-4o-mini": "GPT-4o Mini (OpenRouter)",
    "meta-llama/llama-3.2-3b-instruct": "Llama 3.2 3B (OpenRouter)"
}

# Image Models (Phase C)
IMAGE_MODELS = {
    "google/gemini-2.5-flash-image": "Gemini 2.5 Flash Image (Native)",
    "google/gemini-2.5-flash-image-preview": "Gemini 2.5 Flash Image Preview (Native)",
    "google/gemini-3-pro-image-preview": "Gemini 3 Pro Image (NanoPro - Native)",
    "openai/gpt-5-image-mini": "GPT-5 Image Mini (OpenRouter)",
    "stabilityai/stable-diffusion-3-medium": "SD3 Medium (OpenRouter)" 
}

DEFAULT_AUDIO_MODEL = "openai_realtime_4o"
DEFAULT_QUESTION_MODEL = "gemini-2.5-flash"
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"
