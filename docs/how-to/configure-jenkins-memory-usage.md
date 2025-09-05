# How to control heap memory
The [jenkins-k8s-operator](https://github.com/canonical/jenkins-k8s-operator) charm uses [Juju constraints](https://juju.is/docs/juju/constraint) to limit the amount of memory a charm can use. To deploy the charm with constraints, use the `--constraints "<key>=<value>"` option when running `juju deploy`:
```bash
juju deploy jenkins-k8s --channel=latest/edge --constraints "mem=2048M"
```
To change this value after deployment, use the `set-constraints` command.
```bash
juju set-constraints jenkins-k8s "mem=4096M"
```
Other types of constraints (like cores, disk, etc.) can also be applied. Note that this value affects the shared maximum memory between the `charm` container and `jenkins` container.

## Considerations when applying memory constraints
Constraints set this way directly influence the amount of heap memory available to the JVM, with a ratio `JVM heap / Container Memory limit` of 0.5. For example, a `jenkins-k8s-operator` charm deployed with `--constraints "mem=1024M"` would set a maximum heap memory size of 512Mb. Too little heap memory can result in the controller getting restarted due to Out-of-memory (OOM) error. Make sure to adapt the memory constraints based on your workload.