# Integrations

### agent

_Interface_: jenkins_agent_v0  
_Supported charms_: [jenkins-agent-k8s](https://charmhub.io/jenkins-agent-k8s),
[jenkins-agent](https://charmhub.io/jenkins-agent)

Jenkins agents provide a way to perform tasks scheduled by the Jenkins server. Jenkins agents are
used to distribute workload across multiple containers, allowing parallel execution of jobs.

Example agent relate command: `juju relate jenkins-k8s:agent jenkins-agent-k8s:agent`

To create a [cross model relation](https://juju.is/docs/olm/manage-cross-model-integrations) with
a jenkins-agent (VM) charm, create an offer from the machine model.

`juju offer jenkins-agent:agent`

Then, relate the offer from the k8s model where jenkins-k8s charm resides.

`juju relate jenkins-k8s:agent <controller-name>:<juju-user>/<agent-model>.jenkins-agent`

An example of such command would look like the following, using a jenkins-agent deployed on a
localhost
[lxd controller](https://juju.is/docs/olm/get-started-with-juju#heading--prepare-your-cloud).

`juju relate jenkins-k8s:agent localhost:admin/jenkins-vm-model.jenkins-agent`

### logging

_Interface_: loki_push_api  
_Supported charms_: [loki-k8s](https://charmhub.io/loki-k8s)

Logging relation provides a way to scrape logs produced from the Jenkins server charm. The Jenkins 
server logs are stored at `/var/lib/jenkins/jenkins.log`. These logs are the same logs as the logs 
emitted to the standard output. A promtail worker is spawned and will periodically push logs to
Loki.

Example agent relate command: `juju relate jenkins-k8s:logging loki-k8s:logging`

### metrics-endpoint

_Interface_: prometheus_scrape  
_Supported charms_: [prometheus-k8s](https://charmhub.io/prometheus-k8s)

Metrics-endpoint relation allows scraping the `/prometheus` endpoint provided by Jenkins
`prometheus` plugin on port 8080. The `/metrics` endpoint is reserved for `metrics` plugin, which
is a dependency of `prometheus` plugin. The metrics are exposed in the open metrics format and will
only be scraped by Prometheus once the relation becomes active. For more information about the
metrics exposed, please refer to the
[`prometheus` plugin documentation](https://plugins.jenkins.io/prometheus/).

Example agent relate command: 
`juju relate jenkins-k8s:metrics-endpoint prometheus-k8s:metrics-endpoint`

### grafana-dashboard

_Interface_: grafana_dashboard  
_Supported charms_: [grafana-k8s](https://charmhub.io/grafana-k8s)

Grafana-dashboard relation enables quick dashboard access already tailored to fit the needs of 
operators to monitor the charm. The template for the Grafana dashboard for jenkins-k8s charm can be
found at `/src/grafana_dashboards/jenkins.json`. In Grafana UI, it can be found as “Jenkins: 
Performance and Health Overview” under the General section of the dashboard browser 
(`/dashboards`). Modifications to the dashboard can be made but will not be persisted upon
restart/redeployment of the charm.

Grafana-Prometheus relate command: `juju relate grafana-k8s:grafana-source prometheus-k8s:grafana-source`
Grafana-dashboard relate command: `juju relate jenkins-k8s:grafana-dashboard grafana-k8s:grafana-dashboard`
