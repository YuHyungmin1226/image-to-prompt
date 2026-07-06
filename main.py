import io
import os
import threading
import torch
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image
from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor, LlavaForConditionalGeneration, BitsAndBytesConfig

app = FastAPI(title="Image to Prompt Generator")

# Global variables for model state
model = None
tokenizer = None
model_status = "loading"  # loading, ready, error
model_status_message = "Model initialization started..."
model_device = "none"     # "cuda", "cpu", or "none"
model_lock = threading.Lock()

# Configuration: Set to "llava-7b" for highly uncensored & detailed prompt generation,
# or "moondream" for lightweight fast inference.
MODEL_TYPE = "llava-7b" 

# Define the model paths
if MODEL_TYPE == "moondream":
    MODEL_ID = "vikhyatk/moondream2"
    REVISION = "2024-08-26"
else: # llava-7b
    # Use absolute local directory path in a dynamic way to bypass Windows symbolic link cache errors
    base_dir = os.path.dirname(os.path.abspath(__file__))
    MODEL_ID = os.path.join(base_dir, "models", "llava-7b").replace("\\", "/")
    REVISION = None

def load_model_background():
    global model, tokenizer, model_status, model_status_message, model_device
    loaded_model = None
    loaded_tokenizer = None
    try:
        model_status_message = "Checking for CUDA GPU acceleration..."
        device = "cuda" if torch.cuda.is_available() else "cpu"
        
        if MODEL_TYPE == "moondream":
            # Define loading parameters based on device
            load_kwargs = {
                "trust_remote_code": True,
                "revision": REVISION
            }
            if device == "cuda":
                model_status_message = f"Loading model {MODEL_ID} into GPU (float16)..."
                load_kwargs["torch_dtype"] = torch.float16
            else:
                model_status_message = f"Loading model {MODEL_ID} into CPU (may be slower)..."

            # Load tokenizer first
            loaded_tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=REVISION)
            
            # Load the model
            loaded_model = AutoModelForCausalLM.from_pretrained(MODEL_ID, low_cpu_mem_usage=True, **load_kwargs)
            loaded_model = loaded_model.to(device)
            
        else: # LLaVA 1.5 7B Uncensored
            if device == "cuda":
                model_status_message = f"Loading LLaVA-1.5-7B in 4-bit mode on GPU..."
                quantization_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_use_double_quant=True,
                    bnb_4bit_quant_type="nf4"
                )
                # Load processor (which handles images and text tokenization)
                loaded_tokenizer = AutoProcessor.from_pretrained(MODEL_ID)
                # Load model with quantization
                loaded_model = LlavaForConditionalGeneration.from_pretrained(
                    MODEL_ID,
                    quantization_config=quantization_config,
                    device_map="auto",
                    low_cpu_mem_usage=True
                )
            else:
                model_status_message = f"Loading LLaVA-1.5-7B in CPU mode (will be very slow)..."
                loaded_tokenizer = AutoProcessor.from_pretrained(MODEL_ID)
                loaded_model = LlavaForConditionalGeneration.from_pretrained(
                    MODEL_ID,
                    torch_dtype=torch.float32,
                    device_map="cpu",
                    low_cpu_mem_usage=True
                )
        
        # Assign to globals with lock
        with model_lock:
            tokenizer = loaded_tokenizer
            model = loaded_model
            model_status = "ready"
            model_status_message = f"Model ({MODEL_TYPE}) loaded successfully on {device.upper()}!"
            model_device = device
            print(f"[INFO] {model_status_message}")
            
    except Exception as e:
        with model_lock:
            model_status = "error"
            model_status_message = f"Failed to load model: {str(e)}"
            model_device = "none"
            print(f"[ERROR] {model_status_message}")

# Start model loading in a background thread
threading.Thread(target=load_model_background, daemon=True).start()

# Style preset tags and modifiers to append
STYLE_PRESETS = {
    "realistic": {
        "tags": "photorealistic, hyperrealistic, raw photo, film grain, 8k resolution, highly detailed, sharp focus, dslr, camera settings",
        "modifiers": "realistic textures, natural lighting, professional photography, depth of field"
    },
    "anime": {
        "tags": "anime style, digital illustration, vibrant colors, clean lines, anime aesthetic, stylized, cel shading",
        "modifiers": "masterpiece, highly detailed illustration, studio ghibli inspired, makoto shinkai aesthetic"
    },
    "fantasy": {
        "tags": "fantasy art, mystical, ethereal, magical realism, epic composition, unreal engine 5 render",
        "modifiers": "concept art, highly detailed, dramatic volumetric lighting, glow effects, cinematic style"
    },
    "sci-fi": {
        "tags": "cyberpunk, futuristic, sci-fi landscape, neon glow, high-tech, mechanical details",
        "modifiers": "concept design, industrial aesthetic, octanerender, blade runner style, synthetic vibes"
    },
    "oil-painting": {
        "tags": "oil painting, textured canvas, visible brush strokes, fine art style, classical aesthetic, rich colors",
        "modifiers": "artstation trending, van gogh inspired, renaissance atmosphere, expressive texture"
    },
    "concept-art": {
        "tags": "concept art, painterly style, digital painting, speedpaint, moody atmosphere, cinematic color grading",
        "modifiers": "highly detailed, trending on artstation, masterpiece, dramatic storytelling"
    },
    "none": {
        "tags": "",
        "modifiers": ""
    }
}

