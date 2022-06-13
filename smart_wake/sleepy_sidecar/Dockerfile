##
## Build
##
FROM golang:1.18.3-bullseye AS build
RUN useradd -u 10001 sidecaruser
WORKDIR /app
ADD src /app/

RUN go build -o /sidecar
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /sidecar
##
## Deploy
##
FROM scratch

WORKDIR /

COPY --from=build /sidecar /sidecar
COPY --from=0 /etc/passwd /etc/passwd
USER sidecaruser
EXPOSE 10000

ENTRYPOINT ["/sidecar"]
