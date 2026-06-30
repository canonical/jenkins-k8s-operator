# Integration Test Command for JCasC Repository Configuration

## Quick Start

Run the integration test for JCasC repository configuration using one of the commands below.

### Option 1: Using tox (recommended)

```bash
tox -e integration -- --charm-file=<charm_path> --jenkins-image=<image>
```

### Option 2: Using pytest directly

```bash
PYTHONPATH=src:lib python -m pytest tests/integration/test_jenkins.py::test_jcasc_repository_config_from_file \
  --jenkins-image=<image> \
  --charm-file=<charm_path> \
  --kube-config=~/.kube/config \
  -v
```

## Detailed Setup

### Prerequisites

1. **Kubernetes Cluster**: MicroK8s or similar (requires `microk8s enable registry` for local testing)
2. **Juju Model**: Already connected with `juju switch <model>`
3. **Jenkins OCI Image**: Built and pushed to registry
4. **Charm**: Built using `charmcraft pack`

### Step-by-Step Instructions

#### 1. Build the Jenkins OCI image (if not already built)

```bash
cd <project_dir>
rockcraft pack
# Push to local registry if using MicroK8s:
skopeo --insecure-policy copy --dest-tls-verify=false \
  oci-archive:jenkins*.rock \
  docker://localhost:32000/jenkins:latest
```

#### 2. Build the charm

```bash
cd <project_dir>
charmcraft pack
```

#### 3. Create/switch to a Juju model

```bash
# Create model (if needed)
juju add-model jcasc-test

# Switch to the model
juju switch jcasc-test

# Enable debug logging (optional)
juju model-config logging-config="<root>=INFO;unit=DEBUG"
```

#### 4. Run the integration test

**Basic command:**

```bash
cd <project_dir>
tox -e integration -- \
  --charm-file=jenkins-k8s*.charm \
  --jenkins-image=localhost:32000/jenkins:latest
```

**Full command with all options:**

```bash
PYTHONPATH=src:lib python -m pytest \
  tests/integration/test_jenkins.py::test_jcasc_repository_config_from_file \
  --jenkins-image=localhost:32000/jenkins:latest \
  --charm-file=jenkins-k8s*.charm \
  --kube-config=~/.kube/config \
  --num-units=1 \
  -v \
  --tb=short \
  -s
```

## Command Arguments Reference

| Argument | Value | Required | Description |
|----------|-------|----------|-------------|
| `--charm-file` | Path to `.charm` file | Yes | Built charm package (supports wildcards) |
| `--jenkins-image` | Image reference | Yes | Jenkins OCI image (e.g., `localhost:32000/jenkins:latest`) |
| `--kube-config` | Path to kubeconfig | No | Kubernetes config file (defaults to `~/.kube/config`) |
| `--num-units` | Integer | No | Number of charm units to deploy (default: 1) |
| `-v` / `--verbose` | N/A | No | Verbose output |
| `--tb=short` | N/A | No | Shorter traceback on failures |
| `-s` / `--capture=no` | N/A | No | Don't capture output (see print statements) |

## Test Details

**Test Name:** `test_jcasc_repository_config_from_file`

**Location:** `tests/integration/test_jenkins.py::test_jcasc_repository_config_from_file`

**What it verifies:**
1. ✅ JCasC export endpoint is accessible (HTTP 200)
2. ✅ Git repository configuration is applied during deployment
3. ✅ JCasC YAML from git repository is loaded and integrated
4. ✅ Fixture values are present in exported configuration:
   - `systemMessage: "Jenkins Configuration as Code (JCasC) via Git Repository"`
   - `numExecutors: 2`
   - `mode: NORMAL`
   - `unclassified.location.url: http://localhost:8080/`

**Fixture Files:**
- `tests/integration/data/jcasc/jenkins.yaml` — Jenkins-specific configuration
- `tests/integration/data/jcasc/unclassified.yaml` — Unclassified section configuration

## Expected Output

```
tests/integration/test_jenkins.py::test_jcasc_repository_config_from_file PASSED [100%]
```

Success indicators:
- Test status: `PASSED`
- No assertion failures
- JCasC export contains expected fixture values

## Troubleshooting

### Image not found error
```
Error: Image 'localhost:32000/jenkins:latest' not found
```
Solution: Push the image to the registry:
```bash
skopeo --insecure-policy copy --dest-tls-verify=false \
  oci-archive:jenkins*.rock \
  docker://localhost:32000/jenkins:latest
```

### Charm file not found
```
AssertionError: Charm not built
```
Solution: Build the charm first:
```bash
charmcraft pack
```

### Juju model not connected
```
Error: Model is not connected
```
Solution: Switch to the correct model:
```bash
juju switch <model-name>
```

### Git command failed in charm container
```
AssertionError: Command failed in charm container: git --version
```
Solution: Ensure git is available in the charm container. This may indicate the container image doesn't include git.

## CI/CD Integration

For GitHub Actions or similar CI systems:

```yaml
- name: Run JCasC integration test
  run: |
    tox -e integration -- \
      --charm-file=./jenkins-k8s*.charm \
      --jenkins-image=${{ env.JENKINS_IMAGE }} \
      --kube-config=${{ env.KUBECONFIG }}
  env:
    JENKINS_IMAGE: localhost:32000/jenkins:latest
```

## References

- [pytest-operator documentation](https://github.com/canonical/pytest-operator)
- [Juju documentation](https://juju.is/docs)
- [Jenkins Charm Repository](https://github.com/canonical/jenkins-k8s-operator)
- Implementation: Commit b4e5391 — `test(jcasc): implement integration test for jcasc-repository configuration`
