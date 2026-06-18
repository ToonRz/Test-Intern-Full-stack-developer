#!/bin/bash
# Generate self-signed TLS certificates for local development.
# For production, use Let's Encrypt or a proper CA.
#
# Usage:
#   CERT_DIR=/path bash scripts/generate-certs.sh [CERT_DIR]
#
# Skips generation if server.crt + server.key already exist.
set -euo pipefail

CERT_DIR="${1:-${CERT_DIR:-./nginx/certs}}"
mkdir -p "$CERT_DIR"

if [[ -f "$CERT_DIR/server.crt" && -f "$CERT_DIR/server.key" ]]; then
    echo "Certificates already exist in $CERT_DIR — skipping."
    exit 0
fi

DOMAIN="${DOMAIN:-localhost}"
DAYS="${DAYS:-365}"

echo "Generating self-signed certificate for $DOMAIN in $CERT_DIR..."

openssl req -x509 -nodes -days "$DAYS" -newkey rsa:2048 \
    -keyout "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" \
    -subj "/C=US/ST=State/L=City/O=Organization/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:*.$DOMAIN,IP:127.0.0.1"

chmod 600 "$CERT_DIR/server.key"
chmod 644 "$CERT_DIR/server.crt"

echo "Certificates generated:"
echo "   Certificate: $CERT_DIR/server.crt"
echo "   Private Key: $CERT_DIR/server.key"
echo "   Valid for: $DAYS days"
