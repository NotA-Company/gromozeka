FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    PATH="/home/sandbox/.local/bin:${PATH}" \
    PYTHONPATH="/sandbox/libs"

# coreutils gives us GNU `timeout` semantics (busybox's also works,
# but coreutils is explicit and supports --kill-after consistently)
RUN apk add --no-cache coreutils \
 && adduser -D -u 1000 sandbox \
 && mkdir -p /workspace /sandbox/libs \
 && chown -R sandbox:sandbox /workspace /sandbox

USER sandbox
WORKDIR /workspace
CMD ["python"]