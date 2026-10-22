@echo off
rem Start the local GD caching proxy (run before launching Geometry Dash).
rem Then in-game: Geode Mods -> GD Proxy Helper -> set Proxy URL to http://127.0.0.1:8080
python "%~dp0tools\gdproxy.py" --port 8080
pause
