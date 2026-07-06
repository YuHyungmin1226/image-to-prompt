// Global State Variables
let selectedFile = null;
let modelReady = false;
let statusInterval = null;
let toastTimeout = null;

// DOM Elements
const modelStatusCard = document.getElementById('model-status-card');
const modelStatusText = document.getElementById('model-status-text');
const modelStatusTooltip = document.getElementById('model-status-tooltip');

const dropZone = document.getElementById('drop-zone');
const imageInput = document.getElementById('image-input');
const previewContainer = document.getElementById('preview-container');
const imagePreview = document.getElementById('image-preview');
const btnRemoveImage = document.getElementById('btn-remove-image');

const btnGenerate = document.getElementById('btn-generate');

const outputEmpty = document.getElementById('output-empty');
const outputLoading = document.getElementById('output-loading');
const outputResults = document.getElementById('output-results');

const positiveText = document.getElementById('positive-text');
const negativeText = document.getElementById('negative-text');
const tagsContainer = document.getElementById('tags-container');
const descText = document.getElementById('desc-text');

const toast = document.getElementById('toast');

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    // Check local model loading status
    checkModelStatus();
    statusInterval = setInterval(checkModelStatus, 3000);

    // Setup Event Listeners
    setupUploadHandlers();
    setupConfigHandlers();
    setupCopyHandlers();
});

// Check VLM Model Loading Status
async function checkModelStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Update Badge CSS & Text based on API status
        if (data.status === 'ready') {
            modelReady = true;
            modelStatusCard.className = 'status-badge status-ready';
            const modelName = data.model_type === 'llava-7b' ? 'LLaVA 1.5 7B (비검열)' : 'Moondream2 (비검열)';
            modelStatusText.textContent = `${modelName} 준비 완료 (${data.device.toUpperCase()})`;
            modelStatusTooltip.textContent = `${data.message}\n이 모델은 표현 제한 및 세이프티 차단이 해제되어 어떠한 이미지도 여과 없이 묘사합니다.`;
            
            // Enable generate button if file is already selected
            updateGenerateButtonState();
            
            // Stop polling since model is successfully loaded
            clearInterval(statusInterval);
        } else if (data.status === 'error') {
            modelReady = false;
            modelStatusCard.className = 'status-badge status-error';
            modelStatusText.textContent = '모델 로드 실패';
            modelStatusTooltip.textContent = data.message;
            btnGenerate.disabled = true;
            
            clearInterval(statusInterval);
        } else {
            // "loading" state
            modelReady = false;
            modelStatusCard.className = 'status-badge status-loading';
            const modelName = data.model_type === 'llava-7b' ? 'LLaVA 1.5 7B' : 'Moondream2';
            modelStatusText.textContent = `로컬 ${modelName} 초기화 중...`;
            modelStatusTooltip.textContent = data.message;
            btnGenerate.disabled = true;
        }
    } catch (error) {
        console.error("Failed to query status api", error);
        modelStatusCard.className = 'status-badge status-error';
        modelStatusText.textContent = '서버 통신 오류';
        modelStatusTooltip.textContent = 'FastAPI 서버가 꺼져 있거나 연결에 실패했습니다.';
        btnGenerate.disabled = true;
    }
}

// Handle Image Upload UI and Data
function setupUploadHandlers() {
    // Click drop-zone to trigger hidden file selector
    dropZone.addEventListener('click', (e) => {
        // Prevent click trigger if removing preview image
        if (e.target.closest('#btn-remove-image') || e.target.closest('#preview-container')) {
            return;
        }
        imageInput.click();
    });

    // File Selector Change
    imageInput.addEventListener('change', () => {
        if (imageInput.files && imageInput.files[0]) {
            handleFileSelection(imageInput.files[0]);
        }
    });

    // Drag-over styling
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    // File Drop
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');
        
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            const file = e.dataTransfer.files[0];
            // Ensure it is an image file
            if (file.type.startsWith('image/')) {
                handleFileSelection(file);
            } else {
                showToast('이미지 파일만 업로드할 수 있습니다.', true);
            }
        }
    });

    // Remove Image Preview
    btnRemoveImage.addEventListener('click', (e) => {
        e.stopPropagation();
        resetImageSelection();
    });
}

function handleFileSelection(file) {
    selectedFile = file;
    
    // Read file and draw preview
    const reader = new FileReader();
    reader.onload = (e) => {
        imagePreview.src = e.target.result;
        previewContainer.classList.remove('hidden');
    };
    reader.readAsDataURL(file);
    
    updateGenerateButtonState();
}

function resetImageSelection() {
    selectedFile = null;
    imageInput.value = '';
    imagePreview.src = '';
    previewContainer.classList.add('hidden');
    updateGenerateButtonState();
    
    // Reset output panels to empty state
    outputEmpty.classList.remove('hidden');
    outputLoading.classList.add('hidden');
    outputResults.classList.add('hidden');
}

