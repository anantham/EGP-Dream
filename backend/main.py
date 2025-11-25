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
from dotenv import load_dotenv

from .processors import get_audio_processor
from .generators import get_image_generator
from .instrumentation import instrumentation
from .pricing import pricing
from .config import DEFAULT_AUDIO_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_QUESTION_MODEL

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SessionManager:
    def __init__(self):
        self.session_name = f"Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.session_dir = os.path.join("backend", "sessions", self.session_name)
        self.images_dir = os.path.join(self.session_dir, "images")
        self.ensure_dirs()
        self.log_file = os.path.join(self.session_dir, "session_log.json")
        self.history = []

    def ensure_dirs(self):
        os.makedirs(self.images_dir, exist_ok=True)

    def set_session_name(self, name):
        safe_name = "".join([c for c in name if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).strip()
        if not safe_name: return
        self.session_name = safe_name
        self.session_dir = os.path.join("backend", "sessions", self.session_name)
        self.images_dir = os.path.join(self.session_dir, "images")
        self.ensure_dirs()
        self.log_file = os.path.join(self.session_dir, "session_log.json")

    def log_item(self, question, image_filename, image_url):
        item = {
            "timestamp": datetime.now().isoformat(),
            "question": question,
            "image_file": image_filename
        }
        self.history.append(item)
        try:
            header, encoded = image_url.split(",", 1)
            ext = header.split(";")[0].split("/")[1]
            file_path = os.path.join(self.images_dir, f"{image_filename}.{ext}")
            with open(file_path, "wb") as f:
                f.write(base64.b64decode(encoded))
            with open(self.log_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except Exception as e:
            print(f"Failed to save session item: {e}")

    def export_zip(self):
        zip_filename = f"{self.session_name}.zip"
        zip_path = os.path.join("backend", "sessions", zip_filename)
        shutil.make_archive(os.path.join("backend", "sessions", self.session_name), 'zip', self.session_dir)
        return zip_path

class State:
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
        self.processed_questions = set()
        self.all_questions = []
        self.session = SessionManager()

state = State()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    display_task = asyncio.create_task(display_manager(websocket))
    generator_task = asyncio.create_task(image_worker(websocket))
    
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
                            state.processed_questions.add(q)
                            state.all_questions.append(q)
                            await websocket.send_json({
                                "type": "questions_list",
                                "questions": state.all_questions
                            })
                            await state.image_queue.put(q)

            elif message['type'] == 'config':
                await handle_config(message)
                
            elif message['type'] == 'get_metrics':
                await websocket.send_json({
                    "type": "metrics",
                    "data": {
                        "latency": instrumentation.get_averages(),
                        "cost": pricing.get_stats()
                    }
                })

    except WebSocketDisconnect:
        pass
    finally:
        display_task.cancel()
        generator_task.cancel()

async def handle_config(message):
    if 'geminiApiKey' in message: state.api_keys['gemini_api_key'] = message['geminiApiKey']
    if 'openRouterApiKey' in message: state.api_keys['openrouter_api_key'] = message['openRouterApiKey']
    if 'openaiApiKey' in message: state.api_keys['openai_api_key'] = message['openaiApiKey']
    
    if 'audioModel' in message and message['audioModel'] != state.audio_model:
        state.audio_model = message['audioModel']
        state.audio_processor = get_audio_processor(state.audio_model)
        state.audio_processor.set_question_model(state.question_model)

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
        pricing.reset_session() # Reset session cost on new session

    state.audio_processor.update_config(state.api_keys)
    state.image_generator.update_config(state.api_keys)

async def image_worker(websocket: WebSocket):
    while True:
        question = await state.image_queue.get()
        await websocket.send_json({"type": "status", "message": f"Dreaming about: {question}..."})
        image_url = await state.image_generator.generate(question, state.image_model)
        
        if image_url:
            filename = f"img_{int(datetime.now().timestamp())}"
            state.session.log_item(question, filename, image_url)
            await display_queue.put({"url": image_url, "prompt": question})
        else:
            await websocket.send_json({"type": "status", "message": "Failed to generate image"})
        state.image_queue.task_done()

display_queue = asyncio.Queue()

async def display_manager(websocket: WebSocket):
    while True:
        item = await display_queue.get()
        await websocket.send_json({
            "type": "image",
            "url": item['url'],
            "prompt": item['prompt']
        })
        await asyncio.sleep(state.min_display_time)
        display_queue.task_done()

@app.get("/api/export")
async def export_session():
    zip_path = state.session.export_zip()
    return FileResponse(zip_path, media_type='application/zip', filename=os.path.basename(zip_path))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)