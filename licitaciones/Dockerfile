# Imagen única del motor de licitaciones (ADR 0008): tres binarios, cada servicio elige el suyo con `command`.
# Contexto de construcción: la carpeta licitaciones/   (docker build -f licitaciones/Dockerfile licitaciones)
# POR VERIFICAR (fase 1): fijar la imagen base por digest (`golang:1.27.3-bookworm@sha256:…`) cuando se consulte el registro.
FROM golang:1.27.3-bookworm AS build
ENV GOTOOLCHAIN=local CGO_ENABLED=0
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VERSION=dev
RUN go build -trimpath -ldflags="-s -w -X github.com/ionindustry/cerebro101/licitaciones/internal/version.Version=${VERSION}" -o /out/ ./cmd/...

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/api /out/ingestor /out/proyector /
USER 65532:65532
ENTRYPOINT ["/api"]
