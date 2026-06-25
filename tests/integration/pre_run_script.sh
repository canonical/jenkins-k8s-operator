#!/bin/bash

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# Pre-run script for integration test operator-workflows action.
# https://github.com

# Jenkins machine agent charm is deployed on lxd and Jenkins-k8s server charm is deployed on
# microk8s.

TESTING_MODEL="$(juju switch)"

# Helper function to retry a command until it succeeds or times out
retry_command() {
    local label="$1"
    local cmd="$2"
    local max_attempts=30
    local attempt=1

    echo "Waiting for $label..."
    while [ $attempt -le $max_attempts ]; do
        if eval "$cmd"; then
            echo "Success: $label configuration detected."
            return 0
        fi
        echo "Attempt $attempt/$max_attempts: $label not ready. Retrying in 5 seconds..."
        sleep 5
        attempt=$((attempt + 1))
    done

    echo "Error: Timed out waiting for $label."
    return 1
}

# Function to discover a suitable local IP address range for MetalLB
discover_metallb_range() {
    echo "==============================================="
    echo "  Dynamic MetalLB IP Range Discovery"
    echo "==============================================="

    # 1. Detect primary routing local network interface IP
    local local_ip
    local_ip=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
    if [ -z "$local_ip" ]; then
        echo "Error: Could not determine local IP address."
        exit 1
    fi

    # 2. Extract base subnet prefix (e.g., 192.168.1)
    local subnet_prefix
    subnet_prefix=$(echo "$local_ip" | cut -d'.' -f1-3)
    echo "System IP: $local_ip"
    echo "Inferred Subnet Group: $subnet_prefix.X"

    # 3. Establish a standard safe upper pool target (5 host addresses)
    local start_ip=240
    local end_ip=244
    local metallb_range="$subnet_prefix.$start_ip-$subnet_prefix.$end_ip"

    echo "Verifying network range availability..."
    local conflicts=0
    local last_octet
    local test_ip
    for last_octet in $(seq $start_ip $end_ip); do
        test_ip="$subnet_prefix.$last_octet"
        if ping -c 1 -W 1 "$test_ip" > /dev/null 2>&1; then
            echo "Warning: Address $test_ip is active on the network."
            ((conflicts++))
        fi
    done

    # 4. Enforce failure or fallback routing if the pool is heavily congested
    if [ $conflicts -gt 2 ]; then
        echo "Risk high: Multiple IP responses detected in target range."
        echo "Swapping targeting parameters to a secondary emergency internal pool block..."
        metallb_range="10.15.119.2-10.15.119.4"
    fi

    echo "Target Pool Chosen: $metallb_range"
    echo "==============================================="
    
    # Return the discovered range to the caller
    echo "$metallb_range"
}

# Run the range discovery and capture the result
METALLB_RANGE=$(discover_metallb_range)

# lxd should be install and init by a previous step in integration test action.
echo "bootstrapping lxd juju controller"

# Assign dynamically detected network path range 
sg snap_microk8s -c "sudo microk8s enable metallb:$METALLB_RANGE"

# 5. Wait for MetalLB IPAddressPool Custom Resource Definition to be populated
CHECK_POOL_CMD='POOL_RANGE=$(sg snap_microk8s -c "microk8s kubectl get ipaddresspool -n metallb-system -o jsonpath=\"{.items[*].spec.addresses[*]}\" 2>/dev/null"); [ -n "$POOL_RANGE" ]'
if ! retry_command "MetalLB IP address pool" "$CHECK_POOL_CMD"; then
    exit 1
fi

sg snap_microk8s -c "microk8s status --wait-ready --timeout 1200"
sg snap_microk8s -c "juju bootstrap localhost localhost --debug"

echo "Switching to testing model"
sg snap_microk8s -c "juju switch $TESTING_MODEL"
