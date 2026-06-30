# JCasC-from-Git Integration Test — Design

Date: 2026-06-30
Status: Approved (pending spec review)
Feature branch: `feat/jcasc-git-repository`

## Problem

The charm config option `jcasc-repository` lets operators source Jenkins
Configuration-as-Code (JCasC) YAML from a git repository. The implementation
(`jenkins.fetch_jcasc_repository`, `src/jenkins.py:1234`) clones the repo with
`/usr/bin/git` and merges the YAML, and `charm._reconcile_jcasc_config`
(`src/charm.py:571-600`) fetches, merges, and applies it.

There is **no real integration coverage** of this path. The existing test
`test_jcasc_repository_config_from_file` (`tests/integration/test_jenkins.py:306`)
is a non-functional placeholder: it never sets `jcasc-repository`, never stages a
repo, and only asserts the export endpoint returns 200 and contains the word
`"jenkins"` — true of any Jenkins server regardless of source, so it cannot catch
a clone → merge → apply regression. A regression in that path would not turn the
suite red.

## Goal

Make the deployed Jenkins server source its JCasC from a git repository **by
default**, via the module-scoped `application` fixture, then assert the
repository's configuration is live in Jenkins. Because every other test in the
module runs against this git-configured server, any regression in the
repository-fetch path fails the suite broadly — not just one test.

## Scope

In scope:
- A throwaway `file://` git repository staged inside the charm container at
  fixture setup, seeded from in-repo fixture data under `tests/integration/data/`.
- The `application` fixture configures `jcasc-repository` pointing at that
  `file://` URL, with `jcasc-config` cleared.
- One focused assertion test proving the repository's distinctive markers reached
  Jenkins through the JCasC export endpoint.

Out of scope (explicit, with rationale):
- **Token / private-repo authentication.** The HTTP Basic-auth branch
  (`src/jenkins.py:1256-1259`) requires an HTTP(S) transport; a `file://` repo
  cannot exercise it. This branch stays covered by unit tests
  (`tests/unit/test_jenkins_jcasc.py`). Documented coverage gap — do not fake it.
- Mutual-exclusion and fetch-failure negative tests (deferred; not part of this
  lean scope).

## Architecture & Critical Constraints

Read this section carefully before writing any code — three non-obvious facts
drive the whole implementation.

### 1. The clone runs in the CHARM container, not the workload

`jenkins.fetch_jcasc_repository` calls
`subprocess.run(["/usr/bin/git", "clone", "--depth", "1", clone_url, ...])`
directly (`src/jenkins.py:1264`). Charm hook code executes in the **charm**
(operator) container, so:
- The `file://` repository and the `git` binary must both exist in the **charm**
  container — reach it with `juju ssh --container charm <unit>` (NOT
  `--container jenkins`, which is the workload). Precedent for `--container` exec:
  `tests/integration/helpers.py:471` uses
  `ops_test.juju("ssh", "--container", "jenkins", ...)`; use `charm` here.
- `git clone --depth 1` with no `--branch` clones the **default branch HEAD**.
  A freshly `git init`'d repo's first commit is on the default branch, so a single
  `git init && git add && git commit` is sufficient — no branch juggling needed.

### 2. `jcasc-config` ships a non-empty default → mutual-exclusion trap

`config.options.jcasc-config` has a non-empty default (`charmcraft.yaml:129`), so
`_parse_jcasc_config` returns a dict (not None) unless explicitly cleared
(`src/state.py:233-235`). The state layer raises on both being set
(`src/state.py:413-416`):
`"jcasc-config and jcasc-repository are mutually exclusive; set only one"`.
Therefore the fixture MUST set `jcasc-config=""` in the **same** `set_config`
call that sets `jcasc-repository`, or the charm goes blocked.

### 3. `git` may be absent in the charm container (make-or-break risk)

Nothing in `charmcraft.yaml` stages `git` into the charm container (the `uv`
plugin adds no `stage-packages`), and the charm base is minimal Ubuntu. If
`/usr/bin/git` is missing, the feature is broken in production — and unit tests
mock `subprocess`, so they never catch it. Making git-the-default in the fixture
is precisely what surfaces this. The implementation plan MUST include an early
`git --version` smoke check in the charm container (via `juju ssh --container
charm`) so a missing binary fails loudly with a clear message instead of an opaque
blocked status. If git is absent, that is a real feature bug to report, not a test
defect to work around.

