FROM python:3.12-slim-trixie

LABEL org.opencontainers.image.title="CapOpt OOPSLA 2026 artifact"
LABEL org.opencontainers.image.source="https://github.com/oopslacapopt/oopsla26ae"
LABEL org.opencontainers.image.licenses="Unlicense AND MIT"

ENV DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/capopt-venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/artifact/artifact/lib:/artifact/artifact/source:/artifact/artifact/source/superoptimization \
    PATH=/opt/capopt-venv/bin:/artifact/bin:${PATH}

COPY requirements.lock /tmp/requirements.lock
RUN /usr/local/bin/python3 -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/python" -m pip install --no-cache-dir \
        -r /tmp/requirements.lock \
    && "$VIRTUAL_ENV/bin/python" -m ipykernel install \
        --prefix="$VIRTUAL_ENV" \
        --name=capopt-ae \
        --display-name="CapOpt AE (Python 3.12)"

WORKDIR /artifact
COPY . /artifact

RUN mkdir -p /artifact/ae-output \
    && chmod a-w /artifact/notebook/oopsla26-ae.ipynb \
    && "$VIRTUAL_ENV/bin/python" /artifact/ae/closure_check.py --root /artifact

EXPOSE 8888
CMD ["/opt/capopt-venv/bin/python3", "ae/runner.py", "kick-the-tires"]