function updateGenerateButtonState() {
    // Generate button is active only when model is fully ready and image is selected
    if (modelReady && selectedFile) {
        btnGenerate.disabled = false;
    } else {
        btnGenerate.disabled = true;
    }
}

// Config Panel & Generation trigger
function setupConfigHandlers() {
    btnGenerate.addEventListener('click', async () => {
        if (!selectedFile || !modelReady) return;

        // Get current configurations
        const targetValue = document.querySelector('input[name="target"]:checked').value;
        const styleValue = document.querySelector('input[name="style"]:checked').value;
        const detailValue = document.querySelector('input[name="detail"]:checked').value;

        // Toggle UI states to loading
        outputEmpty.classList.add('hidden');
        outputResults.classList.add('hidden');
        outputLoading.classList.remove('hidden');
        btnGenerate.disabled = true;

        // Prepare FormData
        const formData = new FormData();
        formData.append('image', selectedFile);
        formData.append('target', targetValue);
        formData.append('style', styleValue);
        formData.append('detail', detailValue);

        try {
            const response = await fetch('/api/generate-prompt', {
                method: 'POST',
                body: formData
            });

            let errorMessage = 'Inference failed';
            if (!response.ok) {
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorMessage;
                } catch (jsonErr) {
                    try {
                        errorMessage = await response.text();
                    } catch (textErr) {
                        errorMessage = `HTTP error ${response.status}: ${response.statusText}`;
                    }
                }
                throw new Error(errorMessage);
            }

            const data = await response.json();
            displayResults(data);
            
        } catch (error) {
            console.error('Error generating prompt:', error);
            showToast(`프롬프트 생성 실패: ${error.message}`, true);
            
            // Fallback UI to Empty state
            outputLoading.classList.add('hidden');
            outputEmpty.classList.remove('hidden');
        } finally {
            btnGenerate.disabled = false;
        }
    });
}

// Render VLM output values into UI Cards
function displayResults(data) {
    // Hide loader, show results
    outputLoading.classList.add('hidden');
    outputResults.classList.remove('hidden');

    // Fill in text
    positiveText.textContent = data.positive_prompt || 'No prompt generated.';
    negativeText.textContent = data.negative_prompt || 'N/A';
    descText.textContent = data.description || 'N/A';

    // Build tags dynamically
    tagsContainer.innerHTML = '';
    if (data.tags && data.tags.length > 0) {
        data.tags.forEach(tag => {
            if (tag.trim().length > 0) {
                const badge = document.createElement('span');
                badge.className = 'prompt-tag-badge';
                badge.textContent = tag;
                tagsContainer.appendChild(badge);
            }
        });
    } else {
        tagsContainer.innerHTML = '<span class="sub-text">태그가 추출되지 않았습니다.</span>';
    }
}

// Copy prompt actions
function setupCopyHandlers() {
    const copyButtons = document.querySelectorAll('.btn-copy');
    copyButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const targetElement = document.getElementById(targetId);
            
            if (targetElement && targetElement.textContent) {
                copyTextToClipboard(targetElement.textContent)
                    .then(() => {
                        showToast('클립보드에 프롬프트가 복사되었습니다!');
                    })
                    .catch(err => {
                        console.error('Failed to copy text: ', err);
                        showToast('복사에 실패했습니다.', true);
                    });
            }
        });
    });
}

function copyTextToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
    } else {
        // Fallback method for insecure contexts (HTTP connection via local IP)
        return new Promise((resolve, reject) => {
            try {
                const textArea = document.createElement("textarea");
                textArea.value = text;
                textArea.style.position = "fixed";
                textArea.style.top = "0";
                textArea.style.left = "0";
                textArea.style.opacity = "0";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                const successful = document.execCommand('copy');
                document.body.removeChild(textArea);
                if (successful) {
                    resolve();
                } else {
                    reject(new Error('Fallback copy command failed'));
                }
            } catch (err) {
                reject(err);
            }
        });
    }
}

// Toast alerts helper
function showToast(message, isError = false) {
    // Select Icon & Color based on error
    const icon = toast.querySelector('i');
    const label = toast.querySelector('span');
    
    label.textContent = message;
    
    if (isError) {
        toast.style.background = 'rgba(239, 68, 68, 0.9)';
        toast.style.boxShadow = '0 10px 25px rgba(239, 68, 68, 0.3)';
        icon.setAttribute('data-lucide', 'alert-circle');
    } else {
        toast.style.background = 'rgba(16, 185, 129, 0.9)';
        toast.style.boxShadow = '0 10px 25px rgba(16, 185, 129, 0.3)';
        icon.setAttribute('data-lucide', 'check-circle-2');
    }
    
    // Refresh Lucide Icons inside toast
    lucide.createIcons();
    
    // Toggle hidden status
    if (toastTimeout) {
        clearTimeout(toastTimeout);
    }
    toast.classList.remove('hidden');
    
    toastTimeout = setTimeout(() => {
        toast.classList.add('hidden');
    }, 2500);
}
