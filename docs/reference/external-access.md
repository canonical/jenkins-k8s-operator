# External access
The Jenkins charm requires access to the following domains to install Jenkins and its plugins:

* `jenkins-ci.org`
* `updates.jenkins-ci.org`
* `jenkins.io`
* `updates.jenkins.io`
* `.mirrors.jenkins-ci.org`
* `fallback.get.jenkins.io`
* `get.jenkins.io`
* `pkg.jenkins.io`
* `archives.jenkins.io`
* `pkg.origin.jenkins.io`
* `.mirrors.jenkins.io`
* `www.jenkins.io`

Depending on the localisation, some region-specific external mirrors might also be used. You can find more information on the [list of mirrors for Jenkins](https://get.jenkins.io/war/2.456/jenkins.war?mirrorstats).

Some plugins can also require external access, such as `github.com` for the [Github branch source plugin](https://plugins.jenkins.io/github-branch-source/) or an external Kubernetes cluster if you are using the [Kubernetes plugin](https://plugins.jenkins.io/kubernetes/). Refer to the plugin's documentation for more details.
