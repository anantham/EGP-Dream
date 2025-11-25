import time
import json
import os
import asyncio
from collections import defaultdict
import statistics

METRICS_FILE = "metrics.json"

class Instrumentation:
    def __init__(self):
        self.metrics = defaultdict(list)
        self.load_metrics()

    def load_metrics(self):
        if os.path.exists(METRICS_FILE):
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
        # Sync wrapper for now, but main.py calls this via side-effect?
        # Ideally we should not block. We will use a fire-and-forget thread approach internally
        # or just rely on the fact that we call this less frequently.
        # But end_timer calls it EVERY TIME.
        
        # Simple optimization: Only save every 10 samples or use background task
        # For simplicity/safety, let's just do a quick fire-and-forget write
        asyncio.create_task(self._async_save())

    async def _async_save(self):
        try:
            await asyncio.to_thread(self._write_file)
        except Exception as e:
            print(f"Metrics save failed: {e}")

    def _write_file(self):
        try:
            with open(METRICS_FILE, 'w') as f:
                json.dump(dict(self.metrics), f)
        except: pass

    def start_timer(self):
        return time.perf_counter()

    def end_timer(self, start_time, category, model_name):
        duration = time.perf_counter() - start_time
        key = f"{category}:{model_name}"
        self.metrics[key].append(duration)
        
        if len(self.metrics[key]) > 100:
            self.metrics[key].pop(0)
            
        # Trigger non-blocking save
        # We need a running loop. If called from sync context, this might fail.
        # But our app is fully async.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._async_save())
        except RuntimeError:
            pass # No loop running (e.g. unit test)
            
        return duration

    def get_averages(self):
        averages = {}
        for key, values in self.metrics.items():
            if values:
                averages[key] = round(statistics.mean(values), 3)
        return averages

instrumentation = Instrumentation()
