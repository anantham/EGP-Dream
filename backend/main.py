import os
import asyncio
import base64
import json
import shutil
import numpy as np
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv

# Simple timestamped logger
def log(msg: str):
    print(f"[{datetime.now().isoformat()}] {msg}")

# Compatibility shim: importlib.metadata on Python 3.9 lacks packages_distributions
try:
    import importlib.metadata as _md
    if not hasattr(_md, "packages_distributions"):
        import importlib_metadata as _md_backport  # type: ignore
        _md.packages_distributions = _md_backport.packages_distributions
except Exception as e:
    print(f"Importlib metadata shim failed: {e}")

from .processors import get_audio_processor
from .generators import get_image_generator
from .instrumentation import instrumentation
from .pricing import pricing
from .config import DEFAULT_AUDIO_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_QUESTION_MODEL

load_dotenv()

# Define Base Path
BASE_DIR = Path(__file__).resolve().parent.parent
SESSION_ROOT = BASE_DIR / "backend" / "sessions"

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SessionManager:
    def __init__(self, session_name=None):
        if not session_name:
            session_name = f"Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_name = session_name
        self.session_dir = SESSION_ROOT / self.session_name
        self.images_dir = self.session_dir / "images"
        self.log_file = self.session_dir / "session_log.json"
        self.history = []
        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(self.images_dir, exist_ok=True)

    def set_session_name(self, name):
        safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        if not safe_name: return
        self.session_name = safe_name
        self.session_dir = SESSION_ROOT / self.session_name
        self.images_dir = self.session_dir / "images"
        self.log_file = self.session_dir / "session_log.json"
        self.ensure_dirs()

    async def log_item(self, question, image_filename, image_url):
        item = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "image_file": image_filename
        }
        self.history.append(item)
        
        # Offload blocking I/O to thread
        await asyncio.to_thread(self._save_to_disk, image_filename, image_url)

    def _save_to_disk(self, image_filename, image_url):
        try:
            header, encoded = image_url.split(",", 1)
            ext = header.split(";")[0].split("/")[1]
            file_path = self.images_dir / f"{image_filename}.{ext}"
            
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(encoded))
            
            with open(self.log_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            print(f"Failed to save session item: {e}")

    async def export_zip(self):
        zip_filename = f"{self.session_name}.zip"
        zip_path = SESSION_ROOT / zip_filename
        await asyncio.to_thread(
            shutil.make_archive,
            str(SESSION_ROOT / self.session_name),
            'zip',
            str(self.session_dir)
        )
        return zip_path

# Per-Connection State
class ConnectionState:
    def __init__(self):
        self.audio_model = DEFAULT_AUDIO_MODEL
        self.question_model = DEFAULT_QUESTION_MODEL
        self.image_model = DEFAULT_IMAGE_MODEL
        self.min_display_time = 6
        self.debug = False
        
        self.api_keys = {
            "gemini_api_key": os.getenv("GEMINI_API_KEY"),
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "openai_api_key": os.getenv("OPENAI_API_KEY")
        }
        log(f"[CONFIG] Loaded API keys from env: gemini={'set' if self.api_keys['gemini_api_key'] else 'missing'}, openrouter={'set' if self.api_keys['openrouter_api_key'] else 'missing'}, openai={'set' if self.api_keys['openai_api_key'] else 'missing'}")
        log(f"[CONFIG] Defaults: audio={self.audio_model}, question={self.question_model}, image={self.image_model}, minDisplayTime={self.min_display_time}")
        
        self.audio_processor = get_audio_processor(self.audio_model)
        self.audio_processor.set_question_model(self.question_model)
        self.audio_processor.update_config(self.api_keys)
        log(f"[CONFIG] Audio processor class={type(self.audio_processor).__name__}")
        
        self.image_generator = get_image_generator(self.image_model)
        self.image_generator.update_config(self.api_keys)
        log(f"[CONFIG] Image generator class={type(self.image_generator).__name__}")
        
        self.image_queue = asyncio.Queue()
        self.display_queue = asyncio.Queue()
        self.processed_questions = set()
        self.all_questions = []
        self.session = SessionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log("Client connected")
    
    # Instantiate State PER CONNECTION
    state = ConnectionState()
    
    # Tasks
    display_task = asyncio.create_task(display_manager(websocket, state))
    generator_task = asyncio.create_task(image_worker(websocket, state))
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message['type'] == 'audio':
                if not message.get('data'): continue
                audio_bytes = base64.b64decode(message['data'])
                audio_np = np.frombuffer(audio_bytes, dtype=np.float32)
                
                if state.debug:
                    log(f"[AUDIO] Received chunk len={len(audio_np)} model={state.audio_model}")
                questions_str = await state.audio_processor.process_audio(audio_np)
                
                if questions_str:
                    try:
                        parsed = json.loads(questions_str)
                        if isinstance(parsed, list):
                            for item in parsed:
                                q = (item.get("question") or "").strip() if isinstance(item, dict) else ""
                                img_prompt = (item.get("image_prompt") or q).strip() if isinstance(item, dict) else ""
                                summary = (item.get("summary") or "").strip() if isinstance(item, dict) else ""
                                if q and q not in state.processed_questions:
                                    log(f"[QUESTION] New Question: {q}")
                                    state.processed_questions.add(q)
                                    state.all_questions.append(q)
                                    await websocket.send_json({
                                        "type": "questions_list",
                                        "questions": state.all_questions
                                    })
                                    await state.image_queue.put(img_prompt or q)
                                elif summary:
                                    await websocket.send_json({"type": "status", "message": f"Summary: {summary}"})
                        elif isinstance(parsed, dict):
                            q = parsed.get("question", "").strip()
                            img_prompt = parsed.get("image_prompt", q).strip()
                            summary = parsed.get("summary", "").strip()
                            if q and q not in state.processed_questions:
                                log(f"[QUESTION] New Question: {q}")
                                state.processed_questions.add(q)
                                state.all_questions.append(q)
                                await websocket.send_json({
                                    "type": "questions_list",
                                    "questions": state.all_questions
                                })
                                await state.image_queue.put(img_prompt or q)
                            elif summary:
                                await websocket.send_json({"type": "status", "message": f"Summary: {summary}"})
                        else:
                            log(f"[QUESTION] Unexpected JSON question format: {parsed}")
                    except Exception:
                        questions = questions_str.split('|||')
                        for q in questions:
                            q = q.strip()
                            if q and q not in state.processed_questions:
                                log(f"[QUESTION] New Question: {q}")
                                state.processed_questions.add(q)
                                state.all_questions.append(q)
                                
                                await websocket.send_json({
                                    "type": "questions_list",
                                    "questions": state.all_questions
                                })
                                await state.image_queue.put(q)
                    if state.debug and hasattr(state.audio_processor, "last_debug_text"):
                        await websocket.send_json({"type": "debug_text", "text": getattr(state.audio_processor, "last_debug_text", "")})

            elif message['type'] == 'config':
                log(f"[WS] Config message received: {message}")
                await handle_config(message, state)
                
            elif message['type'] == 'get_metrics':
                await websocket.send_json({
                    "type": "metrics",
                    "data": {
                        "latency": instrumentation.get_averages(),
                        "cost": pricing.get_stats()
                    }
                })
            
            elif message['type'] == 'export_session':
                # Trigger export and send back URL
                zip_path = await state.session.export_zip()
                await websocket.send_json({
                    "type": "export_ready",
                    "path": f"/api/export?session_name={state.session.session_name}",
                    "message": "Session export ready."
                })

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"WebSocket Error: {e}")
    finally:
        # Flush any buffered audio and close network resources
        if hasattr(state.audio_processor, 'flush'):
            try:
                await state.audio_processor.flush()
            except Exception as e:
                print(f"Flush error: {e}")
        if hasattr(state.audio_processor, 'close'):
            try:
                await state.audio_processor.close()
            except Exception as e:
                print(f"Close error: {e}")

        display_task.cancel()
        generator_task.cancel()

