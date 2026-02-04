#!/bin/bash
# Helper script to run tests inside Docker container
# Usage: ./run-tests.sh [pytest arguments]

set -e

IMAGE_NAME="github-approvals:test"

# Build the image if it doesn't exist or if Dockerfile changed
echo "🐳 Building Docker image with test dependencies..."
docker build -t $IMAGE_NAME .

# Default pytest arguments if none provided
PYTEST_ARGS="${@:-tests/ -v}"

echo ""
echo "🧪 Running tests inside container..."
echo "   Command: pytest $PYTEST_ARGS"
echo ""

# Run tests inside container
docker run --rm \
  -e ENVIRONMENT=test \
  -e BASE_URL=http://testserver \
  -e GITHUB_TOKEN=test_token_12345 \
  -e EMAIL_ADDRESS=test@example.com \
  -e EMAIL_PASSWORD=test_password \
  -e STAKEHOLDERS_PSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -e STAKEHOLDERS_GSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -e STAKEHOLDERS_ESRL=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -v "$(pwd)":/workspace \
  -w /workspace \
  $IMAGE_NAME \
  pytest $PYTEST_ARGS

echo ""
echo "✅ Tests completed successfully!"
