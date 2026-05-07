# PQC TLS server: nginx linked against OQS-OpenSSL.
#
# Pulled from openquantumsafe/oqs-demos/nginx (OQS's reference image). The
# upstream image already ships:
#   - nginx 1.x built against OpenSSL 3 + oqs-provider
#   - all PQC groups enabled by default
#   - a self-signed cert for `localhost`
#
# We override the conf to (a) listen on :4433, (b) accept POST with up to
# 10 MB body so the panel's payload knob is honoured, (c) log every
# request in a format we can grep from Grafana later.

FROM openquantumsafe/nginx:latest

COPY nginx.conf /opt/nginx/nginx-conf/nginx.conf

# Listener port — must match docker-compose.yml.
EXPOSE 4433

# Inherits the upstream entrypoint which starts nginx in the foreground.
