Module src.jenkins
==================
Functions to operate Jenkins.

Functions
---------

    
`add_agent_node(agent_meta: src.jenkins.AgentMeta, credentials: src.jenkins.Credentials, client: jenkinsapi.jenkins.Jenkins | None = None) ‑> None`
:   Add a Jenkins agent node.
    
    Args:
        agent_meta: The Jenkins agent metadata to create the node from.
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.
    
    Raises:
        JenkinsError: if an error occurred running groovy script creating the node.

    
`bootstrap(connectable_container: ops.model.Container) ‑> None`
:   Initialize and install Jenkins.
    
    Args:
        connectable_container: The connectable Jenkins workload container.
    
    Raises:
        JenkinsBootstrapError: if there was an error installing given plugins or required plugins.

    
`calculate_env() ‑> src.jenkins.Environment`
:   Return a dictionary for Jenkins Pebble layer.
    
    Returns:
        The dictionary mapping of environment variables for the Jenkins service.

    
`download_stable_war(connectable_container: ops.model.Container, version: str) ‑> None`
:   Download and replace the war executable.
    
    Args:
        connectable_container: The Jenkins container with jenkins.war executable.
        version: Desired version of the war to download.
    
    Raises:
        JenkinsNetworkError: if there was an error fetching the jenkins.war executable.

    
`get_admin_credentials(connectable_container: ops.model.Container) ‑> src.jenkins.Credentials`
:   Retrieve admin credentials.
    
    Args:
        connectable_container: Connectable container to interact with filesystem.
    
    Returns:
        The Jenkins admin account credentials.

    
`get_node_secret(node_name: str, credentials: src.jenkins.Credentials, client: jenkinsapi.jenkins.Jenkins | None = None) ‑> str`
:   Get node secret from jenkins.
    
    Args:
        node_name: The registered node to fetch the secret from.
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.
    
    Returns:
        The Jenkins agent node secret.
    
    Raises:
        JenkinsError: if an error occurred running groovy script getting the node secret.

    
`get_updatable_version() ‑> str | None`
:   Get version to update to if available.
    
    Raises:
        JenkinsUpdateError: if there was an error trying to determine next Jenkins update version.
    
    Returns:
        Patched version string if the update is available. None if latest version is applied.

    
`get_version() ‑> str`
:   Get the Jenkins server version.
    
    Raises:
        JenkinsError: if Jenkins is unreachable.
    
    Returns:
        The Jenkins server version.

    
`safe_restart(credentials: src.jenkins.Credentials, client: jenkinsapi.jenkins.Jenkins | None = None) ‑> None`
:   Safely restart Jenkins server after all jobs are done executing.
    
    Args:
        credentials: The credentials of a Jenkins user with access to the Jenkins API.
        client: The API client used to communicate with the Jenkins server.
    
    Raises:
        JenkinsError: if there was an API error calling safe restart.

    
`wait_ready(timeout: int = 300, check_interval: int = 10) ‑> None`
:   Wait until Jenkins service is up.
    
    Args:
        timeout: Time in seconds to wait for jenkins to become ready in 10 second intervals.
        check_interval: Time in seconds to wait between ready checks.
    
    Raises:
        TimeoutError: if Jenkins status check did not pass within the timeout duration.

Classes
-------

`AgentMeta(executors: str, labels: str, slavehost: str)`
:   Metadata for registering Jenkins Agent.
    
    Attrs:
        executors: Number of executors of the agent in string format.
        labels: Comma separated list of labels to be assigned to the agent.
        slavehost: The host name of the agent.

    ### Class variables

    `executors: str`
    :

    `labels: str`
    :

    `slavehost: str`
    :

    ### Methods

    `validate(self) ‑> None`
    :   Validate the agent metadata.
        
        Raises:
            ValidationError: if the field contains invalid data.

`Credentials(username: str, password: str)`
:   Information needed to log into Jenkins.
    
    Attrs:
        username: The Jenkins account username used to log into Jenkins.
        password: The Jenkins account password used to log into Jenkins.

    ### Class variables

    `password: str`
    :

    `username: str`
    :

`Environment(*args, **kwargs)`
:   Dictionary mapping of Jenkins environment variables.
    
    Attrs:
        JENKINS_HOME: The Jenkins home directory.
        CASC_JENKINS_CONFIG: The Jenkins configuration-as-code plugin config path.

    ### Ancestors (in MRO)

    * builtins.dict

    ### Class variables

    `CASC_JENKINS_CONFIG: str`
    :

    `JENKINS_HOME: str`
    :

`JenkinsBootstrapError(*args, **kwargs)`
:   An error occurred during the bootstrapping process.

    ### Ancestors (in MRO)

    * src.jenkins.JenkinsError
    * builtins.Exception
    * builtins.BaseException

`JenkinsError(*args, **kwargs)`
:   Base exception for Jenkins errors.

    ### Ancestors (in MRO)

    * builtins.Exception
    * builtins.BaseException

    ### Descendants

    * src.jenkins.JenkinsBootstrapError
    * src.jenkins.JenkinsNetworkError
    * src.jenkins.JenkinsPluginError
    * src.jenkins.JenkinsUpdateError

`JenkinsNetworkError(*args, **kwargs)`
:   An error occurred communicating with the upstream Jenkins server.

    ### Ancestors (in MRO)

    * src.jenkins.JenkinsError
    * builtins.Exception
    * builtins.BaseException

`JenkinsPluginError(*args, **kwargs)`
:   An error occurred installing Jenkins plugin.

    ### Ancestors (in MRO)

    * src.jenkins.JenkinsError
    * builtins.Exception
    * builtins.BaseException

`JenkinsUpdateError(*args, **kwargs)`
:   An error occurred trying to update Jenkins.

    ### Ancestors (in MRO)

    * src.jenkins.JenkinsError
    * builtins.Exception
    * builtins.BaseException

`ValidationError(*args, **kwargs)`
:   An unexpected data is encountered.

    ### Ancestors (in MRO)

    * builtins.Exception
    * builtins.BaseException