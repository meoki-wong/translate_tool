@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: 获取项目根目录
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"

echo =====================================
echo   实时音频翻译工具
echo   平台: Windows
echo =====================================
echo.

:: 检查 Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [X] Python 未安装或未加入 PATH
    echo   请安装 Python 3.11+ : https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查 Python 虚拟环境
if not exist "%BACKEND_DIR%\venv" (
    echo [*] Python 虚拟环境不存在，正在创建...
    cd /d "%BACKEND_DIR%"
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
    echo [OK] 虚拟环境创建完成
) else (
    echo [OK] Python 虚拟环境已就绪
)

:: 检查 vosk 模型
set "VOSK_MODEL_DIR=%BACKEND_DIR%\models\vosk-model-small-en-us-0.15"
if not exist "%VOSK_MODEL_DIR%" (
    echo [*] vosk 语音识别模型未下载，正在下载...
    mkdir "%BACKEND_DIR%\models" 2>nul
    cd /d "%BACKEND_DIR%"
    call venv\Scripts\activate.bat
    python -c "import urllib.request, zipfile, os; url='https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'; dest='models/vosk-model-small-en-us-0.15.zip'; print('Downloading ~50MB...'); urllib.request.urlretrieve(url, dest); print('Extracting...'); z=zipfile.ZipFile(dest,'r'); z.extractall('models'); z.close(); os.remove(dest); print('Done!')"
    echo [OK] vosk 模型已就绪
) else (
    echo [OK] vosk 模型已就绪
)

:: 检查前端依赖
if not exist "%FRONTEND_DIR%\node_modules" (
    echo [*] 前端依赖未安装，正在安装...
    cd /d "%FRONTEND_DIR%"
    call npm install
    echo [OK] 前端依赖安装完成
) else (
    echo [OK] 前端依赖已就绪
)

echo.
echo 启动方式选择：
echo   1. 仅启动 Python 后端（调试用）
echo   2. 启动完整应用（Tauri + Python）
echo.
set /p choice="请选择 (1/2): "

if "%choice%"=="1" (
    echo.
    echo 正在启动 Python 后端...
    cd /d "%BACKEND_DIR%"
    call venv\Scripts\activate.bat
    python main.py
) else if "%choice%"=="2" (
    echo.
    echo 正在启动 Tauri 应用...
    cd /d "%FRONTEND_DIR%"
    call npm run tauri dev
) else (
    echo 无效选择
    exit /b 1
)
