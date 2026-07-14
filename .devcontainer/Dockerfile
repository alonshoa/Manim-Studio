FROM manimcommunity/manim:v0.20.1

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV PATH="/home/manimuser/.local/bin:${PATH}"

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        bash \
        ca-certificates \
        dvisvgm \
        ffmpeg \
        fontconfig \
        fonts-dejavu \
        fonts-dejavu-core \
        fonts-dejavu-extra \
        fonts-noto \
        fonts-noto-core \
        fonts-noto-extra \
        fonts-noto-ui-core \
        texlive \
        texlive-fonts-recommended \
        texlive-lang-arabic \
        texlive-lang-other \
        texlive-latex-extra \
        texlive-latex-recommended \
        texlive-xetex \
    && fc-cache -f \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
        manim==0.20.1 \
        manim-slides==5.6.0

# Optional GPU/OpenGL support is intentionally not enabled by default. If a
# workstation needs it later, add explicit runArgs for the host GPU stack here.
USER manimuser
