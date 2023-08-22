# Contributing

Build the OCI image:

```bash
cd jenkins_rock
rockcraft pack
```

Push the OCI image to microk8s:

```bash
sudo /snap/rockcraft/current/bin/skopeo --insecure-policy copy oci-archive:jenkins_rock/Jenkins_1.0_amd64.rock docker-daemon:jenkins:1.0
sudo docker tag jenkins:1.0 localhost:32000/jenkins:1.0
sudo docker push localhost:32000/jenkins:1.0
```

Deploy the charm:

```bash
charmcraft pack
juju deploy ./jenkins-k8s-operator_ubuntu-22.04-amd64.charm --resource jenkins-image=localhost:32000/jenkins:1.0
```

## Generating src docs for every commit

Run the following command:

```bash
echo -e "tox -e src-docs\ngit add src-docs\n" > .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```
