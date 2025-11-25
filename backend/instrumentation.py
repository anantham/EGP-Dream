import time
import json
import os
import asyncio
import threading
from pathlib import Path
from collections import defaultdict
import statistics

BASE_DIR = Path(__file__).resolve().parent
METRICS_FILE = BASE_DIR / "metrics.json"

class Instrumentation:
    def __init__(self):
        self.metrics = defaultdict(list)
        self._write_counter = 0
        self.load_metrics()

    def load_metrics(self):
        if METRICS_FILE.exists():
            try:
                with open(METRICS_FILE, 'r') as f:
                    data = json.load(f)
                    # Cap history on load to prevent memory bloat
                    for k, v in data.items():
                        self.metrics[k] = v[-100:] # Keep only last 100
                print("Metrics loaded.")
            except Exception as e:
                print(f"Failed to load metrics (resetting): {e}")
                self.metrics = defaultdict(list)

    def save_metrics(self):
        try:
            with open(METRICS_FILE, 'w') as f:
                json.dump(dict(self.metrics), f)
        except Exception as e:
            print(f"Metrics save failed: {e}")

    def _schedule_save(self):
        # Try to use the running loop; if none, fall back to a background thread
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(asyncio.to_thread(self.save_metrics))
        except RuntimeError:
            threading.Thread(target=self.save_metrics, daemon=True).start()

    def start_timer(self):
        return time.perf_counter()

    def end_timer(self, start_time, category, model_name):
        duration = time.perf_counter() - start_time
        key = f"{category}:{model_name}"
        self.metrics[key].append(duration)
        
        if len(self.metrics[key]) > 100:
            self.metrics[key].pop(0)
            
        # Throttle disk writes to every 5 samples
        self._write_counter += 1
        if self._write_counter % 5 == 0:
            self._schedule_save()
            
        return duration

    def get_averages(self):
        averages = {}
        for key, values in self.metrics.items():
            if values:
                averages[key] = round(statistics.mean(values), 3)
        return averages

instrumentation = Instrumentation()
