import os
import asyncio
import base64
import json
import shutil
import numpy as np
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv

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
        
        self.api_keys = {
            "gemini_api_key": os.getenv("GEMINI_API_KEY"),
            "openrouter_api_key": os.getenv("OPENROUTER_API_KEY"),
            "openai_api_key": os.getenv("OPENAI_API_KEY")
        }
        
        self.audio_processor = get_audio_processor(self.audio_model)
        self.audio_processor.set_question_model(self.question_model)
        self.audio_processor.update_config(self.api_keys)
        
        self.image_generator = get_image_generator(self.image_model)
        self.image_generator.update_config(self.api_keys)
        
        self.image_queue = asyncio.Queue()
        self.display_queue = asyncio.Queue()
        self.processed_questions = set()
        self.all_questions = []
        self.session = SessionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected")
    
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
                
                questions_str = await state.audio_processor.process_audio(audio_np)
                
                if questions_str:
                    questions = questions_str.split('|||')
                    for q in questions:
                        q = q.strip()
                        if q and q not in state.processed_questions:
                            print(f"New Question: {q}")
                            state.processed_questions.add(q)
                            state.all_questions.append(q)
                            
                            await websocket.send_json({
                                "type": "questions_list",
                                "questions": state.all_questions
                            })
                            await state.image_queue.put(q)

            elif message['type'] == 'config':
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
                    "type": "status",
                    "message": "Session exported ready."
                })
                # In a real app, we'd send a download link, but here we rely on the known endpoint
                # or the button in UI that calls /api/export

    except WebSocketDisconnect:
        print("Client disconnected")
        # Flush audio buffer
        if hasattr(state.audio_processor, 'flush'):
             final_questions = await state.audio_processor.flush()
             if final_questions:
                 print(f"Flushed Questions: {final_questions}")
                 # We can't send them to closed socket, but we log them
    except Exception as e:
        print(f"WebSocket Error: {e}")
    finally:
        display_task.cancel()
        generator_task.cancel()

async def handle_config(message, state: ConnectionState):
    if 'geminiApiKey' in message: state.api_keys['gemini_api_key'] = message['geminiApiKey']
    if 'openRouterApiKey' in message: state.api_keys['openrouter_api_key'] = message['openRouterApiKey']
    if 'openaiApiKey' in message: state.api_keys['openai_api_key'] = message['openaiApiKey']
    
    # Logic to switch processors if model changed
    if 'audioModel' in message and message['audioModel'] != state.audio_model:
        # Flush old processor first
        if hasattr(state.audio_processor, 'flush'):
            await state.audio_processor.flush()
            
        state.audio_model = message['audioModel']
        state.audio_processor = get_audio_processor(state.audio_model)
        state.audio_processor.set_question_model(state.question_model)
        print(f"Switched Audio Model to {state.audio_model}")

    if 'questionModel' in message and message['questionModel'] != state.question_model:
        state.question_model = message['questionModel']
        state.audio_processor.set_question_model(state.question_model)
        
    if 'imageModel' in message and message['imageModel'] != state.image_model:
        state.image_model = message['imageModel']
        state.image_generator = get_image_generator(state.image_model)

    if 'minDisplayTime' in message:
        state.min_display_time = int(message['minDisplayTime'])
        
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
