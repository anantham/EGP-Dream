import time
import json
import os
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
                    for k, v in data.items():
                        self.metrics[k] = v
                print("Metrics loaded from disk.")
            except Exception as e:
                print(f"Failed to load metrics: {e}")

    def save_metrics(self):
        try:
            with open(METRICS_FILE, 'w') as f:
                # Convert defaultdict to dict for JSON serialization
                json.dump(dict(self.metrics), f, indent=2)
        except Exception as e:
            print(f"Failed to save metrics: {e}")

    def start_timer(self):
        return time.perf_counter()

    def end_timer(self, start_time, category, model_name):
        duration = time.perf_counter() - start_time
        key = f"{category}:{model_name}"
        self.metrics[key].append(duration)
        
        # Keep only last 100 records (increased from 50 for better history)
        if len(self.metrics[key]) > 100:
            self.metrics[key].pop(0)
            
        self.save_metrics() # Save on every update (ok for low volume)
        return duration

    def get_averages(self):
        averages = {}
        for key, values in self.metrics.items():
            if values:
                averages[key] = round(statistics.mean(values), 3)
        return averages

instrumentation = Instrumentation()