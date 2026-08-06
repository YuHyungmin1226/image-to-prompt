import base64
import io
import os
import socket
import threading
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

# Global variables for model state
model = None
model_status = "loading"  # loading, ready, error
model_status_message = "Model initialization started..."
model_device = "none"  # "cuda", "cpu", or "none"
model_lock = threading.Lock()
model_start_lock = threading.Lock()
model_loader_started = False

SERVER_HOST = os.getenv("LUMINAPROMPT_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("LUMINAPROMPT_PORT", "8088"))
SKIP_MODEL_LOAD = os.getenv("LUMINAPROMPT_SKIP_MODEL_LOAD", "").strip().lower() in {"1", "true", "yes", "on"}

MODEL_TYPE = "gemma4-12b-qat-balanced"
MODEL_REPO_ID = "HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced"
MODEL_FILENAME = "Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf"
MODEL_MMPROJ_FILENAME = "mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf"
MODEL_CONTEXT_LENGTH = int(os.getenv("LUMINAPROMPT_CTX", "4096"))
MODEL_THREADS = int(os.getenv("LUMINAPROMPT_THREADS", str(max(1, (os.cpu_count() or 4) - 1))))
MODEL_GPU_LAYERS = int(os.getenv("LUMINAPROMPT_N_GPU_LAYERS", "-1"))
MODEL_VERBOSE = os.getenv("LUMINAPROMPT_VERBOSE", "").strip().lower() in {"1", "true", "yes", "on"}
MODEL_MAX_TOKENS = int(os.getenv("LUMINAPROMPT_MAX_TOKENS", "1024"))
SYSTEM_PROMPT_FILE = os.getenv("LUMINAPROMPT_SYSTEM_PROMPT_FILE", "").strip()

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000


@asynccontextmanager
async def lifespan(_app):
    start_model_loading()
    yield


app = FastAPI(title="Image to Prompt Generator", lifespan=lifespan)


def get_default_documents_dir() -> Path:
    """Resolve the OS default Documents folder, honoring Windows user folder relocation."""
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as registry_key:
                documents_dir, _ = winreg.QueryValueEx(registry_key, "Personal")
                return Path(os.path.expandvars(documents_dir)).expanduser()
        except OSError:
            pass

    return Path.home().expanduser() / "Documents"


MODEL_STORAGE_ROOT = Path(
    os.getenv("LUMINAPROMPT_MODELS_DIR", str(get_default_documents_dir() / "LLM-Models"))
).expanduser()
MODEL_LOCAL_DIR = MODEL_STORAGE_ROOT.joinpath(*MODEL_REPO_ID.split("/"))


def get_lan_ip_candidates() -> list[str]:
    """Collect likely LAN IPv4 addresses for friendly startup logs."""
    candidates = []
    seen = set()

    def remember(ip_address: str):
        if not ip_address or ip_address.startswith("127."):
            return
        if ip_address not in seen:
            seen.add(ip_address)
            candidates.append(ip_address)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            remember(probe.getsockname()[0])
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            remember(info[4][0])
    except socket.gaierror:
        pass

    return candidates


def build_access_urls(host: str, port: int) -> list[str]:
    urls = []
    seen = set()

    def add_url(url: str):
        if url not in seen:
            seen.add(url)
            urls.append(url)

    if host in {"127.0.0.1", "localhost"}:
        add_url(f"http://127.0.0.1:{port}")
        add_url(f"http://localhost:{port}")
        return urls

    add_url(f"http://127.0.0.1:{port}")
    add_url(f"http://localhost:{port}")

    if host not in {"0.0.0.0", "::"}:
        add_url(f"http://{host}:{port}")
        return urls

    for ip_address in get_lan_ip_candidates():
        add_url(f"http://{ip_address}:{port}")

    return urls


def print_startup_urls(host: str, port: int):
    print("[INFO] LuminaPrompt server starting...")
    print(f"[INFO] Model storage directory: {MODEL_LOCAL_DIR}")
    for url in build_access_urls(host, port):
        print(f"[INFO] Access URL: {url}")
    if host in {"0.0.0.0", "::"}:
        print("[INFO] If another device cannot connect, allow Python through Windows Firewall on this network.")


def preferred_device_label() -> str:
    return "cpu" if MODEL_GPU_LAYERS == 0 else "cuda"


def detect_llama_backend(llama_module) -> tuple[str, bool]:
    """Best-effort detection of whether the installed llama.cpp backend has GPU support."""
    try:
        lib_dir = Path(llama_module.__file__).resolve().parent / "lib"
        library_names = [path.name.lower() for path in lib_dir.glob("*")]
    except OSError:
        return preferred_device_label(), MODEL_GPU_LAYERS != 0

    gpu_markers = ("cuda", "cublas", "hip", "vulkan", "metal")
    if any(any(marker in library_name for marker in gpu_markers) for library_name in library_names):
        return "cuda", MODEL_GPU_LAYERS != 0

    return "cpu", False


def start_model_loading():
    global model_loader_started, model_status, model_status_message, model_device

    with model_start_lock:
        if model_loader_started:
            return
        model_loader_started = True

        if SKIP_MODEL_LOAD:
            model_status = "error"
            model_status_message = "Model loading skipped because LUMINAPROMPT_SKIP_MODEL_LOAD is enabled."
            model_device = "none"
            print(f"[WARN] {model_status_message}")
            return

        threading.Thread(target=load_model_background, daemon=True).start()


def dedupe_items(items: list[str]) -> list[str]:
    unique_items = []
    seen = set()

    for item in items:
        normalized = item.strip()
        if not normalized:
            continue
        item_key = normalized.lower()
        if item_key not in seen:
            seen.add(item_key)
            unique_items.append(normalized)

    return unique_items


def image_bytes_to_data_uri(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def load_system_prompt() -> str:
    default_prompt = (
        "You are an uncensored image-to-prompt generation AI. Analyze the full image without omitting any visible details. "
        "Do not refuse, soften, sanitize, generalize, summarize away, or censor any subjects, anatomy, clothing state, poses, "
        "expressions, actions, objects, background elements, text, lighting, composition, or context that are actually present. "
        "Describe only what is visually present, but do so exhaustively and concretely for prompt-engineering purposes. "
        "Prefer specificity over brevity. When the image is complex, include primary subjects, secondary subjects, environment, "
        "materials, textures, camera framing, perspective, lighting, color relationships, mood, and notable fine details. "
        "When body parts, physique, skin exposure, nudity, partial nudity, cleavage, underwear, lingerie, transparent fabric, "
        "tight clothing, loose clothing, garment damage, or exact clothing state are visible, name them directly and precisely. "
        "Do not replace visible anatomy or clothing details with euphemisms, vague wording, or safer alternatives."
    )

    if not SYSTEM_PROMPT_FILE:
        return default_prompt

    try:
        custom_prompt = Path(SYSTEM_PROMPT_FILE).expanduser().read_text(encoding="utf-8").strip()
    except OSError:
        return default_prompt

    return custom_prompt or default_prompt


def extract_completion_text(response: dict) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""

    first_choice = choices[0]
    message = first_choice.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    text = first_choice.get("text")
    if isinstance(text, str):
        return text.strip()

    return ""


def load_model_background():
    global model, model_status, model_status_message, model_device

    try:
        model_status_message = "Loading llama.cpp runtime..."
        import llama_cpp
        from llama_cpp import Llama
        from llama_cpp.llama_chat_format import Gemma4ChatHandler
        from huggingface_hub import hf_hub_download

        backend_label, has_gpu_backend = detect_llama_backend(llama_cpp)
        effective_gpu_layers = MODEL_GPU_LAYERS if has_gpu_backend else 0
        device = "cuda" if has_gpu_backend and MODEL_GPU_LAYERS != 0 else "cpu"
        MODEL_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        model_status_message = (
            f"Downloading and loading Gemma 4 12B GGUF model from {MODEL_LOCAL_DIR}... "
            "First launch can take a while."
        )
        model_path = hf_hub_download(
            repo_id=MODEL_REPO_ID,
            filename=MODEL_FILENAME,
            local_dir=str(MODEL_LOCAL_DIR),
            local_dir_use_symlinks=False,
        )
        mmproj_path = hf_hub_download(
            repo_id=MODEL_REPO_ID,
            filename=MODEL_MMPROJ_FILENAME,
            local_dir=str(MODEL_LOCAL_DIR),
            local_dir_use_symlinks=False,
        )

        chat_handler = Gemma4ChatHandler(clip_model_path=mmproj_path)
        loaded_model = Llama(
            model_path=model_path,
            chat_handler=chat_handler,
            n_ctx=MODEL_CONTEXT_LENGTH,
            n_threads=MODEL_THREADS,
            n_gpu_layers=effective_gpu_layers,
            n_batch=512,
            verbose=MODEL_VERBOSE,
        )

        with model_lock:
            model = loaded_model
            model_status = "ready"
            model_status_message = (
                f"Model ({MODEL_TYPE}) loaded successfully via llama.cpp on {device.upper()} "
                f"(backend: {backend_label.upper()}) "
                f"from {MODEL_LOCAL_DIR}."
            )
            model_device = device
            print(f"[INFO] {model_status_message}")

    except ImportError:
        with model_lock:
            model_status = "error"
            model_status_message = (
                "llama-cpp-python is not installed. Run setup_env.bat again to install the "
                "Gemma 4 GGUF runtime."
            )
            model_device = "none"
            print(f"[ERROR] {model_status_message}")
    except Exception as e:
        with model_lock:
            error_message = str(e)
            if any(keyword in error_message.lower() for keyword in ("mmproj", "chat format", "image_url", "multimodal")):
                error_message += " Try reinstalling the latest llama-cpp-python CUDA wheel from setup_env.bat."
            model_status = "error"
            model_status_message = f"Failed to load model: {error_message}"
            model_device = "none"
            print(f"[ERROR] {model_status_message}")


STYLE_PRESETS = {
    "realistic": {
        "tags": "photorealistic, hyperrealistic, raw photo, film grain, 8k resolution, highly detailed, sharp focus, dslr, camera settings",
        "modifiers": "realistic textures, natural lighting, professional photography, depth of field",
    },
    "anime": {
        "tags": "anime style, digital illustration, vibrant colors, clean lines, anime aesthetic, stylized, cel shading",
        "modifiers": "masterpiece, highly detailed illustration, studio ghibli inspired, makoto shinkai aesthetic",
    },
    "fantasy": {
        "tags": "fantasy art, mystical, ethereal, magical realism, epic composition, unreal engine 5 render",
        "modifiers": "concept art, highly detailed, dramatic volumetric lighting, glow effects, cinematic style",
    },
    "sci-fi": {
        "tags": "cyberpunk, futuristic, sci-fi landscape, neon glow, high-tech, mechanical details",
        "modifiers": "concept design, industrial aesthetic, octanerender, blade runner style, synthetic vibes",
    },
    "oil-painting": {
        "tags": "oil painting, textured canvas, visible brush strokes, fine art style, classical aesthetic, rich colors",
        "modifiers": "artstation trending, van gogh inspired, renaissance atmosphere, expressive texture",
    },
    "concept-art": {
        "tags": "concept art, painterly style, digital painting, speedpaint, moody atmosphere, cinematic color grading",
        "modifiers": "highly detailed, trending on artstation, masterpiece, dramatic storytelling",
    },
    "none": {
        "tags": "",
        "modifiers": "",
    },
}

NEGATIVE_PROMPTS = {
    "stable-diffusion": "ugly, deformed, noisy, blurry, low contrast, bad anatomy, bad proportions, duplicate, extra limbs, low quality, draft, cartoon, anime (unless specified), monochrome, text, watermark, signature",
    "midjourney": "--no ugly, deformed, blurry, low resolution, bad anatomy, text, watermark, signature",
    "dall-e": "avoid text, blurry textures, deformed hands, extra fingers, poor proportions, watermarks",
}


@app.get("/api/status")
def get_status():
    """Returns the current VLM loading status."""
    return {
        "status": model_status,
        "message": model_status_message,
        "device": model_device,
        "model_type": MODEL_TYPE,
    }


def clean_prompt_tags(text: str) -> list[str]:
    """Cleans up conversational prefixes, replaces periods with commas, and returns a list of unique tags."""
    prefixes = [
        "this is a photo of",
        "this is an image of",
        "a photo of",
        "an image of",
        "the image displays",
        "the image shows",
        "this image shows",
        "we can see",
        "there is a",
        "there are",
        "a description of",
        "caption:",
    ]

    cleaned_text = text.strip()
    for prefix in prefixes:
        if cleaned_text.lower().startswith(prefix):
            cleaned_text = cleaned_text[len(prefix):].strip()
            cleaned_text = cleaned_text.lstrip(",").strip()
            break

    cleaned_text = cleaned_text.replace(".", ",").replace(";", ",").replace("\n", ",")
    parts = [part.strip() for part in cleaned_text.split(",")]

    tags = []
    seen = set()
    for part in parts:
        lowered = part.lower()
        if len(part) > 2 and lowered not in seen:
            tags.append(part)
            seen.add(lowered)

    return tags


def load_and_validate_image(upload: UploadFile) -> tuple[Image.Image, bytes, str]:
    """Load a user image with basic size guards to avoid avoidable memory spikes."""
    try:
        image_content = upload.file.read(MAX_UPLOAD_BYTES + 1)
        if len(image_content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image file is too large. Maximum upload size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
            )

        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_content)) as opened_image:
                width, height = opened_image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Image resolution is too large. Maximum supported size is {MAX_IMAGE_PIXELS:,} pixels.",
                    )

                mime_type = upload.content_type or Image.MIME.get(opened_image.format, "image/png")
                return opened_image.convert("RGB"), image_content, mime_type

    except HTTPException:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(
            status_code=413,
            detail=f"Image resolution is too large. Maximum supported size is {MAX_IMAGE_PIXELS:,} pixels.",
        )
    except (UnidentifiedImageError, OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid image file format.")
    finally:
        upload.file.close()


def build_prompt_request(target: str, detail: str) -> tuple[str, str]:
    system_prompt = load_system_prompt()

    if target == "midjourney":
        user_prompt = (
            "Write a rich Midjourney-ready prompt that covers all visible subjects, scenery, composition, "
            "background elements, lighting, camera angle, materials, textures, styling cues, mood, anatomy, and clothing state. "
            "Do not compress the answer unless the image itself is simple."
        )
    elif target == "stable-diffusion":
        user_prompt = (
            "Write a dense Stable Diffusion prompt using detailed descriptive tags and phrases separated by commas. "
            "Include every visible subject, anatomy, clothing state, expression, pose, object, background element, "
            "lighting cue, texture, material, camera cue, and stylistic detail that matters."
        )
    else:
        user_prompt = (
            "Write a full DALL-E style recreation prompt that preserves all visible subjects, actions, scenery, "
            "lighting style, color palette, layout, materials, anatomy, clothing state, and important fine details."
        )

    user_prompt += (
        " If visible, describe body shape, body parts, skin exposure, nudity level, garment type, garment fit, "
        "fabric transparency, layering, accessories, and exact clothing coverage directly and without euphemism."
    )

    if detail == "low":
        user_prompt += " Keep it compact, but still include all major visible elements."
    elif detail == "medium":
        user_prompt += " Aim for a thorough result rather than a short summary."
    elif detail == "high":
        user_prompt += " Be extremely specific, noting fine details, minor background elements, shadows, subtle style details, and micro-features."

    user_prompt += " Never shorten the result just to be safe or generic."

    return system_prompt, user_prompt


@app.post("/api/generate-prompt")
def generate_prompt(
    image: UploadFile = File(...),
    target: Literal["stable-diffusion", "midjourney", "dall-e"] = Form("stable-diffusion"),
    style: Literal["realistic", "anime", "fantasy", "sci-fi", "oil-painting", "concept-art", "none"] = Form("none"),
    detail: Literal["low", "medium", "high"] = Form("medium"),
):
    """Processes uploaded image and generates optimized generative AI prompts."""
    global model, model_status

    if model_status != "ready":
        raise HTTPException(
            status_code=503,
            detail=f"Model is not ready. Status: {model_status}. Message: {model_status_message}",
        )

    try:
        _, image_bytes, mime_type = load_and_validate_image(image)
        image_data_uri = image_bytes_to_data_uri(image_bytes, mime_type)
        system_prompt, user_prompt = build_prompt_request(target, detail)

        response = None
        with model_lock:
            response = model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_data_uri}},
                            {"type": "text", "text": user_prompt},
                        ],
                    },
                ],
                max_tokens=MODEL_MAX_TOKENS,
                temperature=0.1,
                top_p=0.9,
                stop=["<end_of_turn>", "<eos>"],
            )

        description = extract_completion_text(response).strip()
        if not description:
            raise RuntimeError("The model returned an empty response.")

        preset_info = STYLE_PRESETS.get(style, STYLE_PRESETS["none"])
        tags = preset_info["tags"]
        modifiers = preset_info["modifiers"]

        positive_prompt = ""
        prompt_tags = []
        negative_prompt = ""

        if target == "stable-diffusion":
            base_tags = clean_prompt_tags(description)
            if not base_tags:
                base_tags = [description]

            style_tags_list = [tag.strip() for tag in tags.split(",") if tag.strip()]
            all_tags = base_tags + style_tags_list
            if modifiers:
                all_tags.append(modifiers)
            all_tags = dedupe_items(all_tags)

            positive_prompt = ", ".join(all_tags)
            prompt_tags = all_tags
            negative_prompt = NEGATIVE_PROMPTS.get("stable-diffusion", "")

        elif target == "midjourney":
            base_tags = clean_prompt_tags(description)
            clean_desc = ", ".join(dedupe_items(base_tags))

            midjourney_prompt = clean_desc
            if modifiers:
                midjourney_prompt += f", {modifiers}"
            if tags:
                midjourney_prompt += f", in the style of {tags}"

            positive_prompt = midjourney_prompt.replace(".", ",")
            positive_prompt = ", ".join([part.strip() for part in positive_prompt.split(",") if part.strip()])

            raw_neg = NEGATIVE_PROMPTS.get("midjourney", "")
            neg_words = [word.strip() for word in raw_neg.replace("--no", "").split(",") if word.strip()]
            if neg_words:
                positive_prompt += " --no " + " ".join(neg_words)

            prompt_tags = dedupe_items(base_tags + [tag.strip() for tag in tags.split(",") if tag.strip()] + ([modifiers] if modifiers else []))
            negative_prompt = "N/A (Appended to positive prompt as --no)"

        else:
            clean_desc = description
            prefixes = [
                "this is a photo of",
                "this is an image of",
                "a photo of",
                "an image of",
                "the image displays",
                "the image shows",
                "this image shows",
                "we can see",
                "there is a",
                "there are",
                "a description of",
                "caption:",
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
                    buzzwords = [
                        "8k resolution",
                        "8k",
                        "photorealistic",
                        "hyperrealistic",
                        "highly detailed",
                        "sharp focus",
                        "dslr",
                        "camera settings",
                        "unreal engine 5 render",
                        "octanerender",
                        "trending on artstation",
                    ]
                    clean_style_tags = [tag.strip() for tag in tags.split(",") if tag.strip() and tag.strip().lower() not in buzzwords]
                    if clean_style_tags:
                        dalle_style_desc += f" It features artistic elements like {', '.join(clean_style_tags)}."
                if modifiers:
                    buzzwords = ["realistic textures", "artstation trending", "masterpiece"]
                    clean_modifiers = [modifier.strip() for modifier in modifiers.split(",") if modifier.strip() and modifier.strip().lower() not in buzzwords]
                    if clean_modifiers:
                        dalle_style_desc += f" The rendering should focus on {', '.join(clean_modifiers)}."
                dalle_prompt += dalle_style_desc

            positive_prompt = dalle_prompt
            prompt_tags = dedupe_items(clean_prompt_tags(tags) + ([modifiers] if modifiers else []))
            negative_prompt = "N/A (DALL-E 3 does not support negative prompts)"

        return JSONResponse(
            content={
                "status": "success",
                "target": target,
                "style": style,
                "description": description,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "tags": prompt_tags,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    print_startup_urls(SERVER_HOST, SERVER_PORT)
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT, reload=False)
