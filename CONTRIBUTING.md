# Contributing

Build the OCI image:

```bash
cd jenkins_rock
rockcraft pack
cd ..
```

Push the OCI image to microk8s:

```bash
rockcraft.skopeo --insecure-policy copy --dest-tls-verify=false oci-archive:jenkins_rock/jenkins_1.0_amd64.rock docker://localhost:32000/jenkins:1.0
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
