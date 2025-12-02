# How to Upgrade the jenkins-k8s Charm

This guide provides step-by-step instructions for upgrading the `jenkins-k8s` charm to a new revision in your Kubernetes environment.

## Prerequisites
- Ensure you have access to the Juju controller managing your deployment.
- Confirm that you have the necessary permissions to perform upgrades.
- Review the [changelog](../changelog.md) for important updates and breaking changes.

## Steps to Upgrade

### 1. Check the Current Charm Revision
Run the following command to verify the current revision of the deployed charm:

```bash
juju status jenkins-k8s
```

### 2. Review the New Revision
Before upgrading, review the new charm revision and its release notes:
- Check the [changelog](../changelog.md) for details.
- Validate compatibility with your environment and integrations.

### 3. Upgrade the Charm
To upgrade to the latest revision, use:

```bash
juju refresh jenkins-k8s
```

To upgrade to a specific revision, use:

```bash
juju refresh jenkins-k8s --revision=<REVISION_NUMBER>
```

### 4. Monitor the Upgrade
Monitor the status and logs to ensure the upgrade completes successfully:

```bash
juju status jenkins-k8s
juju debug-log --include=jenkins-k8s
```

### 5. Validate Functionality
After the upgrade:
- Check that Jenkins is running and accessible.
- Verify that all integrations and plugins are functioning as expected.
- Review any custom configurations for compatibility.

## Troubleshooting
- If the upgrade fails, consult the Juju logs and charm documentation.
- Roll back to a previous revision if necessary:

```bash
juju refresh jenkins-k8s --revision=<PREVIOUS_REVISION>
```

## Additional Resources
- [Juju Documentation](https://juju.is/docs)
- [jenkins-k8s Operator Documentation](../index.md)
- [Changelog](../changelog.md)

---
For further assistance, contact the maintainers or open an issue in the project repository.
