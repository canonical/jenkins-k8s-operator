juju destroy-model jenkinsdepl --destroy-storage --force -y
juju add-model jenkinsdepl
charmcraft pack
juju deploy ./jenkins-k8s_ubuntu-22.04-amd64.charm --resource jenkins-image=localhost:32000/jenkins:latest
juju deploy jenkins-agent-k8s --channel=latest/edge --num-units=3
juju integrate jenkins-k8s:agent jenkins-agent-k8s:agent
watch juju status