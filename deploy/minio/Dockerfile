FROM golang:1.24.8-alpine AS build

# The upstream release is source-only; Go verifies downloaded modules with go.sum.
ARG MINIO_VERSION=RELEASE.2025-10-15T17-29-55Z
ENV CGO_ENABLED=0 GOMAXPROCS=2
RUN go install -ldflags="-s -w" github.com/minio/minio@${MINIO_VERSION} \
    && mkdir /licenses \
    && cp /go/pkg/mod/github.com/minio/minio@*/LICENSE /licenses/LICENSE

FROM alpine:3.22
RUN apk add --no-cache ca-certificates curl
COPY --from=build /go/bin/minio /usr/local/bin/minio
COPY --from=build /licenses/LICENSE /usr/share/licenses/minio/LICENSE
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
