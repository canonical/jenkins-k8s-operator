# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

lxd init --auto
sudo usermod -a -G microk8s runner
sudo chown -R runner ~/.kube
newgrp microk8s
