#!/bin/bash

# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Pre-run script for integration test operator-workflows action.
# https://github.com/canonical/operator-workflows/blob/main/.github/workflows/integration_test.yaml


# The IAM bundle requires metallb to be enabled 
IPADDR=$(ip -4 -j route get 2.2.2.2 | jq -r '.[] | .prefsrc')
microk8s enable "metallb:$IPADDR-$IPADDR"

# Jenkins machine agent charm is deployed on lxd and Jenkins-k8s server charm is deployed on
# microk8s.
# lxd should be install and init by a previous step in integration test action.
echo "bootstrapping lxd juju controller"
sg snap_microk8s -c "microk8s status --wait-ready"
sg snap_microk8s -c "juju bootstrap localhost localhost"

echo "Switching to testing model"
TESTING_MODEL="$(juju switch)"
juju models
juju controllers
echo "$TESTING_MODEL"
sg snap_microk8s -c "juju switch $TESTING_MODEL"
