#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="test.k3rnel-pan1c.com"
REMOTE_PORT=2223
REMOTE_USER="marko"
IMAGE_NAME="ocr"
REMOTE="$REMOTE_USER@$REMOTE_HOST"
SSH_OPTS=(-p "$REMOTE_PORT" -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3)
: "${PUBLIC_URL:?PUBLIC_URL must be set}"
: "${PORT:?PORT must be set}"

# Runtime env vars passed into the remote `docker run` invocation. Each is
# optional — if it's empty in this shell, we still pass it through (the
# server reads them at request time and treats unset = dev mode).
RUNTIME_ENV_VARS=(LLM_BASE_URL LLM_API_KEY LLM_MODEL MISTRAL_OCR_MODEL AUTH_PASSWORD API_KEY OCR_MAX_UPLOAD_MB)
DOCKER_ENV_ARGS=()
for var in "${RUNTIME_ENV_VARS[@]}"; do
  DOCKER_ENV_ARGS+=(-e "${var}=${!var-}")
done

printf "==> building image ($IMAGE_NAME, linux/amd64)..."
./scripts/build.sh linux/amd64 > /dev/null 2>&1
echo "ok"

printf "==> saving image..."
docker save "$IMAGE_NAME" | gzip > /tmp/"${IMAGE_NAME}".tar.gz
echo "ok"

printf "==> uploading to $REMOTE_HOST..."
scp -P "$REMOTE_PORT" -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 /tmp/"${IMAGE_NAME}".tar.gz "$REMOTE":/tmp/"${IMAGE_NAME}".tar.gz
rm /tmp/"${IMAGE_NAME}".tar.gz
echo "ok"

printf "==> loading image on remote..."
ssh "${SSH_OPTS[@]}" "$REMOTE" '
  docker load < /tmp/'"${IMAGE_NAME}"'.tar.gz
  rm /tmp/'"${IMAGE_NAME}"'.tar.gz
' > /dev/null 2>&1
echo "ok"

printf "==> starting container..."
# `printf %q` makes each value safely shell-quotable so we can splice
# them through the heredoc into the remote shell without losing spaces
# or special characters in secrets.
remote_env_args=$(printf '%q ' "${DOCKER_ENV_ARGS[@]}")
ssh "${SSH_OPTS[@]}" "$REMOTE" "
  docker stop ${IMAGE_NAME} 2>/dev/null || true
  docker rm ${IMAGE_NAME} 2>/dev/null || true
  docker run -d \\
    -p ${PORT}:${PORT} \\
    --name ${IMAGE_NAME} \\
    --restart unless-stopped \\
    ${remote_env_args} \\
    ${IMAGE_NAME}
" > /dev/null 2>&1
echo "ok"

printf "==> waiting for server..."
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-120}"
WAIT_INTERVAL_SECONDS="${WAIT_INTERVAL_SECONDS:-2}"
WAIT_DEADLINE=$(( $(date +%s) + WAIT_TIMEOUT_SECONDS ))
server_ready=false

while (( $(date +%s) < WAIT_DEADLINE )); do
  if ssh "${SSH_OPTS[@]}" "$REMOTE" 'curl -sf --max-time 3 http://localhost:'"$PORT"'/health > /dev/null' 2>/dev/null; then
    server_ready=true
    break
  fi
  sleep "$WAIT_INTERVAL_SECONDS"
done

if [[ "$server_ready" != true ]]; then
  echo "FAIL"
  echo "    server did not start within ${WAIT_TIMEOUT_SECONDS}s"
  echo "    remote diagnostics:"
  ssh "${SSH_OPTS[@]}" "$REMOTE" 'docker ps --filter "name='"${IMAGE_NAME}"'" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"; echo; docker logs --tail 50 '"${IMAGE_NAME}"' 2>/dev/null || true' || true
  exit 1
fi
echo "ok"

# /health is auth-bypassed by design — we use it for the smoke check so the
# deploy doesn't need to know AUTH_PASSWORD or API_KEY.
printf "==> checking public endpoint ($PUBLIC_URL/health)..."
if ! body=$(curl -sf --max-time 10 "${PUBLIC_URL%/}/health"); then
  echo "FAIL"
  echo "    could not reach ${PUBLIC_URL%/}/health"
  exit 1
fi

if ! echo "$body" | grep -q '"status": *"ok"'; then
  echo "FAIL"
  echo "    /health did not return status=ok"
  echo "    $body"
  exit 1
fi
echo "ok"

./scripts/get_logs.sh


echo "==> deployed $IMAGE_NAME to $PUBLIC_URL"