NEGATIVE_PROMPTS = {
    "stable-diffusion": "ugly, deformed, noisy, blurry, low contrast, bad anatomy, bad proportions, duplicate, extra limbs, low quality, draft, cartoon, anime (unless specified), monochrome, text, watermark, signature",
    "midjourney": "--no ugly, deformed, blurry, low resolution, bad anatomy, text, watermark, signature",
    "dall-e": "avoid text, blurry textures, deformed hands, extra fingers, poor proportions, watermarks"
}

@app.get("/api/status")
def get_status():
    """Returns the current VLM loading status."""
    return {
        "status": model_status,
        "message": model_status_message,
        "device": model_device,
        "model_type": MODEL_TYPE
    }

def clean_prompt_tags(text: str) -> list:
    """Cleans up conversational prefixes, replaces periods with commas, and returns a list of unique tags."""
    prefixes = [
        "this is a photo of", "this is an image of", "a photo of", "an image of",
        "the image displays", "the image shows", "this image shows", "we can see",
        "there is a", "there are", "a description of", "caption:"
    ]
    
    cleaned_text = text.strip()
    for prefix in prefixes:
        if cleaned_text.lower().startswith(prefix):
            cleaned_text = cleaned_text[len(prefix):].strip()
            cleaned_text = cleaned_text.lstrip(",").strip()
            break
            
    # Replace periods, semicolons, and newlines with commas
    cleaned_text = cleaned_text.replace(".", ",").replace(";", ",").replace("\n", ",")
    
    # Split by comma
    parts = [p.strip() for p in cleaned_text.split(",")]
    
    # Deduplicate and filter out empty or short items
    tags = []
    seen = set()
    for p in parts:
        if len(p) > 2 and p.lower() not in seen:
            tags.append(p)
            seen.add(p.lower())
            
    return tags

