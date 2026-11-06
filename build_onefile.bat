@echo off
rem Build ONE self-contained voice_mouse.exe (Python, Vosk, its DLLs and the speech model inside).
rem First time only:   py -m pip install nuitka ordered-set zstandard vosk sounddevice
rem Needs models\vosk-model-small-en-us-0.15 in this folder (run voice_mouse.py once to download it).
if not exist "models\vosk-model-small-en-us-0.15" (
  echo models\vosk-model-small-en-us-0.15 not found - run "py voice_mouse.py" once so it downloads it.
  exit /b 1
)
py -m nuitka ^
  --onefile ^
  --onefile-tempdir-spec="{CACHE_DIR}/voice_mouse" ^
  --enable-plugin=tk-inter ^
  --include-package=vosk ^
  --include-package-data=vosk ^
  --include-package-data=_sounddevice_data ^
  --include-package=sherpa_onnx ^
  --include-package-data=sherpa_onnx ^
  --include-data-dir=models=models ^
  --assume-yes-for-downloads ^
  --windows-console-mode=force ^
  --output-dir=build ^
  voice_mouse.py
if errorlevel 1 (echo Build failed & exit /b 1)
echo.
echo Built: build\voice_mouse.exe  (single file, roughly 100+ MB because it contains the model)
rem The {CACHE_DIR} tempdir spec makes it unpack once and reuse that copy, so later starts are fast.
rem Use --windows-console-mode=disable to hide the console window.
rem Add --windows-uac-admin to make the exe always ask for administrator rights (so it can click admin windows).

rem Dictation (the "dictate" command) is built in: the two sherpa_onnx lines above add it.
rem   They need: py -m pip install sherpa-onnx webrtcvad-wheels numpy   (delete the two sherpa_onnx lines to build without dictation).
rem   Copy the dictation models folder (sherpa-onnx-*) next to the exe too, or the first use downloads about 750 MB.
