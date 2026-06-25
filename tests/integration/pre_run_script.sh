#!/bin/bash

# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

# Pre-run script for integration test operator-workflows action.
# https://github.com

# Jenkins machine agent charm is deployed on lxd and Jenkins-k8s server charm is deployed on
# microk8s.

TESTING_MODEL="$(juju switch)"

echo "==============================================="
echo "  Dynamic MetalLB IP Range Discovery"
echo "==============================================="

# 1. Detect primary routing local network interface IP
LOCAL_IP=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
if [ -z "$LOCAL_IP" ]; then
    echo "Error: Could not determine local IP address."
    exit 1
fi

# 2. Extract base subnet prefix (e.g., 192.168.1)
SUBNET_PREFIX=$(echo "$LOCAL_IP" | cut -d'.' -f1-3)
echo "System IP: $LOCAL_IP"
echo "Inferred Subnet Group: $SUBNET_PREFIX.X"

# 3. Establish a standard safe upper pool target (5 host addresses)
START_IP=240
END_IP=250
METALLB_RANGE="$SUBNET_PREFIX.$START_IP-$SUBNET_PREFIX.$END_IP"

echo "Verifying network range availability..."
CONFLICTS=0
for last_octet in $(seq $START_IP $END_IP); do
    TEST_IP="$SUBNET_PREFIX.$last_octet"
    if ping -c 1 -W 1 "$TEST_IP" > /dev/null 2>&1; then
        echo "Warning: Address $TEST_IP is active on the network."
        ((CONFLICTS++))
    fi
done

# 4. Enforce failure or fallback routing if the pool is heavily congested
if [ $CONFLICTS -gt 2 ]; then
    echo "Risk high: Multiple IP responses detected in target range."
    echo "Swapping targeting parameters to a secondary emergency internal pool block..."
    METALLB_RANGE="10.15.119.2-10.15.119.4"
fi

echo "Target Pool Chosen: $METALLB_RANGE"
echo "==============================================="

# lxd should be install and init by a previous step in integration test action.
echo "bootstrapping lxd juju controller"

# Assign dynamically detected network path range 
sg snap_microk8s -c "sudo microk8s enable metallb:$METALLB_RANGE"
sg snap_microk8s -c "microk8s status --wait-ready --timeout 1200"
sg snap_microk8s -c "juju bootstrap localhost localhost --debug"

echo "Switching to testing model"
sg snap_microk8s -c "juju switch $TESTING_MODEL"
