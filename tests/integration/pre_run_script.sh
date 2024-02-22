#!/bin/bash

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Pre-run script for integration test operator-workflows action.
# https://github.com/canonical/operator-workflows/blob/main/.github/workflows/integration_test.yaml

# Jenkins machine agent charm is deployed on lxd and Jenkins-k8s server charm is deployed on
# microk8s.
# lxd should be install and init by a previous step in integration test action.
echo "bootstrapping lxd juju controller"
sg snap_microk8s -c "microk8s status --wait-ready"
sg snap_microk8s -c "juju bootstrap localhost localhost"

TESTING_CONTROLLER="$(juju controllers --format json | jq '.controllers | with_entries(select(.key | endswith("microk8s"))) | to_entries[0] | .key')"
echo "Switching to testing model"
sg snap_microk8s -c "juju switch $TESTING_CONTROLLER"

# Remove proxy vars as they prevent the k8s API from being reachable.
head -n  1 /etc/environment > temp && sudo mv temp /etc/environment
unset HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy
