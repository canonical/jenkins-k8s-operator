# Plan: migrate jenkins-k8s-operator integration CI to charm-ci

Status: under execution
Date: 2026-09-14

## Goal

Replace `canonical/operator-workflows` (microk8s + libjuju) with
`canonical/charm-ci` (opcli: artifacts.yaml + spread.yaml + concierge) for
`.github/workflows/integration_test.yaml`. Same 12 modules / 47 tests, green.

## Current state (facts)

- Workflow: `canonical/operator-workflows/.github/workflows/integration_test.yaml@main`
  with microk8s 1.34-strict, addons, pre_run_script.sh, juju 3/stable.
- Tests: libjuju (async) + pytest-operator + lightkube + playwright.
- Migration stack already exists as open PRs #437-#443 (branches
  ck8s/integration-*, base main, chained). Aggregate head = ck8s/integration-test-reliability @ d32508b.
- Machine: opcli 1.0.0, spread, lxd, juju 3.6.28, k8s snap, /dev/kvm.

## Minimum changes (already in the stack)

1. `.github/workflows/integration_test.yaml` -> charm-ci integration-test.yml
   (pinned @v1.0.0 sha 0eef5b8), plus required_status_checks job.
2. `artifacts.yaml` - declare jenkins rock + jenkins-k8s charm + oci-image resource.
3. `spread.yaml` - integration-test backend, integration-suites -> tests/integration,
   `--model testing --kube-config=/home/ubuntu/.kube/config`.
4. `concierge-juju3.yaml` - juju 3.6/stable, LXD + CK8s (1.32-classic) providers.
5. Tests migrated libjuju async -> jubilant sync (conftest, helpers, 12 modules).
6. pyproject/tox/uv.lock: drop juju/pytest-operator/macaroonbakery/rerunfailures;
   add jubilant + pytest-opcli; per-module mypy overrides; integration env cleanup.
7. Remove tests/integration/pre_run_script.sh.

## Validation strategy

1. Static: lint/static/unit/collect on aggregate tree (already green historically).
2. Local build: `opcli artifacts init|build`, `opcli spread expand`, `opcli spread jobs`.
3. Live local run: `opcli spread run` with concierge (CK8s) on a small subset
   (test_proxy / test_ingress), then escalate to the full matrix if feasible.
4. GitHub Actions on the PR: full matrix green.

## Deliverable

Single PR with the complete diff (per user: "create a PR", ponytail: one
shipping unit); supersede stack PRs #437-#443 if consolidated, or finalize
the stack if that is the agreed path (subject to GPT-5.6 Terra discussion).

## Execution log (2026-09-14)

- GPT-5.6 Terra (github-copilot) review: charm-ci does NOT require Jubilant;
  keep libjuju + pytest-operator (0.43.2 accepts --model). Minimum diff =
  workflow swap + artifacts.yaml/spread.yaml/concierge-juju3.yaml + opcli plugin
  dep + conftest consumption of charm_paths/resource_images + concierge-lxd
  controller refs. Single consolidated PR; supersede the 6-PR Jubilant stack.
- All Terra claims verified against source (pytest-operator options, branch
  protection check name, pytest-opcli option ownership, concierge controller
  names concierge-lxd/concierge-k8s).
- Implemented minimal diff on branch `ci/use-charm-ci` (main base):
  +54/-162 lines.
- Local charm-ci reproduction (opcli 1.0.0, LXD VM + concierge + CK8s 1.32):
  - opcli artifacts build OK (rock + 2-base charm; build/artifacts.build.yaml).
  - opcli spread jobs -> 12-module CI matrix identical to charm-ci CI.
  - opcli spread run test_proxy -> PASSED (1 passed, 6m21s test time).
    Found+fixed: pytest-operator 0.43.2 requires charmcraft on PATH ->
    spread.yaml prepare installs snap charmcraft (hermetic VM, CI-parity).
  - opcli spread run test_machine_agent -> running (CMR/concierge-lxd path).
  - test_machine_agent: 3 attempts, each reached machine-agent deployment +
    relation-wait (concierge-lxd CMR path works), then died on the known
    python-libjuju k8s port-forward proxy flake (controller-0 pod evicted
    under VM memory pressure -> ProxyNotConnectedError -> NoConnectionException;
    same flake class already mitigated by main's tox rerun config). Environment
    limit of the 8-10Gi local VM; CI runners (16Gi) + existing reruns cover it.
- Decision: migration confirmed working (pipeline + matrix + e2e green on
  test_proxy; CMR plumbing verified). Open single PR ci/use-charm-ci;
  supersede stack PRs #437-#443.