async def handle_config(message, state: ConnectionState):
    if 'geminiApiKey' in message and message['geminiApiKey']: 
        state.api_keys['gemini_api_key'] = message['geminiApiKey']
        log(f"[CONFIG] Gemini key set via config (length={len(message['geminiApiKey'])})")
    if 'openRouterApiKey' in message and message['openRouterApiKey']: 
        state.api_keys['openrouter_api_key'] = message['openRouterApiKey']
        log(f"[CONFIG] OpenRouter key set via config (length={len(message['openRouterApiKey'])})")
    if 'openaiApiKey' in message and message['openaiApiKey']: 
        state.api_keys['openai_api_key'] = message['openaiApiKey']
        log(f"[CONFIG] OpenAI key set via config (length={len(message['openaiApiKey'])})")
    if 'debug' in message: state.debug = bool(message['debug'])
    
    # Logic to switch processors if model changed
    if 'audioModel' in message and message['audioModel'] != state.audio_model:
        # Flush old processor first
        if hasattr(state.audio_processor, 'flush'):
            await state.audio_processor.flush()
            
        state.audio_model = message['audioModel']
        state.audio_processor = get_audio_processor(state.audio_model)
        state.audio_processor.set_question_model(state.question_model)
        log(f"[CONFIG] Switched Audio Model to {state.audio_model}")

    if 'questionModel' in message and message['questionModel'] != state.question_model:
        state.question_model = message['questionModel']
        state.audio_processor.set_question_model(state.question_model)
        log(f"[CONFIG] Switched Question Model to {state.question_model}")
        
    if 'imageModel' in message and message['imageModel'] != state.image_model:
        state.image_model = message['imageModel']
        state.image_generator = get_image_generator(state.image_model)
        log(f"[CONFIG] Switched Image Model to {state.image_model}")

    if 'minDisplayTime' in message:
        state.min_display_time = int(message['minDisplayTime'])
        log(f"[CONFIG] min_display_time set to {state.min_display_time}")
        
    if 'sessionName' in message:
        state.session.set_session_name(message['sessionName'])
        pricing.reset_session()

    # Push updates
    state.audio_processor.update_config(state.api_keys)
    state.image_generator.update_config(state.api_keys)

