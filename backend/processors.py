import asyncio
import base64
import io
import wave
import json
import os
import numpy as np
import websockets
from abc import ABC, abstractmethod
import google.generativeai as genai
from thestage_speechkit.streaming import StreamingPipeline
from openai import AsyncOpenAI
from .instrumentation import instrumentation
from .pricing import pricing
from .config import GEMINI_API_KEY, OPENROUTER_API_KEY, OPENAI_API_KEY

# --- Phase B: Question Extraction Strategies ---

class QuestionExtractor(ABC):
    @abstractmethod
    async def extract(self, text: str) -> str: pass
    @abstractmethod
    def update_config(self, config: dict): pass

class NativeGeminiExtractor(QuestionExtractor):
    def __init__(self, model_name="gemini-2.5-flash"):
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)

    def update_config(self, config: dict):
        if 'gemini_api_key' in config and config['gemini_api_key']:
            genai.configure(api_key=config['gemini_api_key'])

    async def extract(self, text: str) -> str:
        prompt = f"""
        Analyze the transcript. Return ONLY the complete, philosophical, or salient questions asked. 
        Separate multiple questions with '|||'. If no clear question, return "NO".
        Transcript: "{text}"
        """
        try:
            response = await self.model.generate_content_async(prompt)
            result = response.text.strip()
            
            # Track Cost
            pricing.track_text(self.model_name, len(prompt), len(result))
            
            return "" if result == "NO" else result
        except Exception as e:
            print(f"Native Gemini Extract Error: {e}")
            return ""

