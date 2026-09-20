@echo off
rem novelcomic 一键启动：后端 FastAPI(8765) + 前端 Vite(5173)
rem 后端用 backend\.venv 里的虚拟环境；前端 npm run dev
setlocal
set ROOT=%~dp0

echo [1/2] 启动后端 FastAPI :8765 ...
start "novelcomic-backend" /D "%ROOT%backend" ".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8765

echo [2/2] 启动前端 Vite :5173 ...
start "novelcomic-frontend" /D "%ROOT%frontend" cmd /c "npm run dev"

echo.
echo 完成。画布直达：
echo http://localhost:5173/tapflow/window?slug=project-trailer-canvas%%40project-26%%40project-trailer^&variant=production^&subject_kind=project^&subject_id=26^&subject_name=project26^&project_id=26
echo.
echo 探针：http://127.0.0.1:8765/api/projects?limit=1
pause
