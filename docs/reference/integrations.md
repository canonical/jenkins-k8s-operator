# Integrations

### agent

_Interface_: jenkins_agent_v0  
_Supported charms_: [jenkins-agent-k8s](https://charmhub.io/jenkins-agent-k8s),
[jenkins-agent](https://charmhub.io/jenkins-agent)

Jenkins agents provide a way to perform tasks scheduled by the Jenkins server. Jenkins agents are
used to distribute workload across multiple machines, allowing parallel execution of jobs.

Example agent relate command: `juju relate jenkins-k8s:agent jenkins-agent-k8s:agent`