async def image_worker(websocket: WebSocket, state: ConnectionState):
    while True:
        question = await state.image_queue.get()
        try:
            await websocket.send_json({"type": "status", "message": f"Dreaming about: {question}..."})
            image_url = await state.image_generator.generate(question, state.image_model)
            
            if image_url:
                filename = f"img_{int(datetime.now().timestamp())}"
                await state.session.log_item(question, filename, image_url)
                
                # Send history update for navigation
                await websocket.send_json({
                    "type": "history_update",
                    "item": {"question": question, "url": image_url, "timestamp": datetime.now().isoformat()}
                })
                
                await state.display_queue.put({"url": image_url, "prompt": question})
            else:
                await websocket.send_json({"type": "status", "message": "Failed to generate image"})
        except Exception as e:
            print(f"Image Worker Error: {e}")
        finally:
            state.image_queue.task_done()

async def display_manager(websocket: WebSocket, state: ConnectionState):
    while True:
        item = await state.display_queue.get()
        try:
            await websocket.send_json({
                "type": "image",
                "url": item['url'],
                "prompt": item['prompt']
            })
            await asyncio.sleep(state.min_display_time)
        except Exception:
            break
        finally:
            state.display_queue.task_done()

# GLOBAL Export endpoint (Current limitation: assumes single active session or most recent)
# Since we moved SessionManager to ConnectionState, the global endpoint is tricky.
# For V1, we can instantiate a temporary manager or track the "last active" session globally.
# Better: The frontend already knows the session name. Pass it as query param.

@app.get("/api/export")
async def export_session(session_name: str = None):
    # If no name provided, pick most recent
    target_dir = SESSION_ROOT
    if not session_name:
        # Find newest folder
        all_sessions = sorted([d for d in target_dir.iterdir() if d.is_dir()], key=os.path.getmtime, reverse=True)
        if not all_sessions: return {"error": "No sessions found"}
        session_name = all_sessions[0].name
    
    zip_filename = f"{session_name}.zip"
    zip_path = SESSION_ROOT / zip_filename
    
    session_path = SESSION_ROOT / session_name
    if not session_path.exists():
         return {"error": "Session not found"}

    await asyncio.to_thread(
        shutil.make_archive,
        str(SESSION_ROOT / session_name),
        'zip',
        str(session_path)
    )
    return FileResponse(zip_path, media_type='application/zip', filename=zip_filename)


@app.get("/api/sessions")
async def list_sessions():
    sessions = []
    if SESSION_ROOT.exists():
        for d in SESSION_ROOT.iterdir():
            if d.is_dir():
                sessions.append({
                    "name": d.name,
                    "modified": os.path.getmtime(d)
                })
    sessions = sorted(sessions, key=lambda x: x['modified'], reverse=True)
    return JSONResponse(sessions)


@app.get("/api/session/{session_name}")
async def get_session(session_name: str):
    session_dir = SESSION_ROOT / session_name
    log_file = session_dir / "session_log.json"
    if not log_file.exists():
        return JSONResponse({"error": "Session not found"}, status_code=404)
    try:
        with open(log_file, 'r') as f:
            data = json.load(f)
        # Attach image URLs relative to server
        for item in data:
            img_file = item.get("image_file")
            if img_file:
                item["url"] = f"/api/session/{session_name}/image/{img_file}"
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/session/{session_name}/image/{image_file}")
async def get_session_image(session_name: str, image_file: str):
    # Expecting image_file to include extension
    img_path = SESSION_ROOT / session_name / "images" / image_file
    if not img_path.exists():
        return JSONResponse({"error": "Image not found"}, status_code=404)
    return FileResponse(img_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
