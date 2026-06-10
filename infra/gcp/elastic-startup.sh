#!/usr/bin/env bash
set -euo pipefail

apt-get update
apt-get install -y ca-certificates curl docker.io
systemctl enable --now docker

sysctl -w vm.max_map_count=262144
echo 'vm.max_map_count=262144' > /etc/sysctl.d/99-elasticsearch.conf

PASSWORD="$(curl -sf -H 'Metadata-Flavor: Google' \
  'http://metadata.google.internal/computeMetadata/v1/instance/attributes/elastic-password')"

docker rm -f elasticsearch || true
docker run -d \
  --name elasticsearch \
  --restart unless-stopped \
  -p 127.0.0.1:9200:9200 \
  -e discovery.type=single-node \
  -e xpack.security.enabled=true \
  -e ELASTIC_PASSWORD="${PASSWORD}" \
  -e ES_JAVA_OPTS="-Xms3g -Xmx3g" \
  -v elasticsearch-data:/usr/share/elasticsearch/data \
  docker.elastic.co/elasticsearch/elasticsearch:8.15.5

