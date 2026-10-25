@echo off
rem Tamper demo for the video: verify real data (PASS), tamper one field, verify again (FAIL).
rem Run from the repo root in the activated kilntrace env:   verifier\demo.bat
cls
echo.
echo === 1. Verify the published evidence against the blockchain ===
echo ^> python verifier/verify.py --run kasur-2026-02 --index 0
echo.
python verifier/verify.py --run kasur-2026-02 --index 0
echo.
pause >nul
echo === 2. Tamper: change one kiln's type in a copy of the data ===
echo ^> python verifier/make_tampered.py --run kasur-2026-02 --index 0
echo.
python verifier/make_tampered.py --run kasur-2026-02 --index 0
echo.
pause >nul
echo === 3. Verify the tampered copy ===
echo ^> python verifier/verify.py --run kasur-2026-02 --index 0 --manifest data/runs/kasur-2026-02/manifest_tampered.json
echo.
python verifier/verify.py --run kasur-2026-02 --index 0 --manifest data/runs/kasur-2026-02/manifest_tampered.json
echo.
