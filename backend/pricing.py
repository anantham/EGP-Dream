import time
from collections import defaultdict

# Rates per unit (USD)
# Tokens are per 1M
# Audio is per minute where specified, or estimated via tokens
RATES = {
    # Audio (Phase A)
    "local_whisper": {"mode": "time", "rate": 0.0},
    "gemini_flash_audio": {"mode": "time", "rate": 0.004}, # ~$0.004/min (estimated input)
    "openai_realtime_4o": {"mode": "time", "rate": 0.24}, # Blended Estimate (Input + Output)
    "openai_realtime_mini": {"mode": "time", "rate": 0.06}, # Blended Estimate
    "openai_rest_whisper": {"mode": "time", "rate": 0.006},
    
    # Text/Question (Phase B) - Per 1M Tokens
    "gemini-2.5-flash": {"mode": "token", "input": 0.075, "output": 0.30},
    "google/gemini-2.5-flash-lite": {"mode": "token", "input": 0.075, "output": 0.30},
    "openai/gpt-4o-mini": {"mode": "token", "input": 0.15, "output": 0.60},
    "meta-llama/llama-3.2-3b-instruct": {"mode": "token", "input": 0.05, "output": 0.10}, # Cheap
    
    # Images (Phase C) - Per Image
    "google/gemini-2.5-flash-image": {"mode": "item", "rate": 0.035},
    "google/gemini-2.5-flash-image-preview": {"mode": "item", "rate": 0.035},
    "google/gemini-3-pro-image-preview": {"mode": "item", "rate": 0.050}, # Estimate
    "openai/gpt-5-image-mini": {"mode": "item", "rate": 0.040}, # Estimate
    "stabilityai/stable-diffusion-3-medium": {"mode": "item", "rate": 0.035}
}

class PriceTracker:
    def __init__(self):
        self.total_cost = 0.0
        self.session_cost = 0.0
        self.cost_breakdown = defaultdict(float)

    def track_audio(self, model_name, duration_seconds):
        # Normalize model name
        model_key = model_name
        if "gpt-4o-realtime" in model_name: model_key = "openai_realtime_4o"
        if "gpt-4o-mini-realtime" in model_name: model_key = "openai_realtime_mini"
        
        rate_info = RATES.get(model_key, {"mode": "time", "rate": 0})
        
        cost = 0.0
        if rate_info["mode"] == "time":
            cost = (duration_seconds / 60.0) * rate_info["rate"]
        
        self._add(cost, "Phase A: Audio")
        return cost

    def track_text(self, model_name, input_chars, output_chars):
        # Rough est: 4 chars = 1 token
        in_tokens = input_chars / 4
        out_tokens = output_chars / 4
        
        # Normalize
        key = model_name
        if "gemini" in model_name and "flash" in model_name: key = "gemini-2.5-flash"
        if "gpt-4o-mini" in model_name: key = "openai/gpt-4o-mini"
        
        rate_info = RATES.get(key, {"mode": "token", "input": 0, "output": 0})
        
        cost = 0.0
        if rate_info["mode"] == "token":
            cost += (in_tokens / 1_000_000) * rate_info["input"]
            cost += (out_tokens / 1_000_000) * rate_info["output"]
            
        self._add(cost, "Phase B: Text")
        return cost

    def track_image(self, model_name):
        rate_info = RATES.get(model_name, {"mode": "item", "rate": 0})
        cost = rate_info.get("rate", 0)
        self._add(cost, "Phase C: Image")
        return cost

    def _add(self, amount, category):
        self.total_cost += amount
        self.session_cost += amount
        self.cost_breakdown[category] += amount

    def get_stats(self):
        return {
            "total": round(self.total_cost, 5),
            "breakdown": {k: round(v, 5) for k, v in self.cost_breakdown.items()}
        }

    def reset_session(self):
        self.session_cost = 0.0
        # Total persists

pricing = PriceTracker()
