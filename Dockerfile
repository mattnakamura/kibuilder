# kibuilder — containerized GUI via KasmVNC (modern web client).
#
# Why KasmVNC instead of noVNC: a polished Material-style web client that
# resizes with the browser, no separate websockify proxy, no clunky 2010
# chrome. Single server binary.
#
# Build:   docker build -t kibuilder .
# Run:     docker run --rm -p 6901:6901 -v "$PWD:/work" kibuilder
# Browse:  http://localhost:6901/

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    DISPLAY=:1 \
    QT_QPA_PLATFORM=xcb \
    HOME=/home/kb

# ---------- system deps (Python, Qt, X stack) -----------------------------
RUN apt-get update && apt-get install --no-install-recommends -y \
        software-properties-common gnupg ca-certificates curl wget \
        python3.12 python3.12-venv python3-pip python3-dev \
        # Qt6 + OpenGL runtime
        libxcb-cursor0 libxkbcommon0 libxkbcommon-x11-0 \
        libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
        libxcb-render-util0 libxcb-shape0 libxcb-sync1 libxcb-xfixes0 \
        libxcb-xinerama0 libxcb-xkb1 libxcb-render0 libxcb-shm0 \
        libgl1 libglu1-mesa libglx-mesa0 libegl1 \
        libfontconfig1 libdbus-1-3 libx11-xcb1 \
        # Window manager (just enough to give kibuilder window decorations)
        fluxbox xfonts-base \
        # Build extras for any wheels that need compilation
        build-essential pkg-config git \
    && rm -rf /var/lib/apt/lists/*

# ---------- KasmVNC (modern VNC server with built-in web client) ----------
ARG KASMVNC_VERSION=1.4.0
RUN arch=$(dpkg --print-architecture) \
 && wget -q "https://github.com/kasmtech/KasmVNC/releases/download/v${KASMVNC_VERSION}/kasmvncserver_noble_${KASMVNC_VERSION}_${arch}.deb" \
        -O /tmp/kasmvnc.deb \
 && apt-get update \
 && apt-get install --no-install-recommends -y /tmp/kasmvnc.deb \
 && rm /tmp/kasmvnc.deb \
 && rm -rf /var/lib/apt/lists/*

# ---------- KiCad 9 (provides kicad-cli) ----------------------------------
RUN add-apt-repository --yes ppa:kicad/kicad-9.0-releases \
 && apt-get update \
 && apt-get install --no-install-recommends -y kicad \
 && rm -rf /var/lib/apt/lists/*

# ---------- Python deps (system pip — container is already isolated) -----
RUN pip install --no-cache-dir --break-system-packages \
        "Pillow>=10" "PyQt6>=6.5" "numpy>=1.24" "PyYAML>=6" \
        "cadquery-ocp>=7.7"

# ---------- non-root user --------------------------------------------------
RUN userdel -r ubuntu 2>/dev/null || true \
 && useradd -m -u 1000 -s /bin/bash kb \
 && mkdir -p /work && chown kb:kb /work

# ---------- copy + install kibuilder (system pip, as root) ----------------
COPY pyproject.toml README.md /home/kb/kibuilder/
COPY src /home/kb/kibuilder/src
COPY scripts /home/kb/kibuilder/scripts
COPY examples /home/kb/kibuilder/examples
COPY docker/entrypoint.sh /home/kb/entrypoint.sh
COPY docker/kasmvnc.yaml /etc/kasmvnc/kasmvnc.yaml
COPY docker/xstartup /home/kb/.vnc/xstartup
RUN pip install --no-cache-dir --break-system-packages -e /home/kb/kibuilder \
 && chown -R kb:kb /home/kb \
 && chmod +x /home/kb/entrypoint.sh /home/kb/.vnc/xstartup

USER kb
WORKDIR /work
EXPOSE 6901
ENTRYPOINT ["/home/kb/entrypoint.sh"]
