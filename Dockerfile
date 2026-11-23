# Reference image for evs-cadsr-mcp (proposal 10.5, 11). Use an NCI-approved base in production.
# Base images are pinned by digest; refresh with `docker buildx imagetools inspect python:3.12-slim`.
# Dependencies come from deploy/requirements.lock (hash-checked); regenerate with:
#   uv lock && uv export --frozen --no-emit-project --extra redis --format requirements-txt -o deploy/requirements.lock
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS build
WORKDIR /app
COPY deploy/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .

FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
RUN useradd --create-home --uid 10001 ecm
WORKDIR /app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin/evs-cadsr-mcp /usr/local/bin/evs-cadsr-mcp
USER ecm
# The container listens on all interfaces, so the server refuses to start unless ECM_AUTH_MODE=jwt is
# configured (ECM_AUTH_JWKS_URI, ECM_AUTH_ISSUER, ECM_AUTH_AUDIENCE) or ECM_ALLOW_UNAUTHENTICATED=true
# is set deliberately behind a trusted, authenticating gateway.
# map_map_icdo_to_ncit downloads EVS's ICD-O-3.1 mapping files into ~/.cache/evs-cadsr-mcp/icdo
# (needs HTTPS egress to evs.nci.nih.gov). Mount a volume there to keep them across restarts.
ENV ECM_PROFILE=unified ECM_HTTP_HOST=0.0.0.0 ECM_HTTP_PORT=8000 ECM_LOG_JSON=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["evs-cadsr-mcp", "serve", "--transport", "http"]