## Fixture Data

Location: `tests/integration/data/jcasc/` (a new `jcasc/` subdirectory, so the
default `jcasc-repository-config-path` value of `"jcasc"` resolves without extra
config). A flat `tests/integration/data/jcasc.yaml` already exists with exactly
the content below (verified: nothing in `tests/` references it — it is an orphan
from an earlier session). Split its two top-level blocks into two files under
`jcasc/` so the test also exercises the multi-file deep-merge
(`src/jenkins.py:1289-1303`):

`tests/integration/data/jcasc/jenkins.yaml`
```yaml
jenkins:
  systemMessage: "Jenkins Configuration as Code (JCasC) via Git Repository"
  numExecutors: 2
  mode: NORMAL
  quietPeriod: 5
  scmCheckoutRetryCount: 0
```

`tests/integration/data/jcasc/unclassified.yaml`
```yaml
unclassified:
  location:
    url: "http://localhost:8080/"
```

Distinctive markers used by the assertion:
- `systemMessage` value `"Jenkins Configuration as Code (JCasC) via Git
  Repository"` — unique string, will not collide with the charm-managed default
  `"Managed by jenkins-k8s charm via JCasC"` (`charmcraft.yaml:131`).
- `numExecutors: 2` — differs from the charm default `0` (`charmcraft.yaml:132`),
  proving the repo value won, not the default.

Note on charm-managed overrides: `build_jcasc_config` (`src/charm.py:602`) injects
securityRealm/admin credentials but does NOT override `systemMessage` or
`numExecutors`, so both markers survive into the exported config. Assert on
`systemMessage` as the primary signal.

## Fixture Staging Sequence

Modify the module-scoped `application` fixture
(`tests/integration/conftest.py:87-108`). After the charm deploys and reaches
active/idle, and BEFORE the `fast_forward` block, stage the repo and switch
config. Concrete steps for the implementer:

1. Resolve the unit name: `unit = application.units[0]`; `unit_name = unit.name`.

2. Smoke-check git in the charm container (fail fast, see Constraint 3):
   ```python
   ret, stdout, stderr = await ops_test.juju(
       "ssh", "--container", "charm", unit_name, "git", "--version"
   )
   assert ret == 0, f"git missing in charm container: {stderr}"
   ```

3. Create the repo directory and seed files in the charm container. Read each
   fixture file on the test host (`pathlib.Path(__file__).parent / "data" /
   "jcasc" / "<name>"`), then write it into the container. Use a base64 round-trip
   to avoid quoting/heredoc pitfalls — pipe via stdin is not available through
   `ops_test.juju`, so embed the encoded content in the command:
   ```python
   import base64
   REPO_DIR = "/tmp/jcasc-repo"  # nosec: hardcoded test path in charm container
   await charm_exec(ops_test, unit_name, f"mkdir -p {REPO_DIR}/jcasc")
   for name in ("jenkins.yaml", "unclassified.yaml"):
       content = (DATA_DIR / "jcasc" / name).read_text(encoding="utf-8")
       b64 = base64.b64encode(content.encode()).decode()
       await charm_exec(
           ops_test, unit_name,
           f"bash -c 'echo {b64} | base64 -d > {REPO_DIR}/jcasc/{name}'",
       )
   ```
   where `charm_exec` is a tiny local helper that calls
   `ops_test.juju("ssh", "--container", "charm", unit_name, *shlex.split(cmd))`
   and asserts `ret == 0`.

4. Initialise the git repo in the charm container (single commit on default
   branch — see Constraint 1):
   ```python
   await charm_exec(ops_test, unit_name, f"git -C {REPO_DIR} init")
   await charm_exec(ops_test, unit_name, f"git -C {REPO_DIR} add .")
   await charm_exec(
       ops_test, unit_name,
       f"git -C {REPO_DIR} -c user.email=test@test -c user.name=test "
       f"commit -m fixture",
   )
   ```

5. Point the charm at the repo and clear `jcasc-config` in ONE call
   (see Constraint 2):
   ```python
   await application.set_config({
       "jcasc-config": "",
       "jcasc-repository": f"file://{REPO_DIR}",
       "jcasc-repository-config-path": "jcasc",
   })
   await model.wait_for_idle(
       apps=[application.name], status="active", timeout=20 * 60,
   )
   ```

