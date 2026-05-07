# PQC TLS client: curl linked against OQS-OpenSSL.
#
# We don't drive curl from inside this container's CMD — the panel does
# `docker exec pqreact-cam-pqc-curl curl …` on demand. The container just
# needs to stay alive so exec can find it. `sleep infinity` is the
# canonical pattern.
#
# Inherits everything from openquantumsafe/curl: the curl binary linked
# against OpenSSL 3 + oqs-provider with all the same groups the nginx
# image accepts.

FROM openquantumsafe/curl:latest

# Sanity probe — should print the OpenSSL version with oqs-provider loaded.
RUN curl --version | head -3 && openssl list -providers || true
