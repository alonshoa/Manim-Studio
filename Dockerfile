FROM manimcommunity/manim:v0.20.1 AS runtime

USER root

ARG USER_UID=1000
ARG USER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:/manim/.local/bin:/home/manimuser/.local/bin:${PATH}"
ENV MANIM_STUDIO_REPO_ROOT=/workspace

RUN printf '%s\n' \
        'export VIRTUAL_ENV=/opt/venv' \
        'case ":${PATH}:" in' \
        '  *":/opt/venv/bin:"*) ;;' \
        '  *) export PATH="/opt/venv/bin:/manim/.local/bin:/home/manimuser/.local/bin:${PATH}" ;;' \
        'esac' \
    > /etc/profile.d/manim-studio-path.sh

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

RUN groupmod --gid "${USER_GID}" manimuser \
    && usermod --uid "${USER_UID}" --gid "${USER_GID}" manimuser \
    && mkdir -p /workspace /opt/manim-studio \
    && chown -R manimuser:manimuser /workspace /opt/manim-studio /opt/venv /home/manimuser

WORKDIR /opt/manim-studio

COPY --chown=manimuser:manimuser pyproject.toml README.md LICENSE ./
COPY --chown=manimuser:manimuser src ./src

USER manimuser

RUN python -m pip install --no-cache-dir .

WORKDIR /workspace

CMD ["studio", "doctor"]

FROM runtime AS dev

USER root

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        git \
        openssh-client \
        sudo \
    && printf 'manimuser ALL=(ALL) NOPASSWD:ALL\n' > /etc/sudoers.d/manimuser \
    && chmod 0440 /etc/sudoers.d/manimuser \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER manimuser

WORKDIR /workspaces/Manim-Studio
