#!/usr/bin/env bash
# Bring up KasmVNC. Web client is served on :6901 over HTTP (no TLS, no auth).
#
# Browser endpoint: http://localhost:6901/
#
# Honors:
#   KIBUILDER_GEOM  geometry override (default: 1600x1000)

set -euo pipefail

GEOM="${KIBUILDER_GEOM:-1600x1000}"

cleanup() {
    vncserver -kill :1 >/dev/null 2>&1 || true
}
trap cleanup EXIT

# KasmVNC 1.4's wrapper interactively prompts for a write-access user on
# first launch — and the prompt loops forever without a TTY. Pre-seed the
# user via kasmvncpasswd so the wrapper finds it and skips the prompt.
# -f read password from stdin, -o owner permissions, -u USER, -w write.
mkdir -p "$HOME/.vnc"
echo -e "kasm\nkasm" | kasmvncpasswd -f -o -u kasm -w >/dev/null 2>&1 || \
    echo -e "kasm\nkasm" | vncpasswd -f -o -u kasm -w >/dev/null 2>&1 || true

echo "[entrypoint] starting KasmVNC on :1 ($GEOM)"
vncserver :1 \
    -geometry "$GEOM" \
    -depth 24 \
    -websocketPort 6901 \
    -interface 0.0.0.0 \
    -httpd /usr/share/kasmvnc/www \
    -sslOnly 0 \
    >/tmp/vnc.log 2>&1 &
VNC_PID=$!

# Wait for the server to come up before declaring success.
for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    if ss -tln 2>/dev/null | grep -q ':6901' \
       || (exec 3<>/dev/tcp/127.0.0.1/6901 && echo) 2>/dev/null; then
        break
    fi
done

echo "[entrypoint] kibuilder running"
echo "[entrypoint] browse to http://localhost:6901/  (user: kasm  password: kasm)"
echo "[entrypoint] (Ctrl-C here to stop the container)"

# Block on the X session; if vncserver dies, drain its log and exit.
wait $VNC_PID 2>/dev/null || true
cat /tmp/vnc.log 2>/dev/null || true
