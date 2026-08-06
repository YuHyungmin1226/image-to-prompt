# LuminaPrompt - Gemma 4 기반 로컬 이미지 프롬프트 생성기

LuminaPrompt는 업로드한 이미지를 로컬에서 분석해 Midjourney, Stable Diffusion, DALL-E 3용 프롬프트를 생성하는 FastAPI 웹앱입니다.

이 버전은 기존 `transformers + LLaVA` 경로 대신 **`HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced`** 모델을 **`llama-cpp-python`** 으로 구동하도록 변경되었습니다. 이 프로젝트는 텍스트 GGUF만이 아니라 Gemma 4 비전용 `mmproj` 파일도 함께 내려받아 이미지 입력을 처리합니다.

---

## 요구 사항

- Windows 10/11
- Python 3.10 ~ 3.12
- NVIDIA GPU 권장
- NVIDIA CUDA Toolkit 11.8 이상 권장
- Visual Studio 2022 Build Tools 필수
- 디스크 여유 공간 약 9 GB 이상 권장

CPU-only로도 시도할 수는 있지만, 속도는 매우 느릴 수 있습니다.

중요:
- 2026년 7월 19일 기준 `llama-cpp-python 0.3.34`용 Windows `cu118` CUDA wheel을 사용할 수 있습니다.
- 이 프로젝트는 Windows에서 가장 권장되는 GPU 가속 경로로 **CUDA 11.8 wheel 설치**를 우선 사용하고, Visual Studio 2022 Build Tools는 런타임 검증과 비상 수동 빌드 대비용으로 유지합니다.
- `setup_env.bat` 실행 전 Build Tools와 CUDA Toolkit이 먼저 설치되어 있어야 합니다.

---

## 설치

프로젝트 루트에서 **`setup_env.bat`** 를 실행합니다.

이 배치는 다음 작업을 수행합니다.

1. `venv` 가상환경 생성
2. `pip` 업그레이드
3. `requirements.txt` 기반 공통 의존성 설치
4. Visual Studio C++ 빌드 환경 확인
5. CUDA Toolkit 확인
6. `llama-cpp-python` CUDA wheel 설치

사전 설치가 필요한 항목:

- Visual Studio 2022 Build Tools
- `Desktop development with C++` 워크로드
- MSVC v143 toolset
- Windows SDK
- CMake tools
- NVIDIA CUDA Toolkit 11.8 이상

`requirements.txt`에는 공통 의존성만 포함되어 있고, `llama-cpp-python` GPU 런타임은 `setup_env.bat`가 별도로 설치합니다.

모델 본체는 설치 단계가 아니라 **첫 실행 시 자동 다운로드** 됩니다.
다운로드된 모델은 기본적으로 OS의 기본 문서 폴더 아래 **`LLM-Models`** 폴더에 저장됩니다.
첫 실행 시 보통 아래 두 파일이 함께 내려받아집니다.

- `Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf`
- `mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf`

기본 구조 예시:

```text
Documents\LLM-Models\HauhauCS\Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced
```

---

## 실행

가상환경 준비가 끝나면 **`start_app.bat`** 를 실행합니다.
이 런처는 현재 셸에 설정된 `LUMINAPROMPT_HOST`, `LUMINAPROMPT_PORT`, `LUMINAPROMPT_MODELS_DIR` 값을 읽습니다.

실행 직후 터미널에는 다음 정보가 출력됩니다.

- `Local URL`: `http://localhost:8088`
- `Network URL`: 같은 공유기의 다른 기기에서 접속할 주소

서버가 떠 있는 동안 브라우저에서 `http://localhost:8088` 로 접속하면 됩니다.

첫 실행은 모델 다운로드와 초기 로딩 때문에 오래 걸릴 수 있습니다. 이때 모델 파일은 `Documents\LLM-Models` 아래에 저장되고, 이후부터는 그 위치에서 다시 불러와 사용합니다.
기본 문서 폴더가 아닌 다른 위치를 쓰고 싶다면 **첫 실행 전에** `LUMINAPROMPT_MODELS_DIR` 를 먼저 설정한 뒤 `start_app.bat` 를 실행해야 합니다.