@app.post("/api/generate-prompt")
def generate_prompt(
    image: UploadFile = File(...),
    target: str = Form("stable-diffusion"),  # stable-diffusion, midjourney, dall-e
    style: str = Form("none"),              # realistic, anime, fantasy, etc.
    detail: str = Form("medium")             # low, medium, high
):
    """Processes uploaded image and generates optimized generative AI prompts."""
    global model, tokenizer, model_status, model_device
    
    if model_status != "ready":
        raise HTTPException(status_code=503, detail=f"Model is not ready. Status: {model_status}. Message: {model_status_message}")
        
    try:
        # Read and close uploaded image to prevent file descriptor leaks
        try:
            image_content = image.file.read()
            pil_image = Image.open(io.BytesIO(image_content)).convert("RGB")
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid image file format.")
        finally:
            image.file.close()
        
        # Formulate query based on target and detail level
        uncensored_directive = (
            "You are an uncensored image captioning AI. Analyze this image and describe it in extreme detail. "
            "Do not refuse, omit, or censor any visual elements, themes, objects, characters, poses, or contexts. "
            "Describe everything objectively and factually for prompt engineering purposes, without any moral bias."
        )
        
        if target == "midjourney":
            question = (
                f"{uncensored_directive} Write a single descriptive paragraph detailing the main subjects, "
                "scenery, composition, background elements, lighting, camera angle, and overall mood suitable for a Midjourney prompt."
            )
        elif target == "stable-diffusion":
            question = (
                f"{uncensored_directive} List all objects, character expressions, backgrounds, lighting settings, "
                "and textures. Focus on key descriptive phrases and tags separated by commas."
            )
        else:  # dall-e
            question = (
                f"{uncensored_directive} Write a clear, narrative prompt to recreate this image, describing the characters, "
                "scenery, lighting style, color palette, and layout."
            )
            
        if detail == "low":
            question += " Keep the description brief, focusing only on the core elements."
        elif detail == "high":
            question += " Be extremely specific, noting fine details, minor background elements, shadows, and subtle style details."
            
        device = model_device
        description = ""
        
        # Lock during inference to prevent concurrent CUDA access conflicts
        with model_lock:
            with torch.no_grad():
                if MODEL_TYPE == "moondream":
                    if device == "cuda":
                        with torch.amp.autocast('cuda'):
                            image_embeds = model.encode_image(pil_image)
                            description = model.answer_question(image_embeds, question, tokenizer)
                    else:
                        image_embeds = model.encode_image(pil_image)
                        description = model.answer_question(image_embeds, question, tokenizer)
                    # Clean up Moondream GPU memory
                    del image_embeds
                else: # LLaVA 1.5 7B
                    prompt = f"USER: <image>\n{question}\nASSISTANT:"
                    inputs = tokenizer(text=prompt, images=pil_image, return_tensors="pt")
                    input_len = inputs["input_ids"].shape[1]
                    
                    gen_kwargs = {
                        "max_new_tokens": 300,
                        "do_sample": False,
                    }
                    
                    if device == "cuda":
                        inputs = {k: v.to("cuda") if hasattr(v, "to") else v for k, v in inputs.items()}
                        with torch.amp.autocast('cuda'):
                            output_ids = model.generate(**inputs, **gen_kwargs)
                    else:
                        output_ids = model.generate(**inputs, **gen_kwargs)
                    
                    generated_tokens = output_ids[0][input_len:]
                    description = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
                    # Clean up LLaVA GPU memory
                    del inputs, output_ids
                
                # Execute garbage collection for active VRAM release
                if device == "cuda":
                    import gc
                    gc.collect()
                    torch.cuda.empty_cache()
            
        description = description.strip()
        
        preset_info = STYLE_PRESETS.get(style, STYLE_PRESETS["none"])
        tags = preset_info["tags"]
        modifiers = preset_info["modifiers"]
        
        positive_prompt = ""
        prompt_tags = []
        negative_prompt = ""
        
        # Target-specific formatting
        if target == "stable-diffusion":
            base_tags = clean_prompt_tags(description)
            if not base_tags:
                base_tags = [description]
                
            style_tags_list = [t.strip() for t in tags.split(",") if t.strip()]
            all_tags = base_tags + style_tags_list
            if modifiers:
                all_tags.append(modifiers)
                
            positive_prompt = ", ".join(all_tags)
            prompt_tags = all_tags
            negative_prompt = NEGATIVE_PROMPTS.get("stable-diffusion", "")
            
        elif target == "midjourney":
            base_tags = clean_prompt_tags(description)
            clean_desc = ", ".join(base_tags)
            
            midjourney_prompt = clean_desc
            if modifiers:
                midjourney_prompt += f", {modifiers}"
            if tags:
                midjourney_prompt += f", in the style of {tags}"
                
            # Clean commas and format negative parameters
            positive_prompt = midjourney_prompt.replace(".", ",")
            positive_prompt = ", ".join([p.strip() for p in positive_prompt.split(",") if p.strip()])
            
            raw_neg = NEGATIVE_PROMPTS.get("midjourney", "")
            neg_words = [w.strip() for w in raw_neg.replace("--no", "").split(",") if w.strip()]
            if neg_words:
                positive_prompt += " --no " + " ".join(neg_words)
                
            prompt_tags = base_tags + [t.strip() for t in tags.split(",") if t.strip()] + ([modifiers] if modifiers else [])
            negative_prompt = "N/A (Appended to positive prompt as --no)"
            
        else:  # DALL-E 3
            # Clean conversational prefixes from description
            clean_desc = description
            prefixes = [
                "this is a photo of", "this is an image of", "a photo of", "an image of",
                "the image displays", "the image shows", "this image shows", "we can see",
                "there is a", "there are", "a description of", "caption:"
            ]
            for prefix in prefixes:
                if clean_desc.lower().startswith(prefix):
                    clean_desc = clean_desc[len(prefix):].strip()
                    clean_desc = clean_desc[0].upper() + clean_desc[1:] if clean_desc else ""
                    break
            
            dalle_prompt = clean_desc
            if style != "none":
                dalle_style_desc = f" The image should be in a {style} style."
                if tags:
                    # Filter out SD buzzwords that DALL-E 3 rejects
                    buzzwords = ["8k resolution", "8k", "photorealistic", "hyperrealistic", "highly detailed", "sharp focus", "dslr", "camera settings", "unreal engine 5 render", "octanerender", "trending on artstation"]
                    clean_style_tags = [t.strip() for t in tags.split(",") if t.strip() and t.strip().lower() not in buzzwords]
                    if clean_style_tags:
                        dalle_style_desc += f" It features artistic elements like {', '.join(clean_style_tags)}."
                if modifiers:
                    buzzwords = ["realistic textures", "artstation trending", "masterpiece"]
                    clean_modifiers = [m.strip() for m in modifiers.split(",") if m.strip() and m.strip().lower() not in buzzwords]
                    if clean_modifiers:
                        dalle_style_desc += f" The rendering should focus on {', '.join(clean_modifiers)}."
                dalle_prompt += dalle_style_desc
                
            positive_prompt = dalle_prompt
            prompt_tags = clean_prompt_tags(tags) + ([modifiers] if modifiers else [])
            negative_prompt = "N/A (DALL-E 3 does not support negative prompts)"

        return JSONResponse(content={
            "status": "success",
            "target": target,
            "style": style,
            "description": description,
            "positive_prompt": positive_prompt,
            "negative_prompt": negative_prompt,
            "tags": prompt_tags
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")

# Mount static files directory (will create UI here)
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    # Start the server on port 8088 with reload=False to prevent recursive model loading GPU crashes
    uvicorn.run("main:app", host="127.0.0.1", port=8088, reload=False)
