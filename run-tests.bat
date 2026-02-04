@echo off
REM Helper script to run tests inside Docker container (Windows)
REM Usage: run-tests.bat [pytest arguments]

set IMAGE_NAME=github-approvals:test

echo 🐳 Building Docker image with test dependencies...
docker build -t %IMAGE_NAME% .

if "%~1"=="" (
    set PYTEST_ARGS=tests/ -v
) else (
    set PYTEST_ARGS=%*
)

echo.
echo 🧪 Running tests inside container...
echo    Command: pytest %PYTEST_ARGS%
echo.

REM Run tests inside container
docker run --rm ^
  -e ENVIRONMENT=test ^
  -e BASE_URL=http://testserver ^
  -e GITHUB_TOKEN=test_token_12345 ^
  -e EMAIL_ADDRESS=test@example.com ^
  -e EMAIL_PASSWORD=test_password ^
  -e STAKEHOLDERS_PSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov ^
  -e STAKEHOLDERS_GSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov ^
  -e STAKEHOLDERS_ESRL=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov ^
  -v "%cd%":/workspace ^
  -w /workspace ^
  %IMAGE_NAME% ^
  pytest %PYTEST_ARGS%

if %errorlevel% equ 0 (
    echo.
    echo ✅ Tests completed successfully!
) else (
    echo.
    echo ❌ Tests failed!
    exit /b %errorlevel%
)