---

## 현재 모델

- Hugging Face repo: `HauhauCS/Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced`
- 기본 런타임: `llama-cpp-python`
- 기본 양자화 파일: `Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf`
- 비전 프로젝터 파일: `mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf`
- 기본 로컬 저장 위치: `Documents\LLM-Models\HauhauCS\Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced`

앱 내부 `MODEL_TYPE` 값은 현재 `gemma4-12b-qat-balanced` 입니다.

---

## 환경 변수

필요하면 아래 값으로 런타임을 조정할 수 있습니다.

- `LUMINAPROMPT_HOST`
- `LUMINAPROMPT_PORT`
- `LUMINAPROMPT_CTX`
- `LUMINAPROMPT_THREADS`
- `LUMINAPROMPT_MAX_TOKENS`
- `LUMINAPROMPT_N_GPU_LAYERS`
- `LUMINAPROMPT_MODELS_DIR`
- `LUMINAPROMPT_SYSTEM_PROMPT_FILE`
- `LUMINAPROMPT_SKIP_MODEL_LOAD`
- `LUMINAPROMPT_VERBOSE`

예시:

```powershell
$env:LUMINAPROMPT_HOST = "127.0.0.1"
$env:LUMINAPROMPT_PORT = "8090"
$env:LUMINAPROMPT_MODELS_DIR = "D:\LLM-Models"
$env:LUMINAPROMPT_MAX_TOKENS = "1536"
$env:LUMINAPROMPT_SYSTEM_PROMPT_FILE = "D:\CodeSpace\MasterPrompts\optimized_system_prompt.md"
$env:LUMINAPROMPT_N_GPU_LAYERS = "0"
.\start_app.bat
```

`LUMINAPROMPT_N_GPU_LAYERS=0` 으로 두면 CPU 모드로 강제할 수 있습니다.

`LUMINAPROMPT_MODELS_DIR` 를 지정하면 기본 `Documents\LLM-Models` 대신 원하는 모델 저장 루트를 사용할 수도 있습니다.

---

## 업로드 가드레일

- 비이미지 파일은 `400`
- 20 MB 초과 업로드는 `413`
- 40,000,000 픽셀 초과 이미지는 `413`

이 제한은 메모리 급증과 오작동을 줄이기 위한 것입니다.

---

## 문제 해결

### 포트 8088이 이미 사용 중인 경우

```powershell
Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
}
```

### `llama-cpp-python` 설치가 실패하는 경우

- Python 버전이 3.10~3.12인지 확인합니다.
- Visual Studio 2022 Build Tools와 `Desktop development with C++` 워크로드가 설치되어 있는지 확인합니다.
- `nvcc.exe`가 준비되지 않으면 CUDA wheel 설치 이후 실제 GPU 사용이 불가능합니다.
- CUDA Toolkit 11.8 이상이 설치되어 있는지 확인합니다.
- Gemma 4 비전 입력을 쓰려면 `Gemma4ChatHandler`를 포함한 최신 `llama-cpp-python`이 필요하므로, 오래된 버전이 남아 있지 않도록 다시 설치하는 편이 안전합니다.

### 모델 파일 위치를 확인하고 싶은 경우

- 기본 저장 위치는 `Documents\LLM-Models` 입니다.
- 현재 기본 모델은 보통 `Documents\LLM-Models\HauhauCS\Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced` 아래에 저장됩니다.
- 이미지 분석이 동작하려면 텍스트 GGUF뿐 아니라 `mmproj-Gemma4-12B-QAT-Uncensored-HauhauCS-Balanced-BF16.gguf` 파일도 같은 폴더에 있어야 합니다.
- 다른 위치를 쓰고 싶다면 `LUMINAPROMPT_MODELS_DIR` 환경 변수를 지정합니다.

### 다른 기기에서 접속이 안 되는 경우

- Windows 방화벽에서 Python 또는 해당 포트를 허용합니다.
- 반드시 터미널에 표시된 `Network URL` 로 접속합니다.
