# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Bootstrap-specific Jenkins tests intentionally deferred.

Current Jenkins bootstrap behavior is exercised through focused helper tests in:
- test_jenkins_jcasc.py (unlock/config install)
- test_jenkins_plugins.py (plugin install/remove flows)
- test_jenkins_readiness.py (readiness checks)

The legacy bootstrap method-level tests relied on removed APIs and were retired during
module decomposition.
"""
