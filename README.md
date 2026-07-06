# LuminaPrompt - 로컬 비검열 AI 이미지 프롬프트 생성기

LuminaPrompt는 로컬 GPU를 활용하여 민감하거나 자극적인 이미지 묘사에도 검열 가이드라인(Refusal)에 의해 거부당하지 않고, 있는 그대로 분석하여 Midjourney, Stable Diffusion, DALL-E 3 전용 최적의 AI 프롬프트를 작성해주는 Vanilla JS/CSS/FastAPI 기반의 대시보드 웹앱입니다.

이 서비스는 기본적으로 **LLaVA-1.5-7B (4-bit 양자화)** 및 **Moondream2** 로컬 비전 언어 모델(VLM)을 CUDA 가속으로 기동합니다.

---

## 💻 요구 사양 및 환경
- **운영체제**: Windows 10/11
- **하드웨어 사양**: NVIDIA Dedicated GPU (RTX 4060 Ti 16GB 등 VRAM 6GB 이상 권장)
- **런타임**: Python 3.10 ~ 3.11

---

## 🛠️ 최초 환경 설정 및 설치 방법

### 1단계. 가상환경 및 PyTorch CUDA 설치
프로젝트 루트 폴더에 있는 **`setup_env.bat`** 파일을 더블 클릭하여 실행합니다. 
이 배치는 자동으로 다음 작업을 수행합니다:
1. Python 가상환경(`venv`)을 스폰합니다.
2. CUDA 12.1 연산 가속을 지원하는 PyTorch 패키지를 다운로드합니다.
3. `requirements.txt`에 기록된 FastAPI, Transformers 등의 의존성 패키지를 전량 설치합니다.

### 2단계. Windows 캐시 심볼릭 링크 오류 우회 및 모델 가중치 배치
Windows 환경에서는 관리자 권한이나 개발자 모드가 아닐 경우 Hugging Face 캐시용 심볼릭 링크(Symbolic Link) 생성이 막혀 `model-00001-of-00003.safetensors` 누락 크래시가 유발될 수 있습니다. 

이를 해결하기 위해 아래 명령어를 터미널에서 실행하여 프로젝트 내부 폴더에 **직접 가중치 실제 파일 복제본**을 다운로드 및 복사해 넣습니다:

```powershell
# 가상환경 활성화
.\venv\Scripts\activate

# 로컬 models 폴더에 직접 가중치 복사 (이미 다운로드 완료된 캐시가 있다면 디스크 복사로 빠르게 복원됩니다)
hf download llava-hf/llava-1.5-7b-hf --local-dir models/llava-7b
```

---

## 🚀 실행 방법 및 원격 기기 접속

가상환경 및 모델 배치가 완료된 상태에서 **`start_app.bat`** 파일을 더블 클릭하여 실행합니다.
서버가 켜지고 LLaVA 모델이 GPU VRAM에 4-bitNF4 상태로 적재(약 15~20초 소요)된 후, 웹 브라우저에서 아래 주소로 접속해 즉시 서비스를 이용하실 수 있습니다:

👉 **[http://localhost:8088](http://localhost:8088)**

### 📱 동일 와이파이(로컬 네트워크) 내 타 기기(모바일/태블릿 등) 접속
모바일 기기 등으로 동일 와이파이 환경에서 PC에 구동된 LuminaPrompt를 이용하고 싶다면, PC의 로컬 IP(예: `http://192.168.x.x:8088`)로 접속할 수 있습니다. 
- *참고*: 비보안(HTTP) 및 비localhost 환경에서는 브라우저 보안 정책상 표준 클립보드 복사 API(`navigator.clipboard`)가 작동을 거부합니다. LuminaPrompt는 이러한 로컬 네트워크 접속 시에도 정상적으로 복사가 완료되도록 **가상 텍스트 에어리어 기반의 Fallback 복사기**가 내장되어 있어 크래시 없이 안전하게 프롬프트를 복사할 수 있습니다.

---

## 🔧 장애 해결 및 VRAM 메모리 관리 (Troubleshooting)

### 1. "Some modules are dispatched on the CPU or the disk" 로딩 실패 경고가 뜨는 경우
- **원인**: GPU VRAM 여유 공간이 부족하여(약 5.2GB 여유 필요) 모델의 일부를 CPU 메모리로 offload 하려다 4-bitNF4 제한 사양에 걸려 로드가 실패한 현상입니다.
- **해결책**: 백그라운드에 이전에 실행되었던 좀비 Python 프로세스가 남아있거나 다른 GPU 툴(ComfyUI 등)이 메모리를 잡고 있는 상태입니다. 파워쉘 터미널에서 다음 명령어로 백그라운드 포트 점유 프로세스를 일괄 강제종료한 뒤 서버를 재기동합니다.

```powershell
# 8088 포트를 붙들고 있는 좀비 python 프로세스 강제 종료
Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# 또는 백그라운드 python 프로세스 전체 강제 종료
Stop-Process -Name "python" -Force
```

### 2. 연속 복사 및 생성 알림 팝업 오작동
- 화면 우측 하단의 Toast 알림이 여러 번 연속해서 호출되어도, 새로운 알림 타이머가 이전 타이머를 자동으로 `clear`하므로 조기에 팝업이 닫히거나 뭉개지지 않고 안정적으로 노출됩니다.