class OpenRouterExtractor(QuestionExtractor):
    def __init__(self, model_name):
        self.model_name = model_name
        self.client = None

    def update_config(self, config: dict):
        key = config.get('openrouter_api_key') or OPENROUTER_API_KEY
        if key:
            self.client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=key,
            )

    async def extract(self, text: str) -> str:
        if not self.client: return ""
        prompt = f"""
        Analyze the transcript. Return ONLY the complete, philosophical, or salient questions asked. 
        Separate multiple questions with '|||'. If no clear question, return "NO".
        Transcript: "{text}"
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful scribe. Extract questions from the transcript. Return ONLY the questions separated by '|||' or 'NO'."},
                    {"role": "user", "content": prompt}
                ]
            )
            result = response.choices[0].message.content.strip()
            
            # Track Cost (Estimate from chars)
            pricing.track_text(self.model_name, len(prompt), len(result))
            
            return "" if result == "NO" else result
        except Exception as e:
            print(f"OpenRouter Extract Error: {e}")
            return ""

def get_question_extractor(model_name: str) -> QuestionExtractor:
    if "google/" in model_name or "openai/" in model_name or "meta-llama/" in model_name:
         return OpenRouterExtractor(model_name)
    else:
         return NativeGeminiExtractor(model_name)


# --- Phase A: Audio Processing ---

class AudioProcessor(ABC):
    @abstractmethod
    async def process_audio(self, audio_data: np.ndarray) -> str:
        pass

    @abstractmethod
    def update_config(self, config: dict):
        pass
    
    @abstractmethod
    def set_question_model(self, model_name: str):
        pass

    # Optional lifecycle hooks for buffered/network processors
    async def flush(self) -> str:
        """Flush any buffered audio and return pending questions."""
        return ""

    async def close(self):
        """Cleanup network resources."""
        return

# 1. Local Whisper (Streaming)
class LocalWhisperProcessor(AudioProcessor):
    def __init__(self):
        print("Initializing Local Whisper...")
        self.pipeline = StreamingPipeline(
            model='TheStageAI/thewhisper-large-v3-turbo',
            chunk_length_s=15,
            platform='apple',
        )
        self.extractor = NativeGeminiExtractor() 
        self.accumulated_text = ""
        self.last_check_text = ""
        self.config_cache = {}
        self.last_debug_text = ""

    def update_config(self, config: dict):
        self.config_cache = config
        self.extractor.update_config(config)

    def set_question_model(self, model_name: str):
        self.extractor = get_question_extractor(model_name)
        self.extractor.update_config(self.config_cache)
        print(f"LocalWhisper: Phase B Model Set to {model_name}")

    async def process_audio(self, audio_data: np.ndarray) -> str:
        start_time = instrumentation.start_timer()
        
        # Calculate duration for cost (Local is free but nice to track volume)
        duration = len(audio_data) / 16000.0
        pricing.track_audio("local_whisper", duration)
        self.last_debug_text = f"[LOCAL] Received {duration:.2f}s audio for model {self.pipeline.model}"
        
        self.pipeline.add_new_chunk(audio_data)
        approved, assumption = self.pipeline.process_new_chunk()
        
        if approved:
            self.accumulated_text += " " + approved
            self.accumulated_text = self.accumulated_text.strip()
            # Prune
            if len(self.accumulated_text) > 3000:
                self.accumulated_text = self.accumulated_text[-2000:]

        current_full_text = (self.accumulated_text + " " + assumption).strip()
        self.last_debug_text = current_full_text
        instrumentation.end_timer(start_time, "Phase A", "local_whisper")

        if not current_full_text:
            return ""

        # Heuristic: only check if new context added
        if len(current_full_text) - len(self.last_check_text) > 20 or '?' in current_full_text[len(self.last_check_text):]:
            self.last_check_text = current_full_text
            
            start_b = instrumentation.start_timer()
            questions = await self.extractor.extract(current_full_text)
            
            model_label = getattr(self.extractor, 'model_name', 'unknown')
            instrumentation.end_timer(start_b, "Phase B", model_label)
            print(f"[QUESTION] Extracted using {model_label}: {questions}")
            
            return questions
        return ""

# 2. OpenAI Realtime API (Streaming WebSocket)
class OpenAIRealtimeProcessor(AudioProcessor):
    def __init__(self, model_name="gpt-4o-realtime-preview-2024-10-01"):
        self.model_name = model_name
        self.api_key = None
        self.ws = None
        self.listener_task = None
        self.transcript_queue = asyncio.Queue(maxsize=10)
        self.extractor = NativeGeminiExtractor() 
        self.accumulated_text = ""
        self.last_check_text = ""
        self.config_cache = {}
        print(f"Initializing OpenAI Realtime: {model_name}")

    def update_config(self, config: dict):
        self.api_key = config.get('openai_api_key') or OPENAI_API_KEY
        self.config_cache = config
        self.extractor.update_config(config)

    def set_question_model(self, model_name: str):
        self.extractor = get_question_extractor(model_name)
        self.extractor.update_config(self.config_cache)
        print(f"OpenAIRealtime: Phase B Model Set to {model_name}")

    async def ensure_connection(self):
        if self.ws and not self.ws.closed:
            return
        
        if not self.api_key:
            print("OpenAI API Key missing for Realtime API")
            return

        url = f"wss://api.openai.com/v1/realtime?model={self.model_name}"
        header = {"Authorization": f"Bearer {self.api_key}", "OpenAI-Beta": "realtime=v1"}
        
        try:
            self.ws = await websockets.connect(url, additional_headers=header)
            print(f"[REALTIME] Connected to OpenAI Realtime WebSocket model={self.model_name}")
            
            # Init Session for Transcription
            await self.ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "modalities": ["text"], # We only want text back, not audio
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    }
                }
            }))
            # Start dedicated listener
            self.listener_task = asyncio.create_task(self._listen_loop())
            
        except Exception as e:
            print(f"[REALTIME] Connection Failed: {e}")

    def _float32_to_pcm16(self, audio_np: np.ndarray) -> bytes:
        return (audio_np * 32767).astype(np.int16).tobytes()

    async def _listen_loop(self):
        try:
            while self.ws and not self.ws.closed:
                msg = await self.ws.recv()
                event = json.loads(msg)
                if event.get('type') == 'conversation.item.input_audio_transcription.completed':
                    transcript = event.get('transcript', '')
                    if transcript:
                        # Backpressure: drop oldest if full
                        if self.transcript_queue.full():
                            try:
                                self.transcript_queue.get_nowait()
                                self.transcript_queue.task_done()
                            except asyncio.QueueEmpty:
                                pass
                        await self.transcript_queue.put(transcript)
        except Exception as e:
            print(f"[REALTIME] Listener error: {e}")

    async def process_audio(self, audio_data: np.ndarray) -> str:
        await self.ensure_connection()
        start_time = instrumentation.start_timer()
        duration = len(audio_data) / 16000.0
        pricing.track_audio(self.model_name, duration)
        try:
            if not self.ws:
                return ""
            
            # Send Audio
            pcm_base64 = base64.b64encode(self._float32_to_pcm16(audio_data)).decode('utf-8')
            await self.ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": pcm_base64
            }))
            self.last_debug_text = f"[REALTIME] Sent {duration:.2f}s chunk to {self.model_name}"
            # Drain any transcripts collected by listener
            while True:
                try:
                    transcript = self.transcript_queue.get_nowait()
                    self.accumulated_text += " " + transcript
                    self.accumulated_text = self.accumulated_text.strip()
                    self.transcript_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            self.last_debug_text = self.accumulated_text
            
        finally:
            instrumentation.end_timer(start_time, "Phase A", "openai_realtime")
        
        current_text = self.accumulated_text
        if len(current_text) - len(self.last_check_text) > 20 or '?' in current_text[len(self.last_check_text):]:
            self.last_check_text = current_text
            
            start_b = instrumentation.start_timer()
            questions = await self.extractor.extract(current_text)
            
            model_label = getattr(self.extractor, 'model_name', 'unknown')
            instrumentation.end_timer(start_b, "Phase B", model_label)
            
            return questions
            
        return ""

    async def close(self):
        if self.ws and not self.ws.closed:
            try:
                await self.ws.close()
            except Exception as e:
                print(f"Failed to close OpenAI Realtime socket: {e}")
        self.ws = None
        if self.listener_task:
            self.listener_task.cancel()
            self.listener_task = None

# 3. Cloud Batched (Gemini Native / OpenAI REST)
class CloudBatchedProcessor(AudioProcessor):
    def __init__(self, mode="gemini_flash_audio"):
        self.mode = mode
        self.buffer = []
        # Shorter chunks with overlap to improve completeness without waiting long
        self.chunk_limit = 16000 * 4  # ~4s
        self.overlap_size = 16000 * 2  # 2s overlap
        self.prev_tail = []
        self.client = None # For OpenRouter/OpenAI REST
        self.api_keys = {}
        self.last_debug_text = ""
        print(f"Initializing Cloud Batched: {mode}")

    def update_config(self, config: dict):
        self.api_keys = config
        if 'gemini_api_key' in config:
            genai.configure(api_key=config['gemini_api_key'])
        
        # Setup OpenAI Client for REST Mode
        if 'openai_api_key' in config:
             self.client = AsyncOpenAI(api_key=config['openai_api_key'])
        print(f"[CONFIG] CloudBatched mode={self.mode} configured gemini_key={'set' if config.get('gemini_api_key') else 'missing'} openai_key={'set' if config.get('openai_api_key') else 'missing'}")

    def set_question_model(self, model_name: str):
        pass 

    def _numpy_to_wav(self, audio_np: np.ndarray) -> bytes:
        audio_int16 = (audio_np * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) 
            wav_file.setframerate(16000)
            wav_file.writeframes(audio_int16.tobytes())
        return buffer.getvalue()

    async def process_audio(self, audio_data: np.ndarray) -> str:
        self.buffer.extend(audio_data.tolist())
        
        if len(self.buffer) >= self.chunk_limit:
            full_audio_list = self.prev_tail + self.buffer
            self.prev_tail = self.buffer[-self.overlap_size:]
            audio_np = np.array(full_audio_list, dtype=np.float32)
            self.buffer = [] 
            return await self._send_to_cloud(audio_np)
        return ""

    async def flush(self) -> str:
        """Send any remaining buffered audio."""
        if not self.buffer and not self.prev_tail:
            return ""
        full_audio_list = self.prev_tail + self.buffer
        self.buffer = []
        self.prev_tail = []
        audio_np = np.array(full_audio_list, dtype=np.float32)
        return await self._send_to_cloud(audio_np)

    async def _send_to_cloud(self, audio_np: np.ndarray) -> str:
        wav_data = self._numpy_to_wav(audio_np)
        duration = len(audio_np) / 16000.0
        pricing.track_audio(self.mode, duration)
        
        start_time = instrumentation.start_timer()
        timer_recorded = False
        # For debug display
        self.last_debug_text = f"Sent {duration:.1f}s audio chunk ({len(audio_np)} samples)"
        
        try:
            if "gemini" in self.mode:
                # Gemini Native (A+B)
                model = genai.GenerativeModel('gemini-2.5-flash') 
                prompt = "Listen to this audio. If there is a clear philosophical or salient question asked, transcribe ONLY the question text. If there is just conversation or silence, return 'NO'."
                print(f"[CLOUD] Sending Gemini audio request len={len(wav_data)} mode={self.mode}")
                response = await model.generate_content_async([
                    prompt,
                    {"mime_type": "audio/wav", "data": wav_data}
                ])
                print(f"[CLOUD] Gemini audio response: {response.text}")
                result = response.text.strip()
                instrumentation.end_timer(start_time, "Phase A+B", "gemini_native")
                timer_recorded = True
                return "" if result == "NO" else result

            elif "openai_rest_whisper" in self.mode:
                # OpenAI Whisper V1 REST (Phase A only usually, but we can ask for prompt?)
                # Actually Whisper REST is just Transcribe. We need Phase B after.
                if not self.client: 
                    return ""
                
                # 1. Transcribe (Phase A)
                # We need a file-like object with name
                wav_file = io.BytesIO(wav_data)
                wav_file.name = "audio.wav"
                
                transcript_resp = await self.client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=wav_file
                )
                text = transcript_resp.text
                instrumentation.end_timer(start_time, "Phase A", "openai_whisper_rest")
                timer_recorded = True
                
                if not text: 
                    return ""
                
                # 2. Extract Questions (Phase B) - Using whatever default or hardcoded model?
                # For simplicity, let's use GPT-4o-mini for this part
                start_b = instrumentation.start_timer()
                try:
                    extract_resp = await self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "Extract questions from transcript. Separated by ||| or return NO."},
                            {"role": "user", "content": text}
                        ]
                    )
                    questions = extract_resp.choices[0].message.content.strip()
                finally:
                    instrumentation.end_timer(start_b, "Phase B", "gpt-4o-mini")
                
                return "" if questions == "NO" else questions

        except Exception as e:
            print(f"Cloud Batched Error ({self.mode}): {e}")
            return ""
        finally:
            # If the branch didn't record a timer, record an error outcome to avoid silent drops
            if not timer_recorded:
                instrumentation.end_timer(start_time, "Phase A+B", f"{self.mode}_error")
        return ""

def get_audio_processor(mode: str) -> AudioProcessor:
    if mode == "local_whisper":
        return LocalWhisperProcessor()
    elif "realtime" in mode:
        # Support both 4o and Mini
        model = "gpt-4o-realtime-preview-2024-10-01" if "4o" in mode else "gpt-4o-mini-realtime-preview-2024-12-17"
        return OpenAIRealtimeProcessor(model)
    else:
        return CloudBatchedProcessor(mode)