6. Proceed into the existing `fast_forward` block and `yield application`
   unchanged.

Module-level constant to add near the top of `conftest.py`:
`DATA_DIR = pathlib.Path(__file__).parent / "data"`.

## Assertion Test

Replace the placeholder `test_jcasc_repository_config_from_file`
(`tests/integration/test_jenkins.py:306-325`) with a real test. Pattern it on the
working `test_jcasc_reload_without_restart` (`tests/integration/test_jenkins.py:268`),
which is the proven shape for "config change → wait_for_idle → assert against the
export endpoint".

```python
async def test_jcasc_repository_config_applied(
    application: Application,
    web_address: str,
    jenkins_client: jenkinsapi.jenkins.Jenkins,
):
    """
    arrange: given a Jenkins charm whose `application` fixture sources JCasC from
        a git repository by default.
    act: query the JCasC export endpoint.
    assert: the repository's distinctive systemMessage is present, proving the
        clone -> merge -> apply path ran.
    """
    response = jenkins_client.requester.post_url(
        f"{web_address}/configuration-as-code/export"
    )
    assert response.status_code == 200
    exported = response.text
    assert "Jenkins Configuration as Code (JCasC) via Git Repository" in exported
```

The test itself is deliberately thin because the **fixture** is what exercises the
feature. No `set_config` inside the test — the server is already git-configured.

Why no explicit `numExecutors` assertion: `systemMessage` is a unique,
unambiguous marker; asserting one strong signal keeps the test focused. Implementers
MAY add a secondary `assert "numExecutors: 2" in exported` if the export format
makes it stable, but it is optional.

## Files to Change

- `tests/integration/data/jcasc/jenkins.yaml` — NEW (the `jenkins:` block of the
  old flat `data/jcasc.yaml`).
- `tests/integration/data/jcasc/unclassified.yaml` — NEW (the `unclassified:`
  block of the old flat file).
- `tests/integration/data/jcasc.yaml` — DELETE. Verified orphan: no test
  references it (re-confirm with `search_files(pattern="jcasc.yaml", path="tests")`
  if you want belt-and-braces, but the search came back empty during design).
- `tests/integration/conftest.py` — add `DATA_DIR` + `base64`/`shlex`/`pathlib`
  imports, the `charm_exec` helper, and the staging steps in the `application`
  fixture.
- `tests/integration/test_jenkins.py` — replace placeholder
  `test_jcasc_repository_config_from_file` with `test_jcasc_repository_config_applied`.

## Risks & Mitigations

- **git absent in charm container** (highest risk): the `git --version` smoke check
  in step 2 turns this into a clear, early assertion failure rather than an opaque
  blocked status. If it fires, report it as a feature bug (charm must stage `git`)
  — do not work around it in the test.
- **`file://` + `--depth 1` shallow clone**: shallow clone of a local `file://`
  repo is supported by git; if a specific CI git version objects, fall back to
  cloning without `--depth` is NOT an option (the charm controls the clone flags),
  so instead ensure the staged repo has at least one commit (it does, step 4).
- **Fixture leaks into other tests**: making git-the-default is intentional — every
  module test now runs against the git-configured server. Confirm no existing test
  asserts the OLD default `systemMessage` (`"Managed by jenkins-k8s charm via
  JCasC"`); `search_files(pattern="Managed by jenkins-k8s")` before finalising.
- **`set_config` race**: always `wait_for_idle(status="active")` after `set_config`
  (step 5) so later tests don't observe a mid-reconcile server.

## Verification

Per the user's verification rule — commit BEFORE running checks so the toolchain
reads committed code, not the working tree:

1. `git add -A && git commit` the fixtures, conftest, and test changes.
2. Static/lint/unit (host): `tox run -e lint,unit,static,coverage-report`.
3. Integration (on `ssh dev`, not the laptop): the module's integration suite,
   which now runs entirely against the git-configured server. Confirm
   `test_jcasc_repository_config_applied` passes AND the rest of the module still
   passes (proving the new default fixture didn't break unrelated tests).

Definition of done: integration suite green on `ssh dev` with the git-sourced
fixture active, and `test_jcasc_repository_config_applied` asserting the
repository marker is live in Jenkins.
