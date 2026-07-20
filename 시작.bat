@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

REM 이 파일을 더블클릭하면: 폴더 이동 + 환경 켜기 + 소재 공장 실행까지 자동.
REM cd 나 .venv\Scripts\activate 를 손으로 칠 필요가 없다.
REM (파이썬 설치, 클로드 로그인, .env 넣기는 처음 한 번 미리 해둬야 한다.)

if not exist ".venv\" (
  echo 처음 실행이라 준비를 합니다. 1~2분 걸립니다...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate.bat
)

echo.
python factory.py

echo.
echo 끝났습니다. 이 창은 닫아도 됩니다.
pause
