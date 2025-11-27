import os
import base64
from abc import ABC, abstractmethod
import google.generativeai as genai
from openai import AsyncOpenAI
from .instrumentation import instrumentation
from .pricing import pricing
from .config import OPENROUTER_API_KEY

class ImageGenerator(ABC):
    @abstractmethod
    async def generate(self, prompt: str, model_name: str) -> str:
        pass
    @abstractmethod
    def update_config(self, config: dict): pass

class GeminiImageGenerator(ImageGenerator):
    def update_config(self, config: dict):
         if 'gemini_api_key' in config:
            genai.configure(api_key=config['gemini_api_key'])

    async def generate(self, prompt: str, model_name: str) -> str:
        start_time = instrumentation.start_timer()
        pricing.track_image(model_name)
        
        try:
            target_model = model_name.replace("google/", "") 
            model = genai.GenerativeModel(target_model)
            print(f"[IMAGE] Gemini request model={target_model} prompt={prompt}")
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(response_modalities=["IMAGE"])
            )
            try:
                print(f"[IMAGE] Gemini response full={response}")
            except Exception:
                pass
            instrumentation.end_timer(start_time, "Phase C", model_name)
            
            if response.parts:
                for part in response.parts:
                    if part.inline_data:
                        return f"data:{part.inline_data.mime_type};base64,{base64.b64encode(part.inline_data.data).decode('utf-8')}"
            return ""
        except Exception as e:
            print(f"Gemini Image Error: {e}")
            return ""

class OpenRouterImageGenerator(ImageGenerator):
    def __init__(self):
        self.client = None

    def update_config(self, config: dict):
        key = config.get('openrouter_api_key') or OPENROUTER_API_KEY
        if key:
            self.client = AsyncOpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)

    async def generate(self, prompt: str, model_name: str) -> str:
        if not self.client: return ""
        start_time = instrumentation.start_timer()
        pricing.track_image(model_name)
        
        try:
            print(f"[IMAGE] OpenRouter request model={model_name} prompt={prompt}")
            response = await self.client.images.generate(
                model=model_name,
                prompt=prompt,
                n=1, size="1024x1024", response_format="b64_json"
            )
            try:
                print(f"[IMAGE] OpenRouter response full={response}")
                if hasattr(response, 'model_dump_json'):
                    print(f"[IMAGE] OpenRouter response json={response.model_dump_json()}")
            except Exception:
                pass
            instrumentation.end_timer(start_time, "Phase C", model_name)
            if response.data:
                return f"data:image/png;base64,{response.data[0].b64_json}"
            return ""
        except Exception as e:
             print(f"OpenRouter Image Error: {e}")
             return ""

def get_image_generator(model_name: str) -> ImageGenerator:
    if "google/gemini" in model_name and "via openrouter" not in model_name.lower():
        return GeminiImageGenerator()
    else:
        return OpenRouterImageGenerator()
