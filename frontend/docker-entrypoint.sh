#!/bin/sh
# Inject the container's DNS resolver into nginx config at startup.
# This handles Podman's aardvark-dns IP changing across network recreations.
RESOLVER=$(awk '/^nameserver/{print $2; exit}' /etc/resolv.conf)
RESOLVER=${RESOLVER:-127.0.0.11}
sed -i "s/__RESOLVER__/${RESOLVER}/g" /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
