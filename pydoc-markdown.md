Generated using: `pydoc-markdown -I src --render-toc > pydoc-markdown.md`

# Table of Contents

* [state](#state)
  * [CharmStateBaseError](#state.CharmStateBaseError)
  * [CharmConfigInvalidError](#state.CharmConfigInvalidError)
    * [\_\_init\_\_](#state.CharmConfigInvalidError.__init__)
  * [State](#state.State)
    * [from\_charm](#state.State.from_charm)
* [timerange](#timerange)
  * [InvalidTimeRangeError](#timerange.InvalidTimeRangeError)
  * [Range](#timerange.Range)
    * [validate\_range](#timerange.Range.validate_range)
    * [from\_str](#timerange.Range.from_str)
    * [check\_now](#timerange.Range.check_now)
* [charm](#charm)
  * [JenkinsK8sOperatorCharm](#charm.JenkinsK8sOperatorCharm)
    * [\_\_init\_\_](#charm.JenkinsK8sOperatorCharm.__init__)
* [agent](#agent)
  * [AgentRelationData](#agent.AgentRelationData)
  * [Observer](#agent.Observer)
    * [\_\_init\_\_](#agent.Observer.__init__)
* [jenkins](#jenkins)
  * [JenkinsError](#jenkins.JenkinsError)
  * [JenkinsPluginError](#jenkins.JenkinsPluginError)
  * [JenkinsBootstrapError](#jenkins.JenkinsBootstrapError)
  * [ValidationError](#jenkins.ValidationError)
  * [JenkinsNetworkError](#jenkins.JenkinsNetworkError)
  * [JenkinsUpdateError](#jenkins.JenkinsUpdateError)
  * [AgentMeta](#jenkins.AgentMeta)
    * [validate](#jenkins.AgentMeta.validate)
  * [wait\_ready](#jenkins.wait_ready)
  * [Credentials](#jenkins.Credentials)
  * [get\_admin\_credentials](#jenkins.get_admin_credentials)
  * [Environment](#jenkins.Environment)
  * [calculate\_env](#jenkins.calculate_env)
  * [get\_version](#jenkins.get_version)
  * [bootstrap](#jenkins.bootstrap)
  * [get\_node\_secret](#jenkins.get_node_secret)
  * [add\_agent\_node](#jenkins.add_agent_node)
  * [get\_updatable\_version](#jenkins.get_updatable_version)
  * [download\_stable\_war](#jenkins.download_stable_war)
  * [safe\_restart](#jenkins.safe_restart)

<a id="state"></a>

# state

Jenkins States.

<a id="state.CharmStateBaseError"></a>

## CharmStateBaseError Objects

```python
class CharmStateBaseError(Exception)
```

Represents error with charm state.

<a id="state.CharmConfigInvalidError"></a>

## CharmConfigInvalidError Objects

```python
class CharmConfigInvalidError(CharmStateBaseError)
```

Exception raised when a charm configuration is found to be invalid.

Attributes:
    msg: Explanation of the error.

<a id="state.CharmConfigInvalidError.__init__"></a>

#### \_\_init\_\_

```python
def __init__(msg: str)
```

Initialize a new instance of the CharmConfigInvalidError exception.

**Arguments**:

- `msg` - Explanation of the error.

<a id="state.State"></a>

## State Objects

```python
@dataclasses.dataclass(frozen=True)
class State()
```

The Jenkins k8s operator charm state.

Attributes:
    jenkins_service_name: The Jenkins service name. Note that the container name is the same.
    update_time_range: Time range to allow Jenkins to update version.

<a id="state.State.from_charm"></a>

#### from\_charm

```python
@classmethod
def from_charm(cls, charm: CharmBase) -> "State"
```

Initialize the state from charm.

**Arguments**:

- `charm` - The charm root JenkinsK8SOperatorCharm.
  

**Returns**:

  Current state of Jenkins.
  

**Raises**:

- `CharmConfigInvalidError` - if invalid state values were encountered.

<a id="timerange"></a>

# timerange

The module for checking time ranges.

<a id="timerange.InvalidTimeRangeError"></a>

## InvalidTimeRangeError Objects

```python
class InvalidTimeRangeError(Exception)
```

Represents an invalid time range.

<a id="timerange.Range"></a>

## Range Objects

```python
class Range(BaseModel)
```

Time range to allow Jenkins to update version.

Attributes:
    start: Hour to allow updates from in UTC time, in 24 hour format.
    end: Hour to allow updates until in UTC time, in 24 hour format.

<a id="timerange.Range.validate_range"></a>

#### validate\_range

```python
@root_validator(skip_on_failure=True)
def validate_range(cls: "Range", values: dict) -> dict
```

Validate the time range.

**Arguments**:

- `values` - The value keys of the model.
  

**Returns**:

  A dictionary validated values.
  

**Raises**:

- `ValueError` - if the time range are out of bounds of 24H format.

<a id="timerange.Range.from_str"></a>

#### from\_str

```python
@classmethod
def from_str(cls, time_range: str) -> "Range"
```

Instantiate the class from string time range.

**Arguments**:

- `time_range` - The time range string in H(H)-H(H) format, in UTC.
  

**Raises**:

- `InvalidTimeRangeError` - if invalid time range was given.
  

**Returns**:

- `UpdateTimeRange` - if a valid time range was given.

<a id="timerange.Range.check_now"></a>

#### check\_now

```python
def check_now() -> bool
```

Check whether the current time is within the defined bounds.

**Returns**:

  True if within bounds, False otherwise.

<a id="charm"></a>

# charm

Charm Jenkins.

<a id="charm.JenkinsK8sOperatorCharm"></a>

## JenkinsK8sOperatorCharm Objects

```python
class JenkinsK8sOperatorCharm(CharmBase)
```

Charm Jenkins.

<a id="charm.JenkinsK8sOperatorCharm.__init__"></a>

#### \_\_init\_\_

```python
def __init__(*args: typing.Any)
```

Initialize the charm and register event handlers.

**Arguments**:

- `args` - Arguments to initialize the char base.

<a id="agent"></a>

# agent

The Jenkins agent relation observer.

<a id="agent.AgentRelationData"></a>

## AgentRelationData Objects

```python
class AgentRelationData(typing.TypedDict)
```

Relation data required for adding the Jenkins agent.

Attributes:
    url: The Jenkins server url.
    secret: The secret for agent node.

<a id="agent.Observer"></a>

## Observer Objects

```python
class Observer(Object)
```

The Jenkins agent relation observer.

<a id="agent.Observer.__init__"></a>

#### \_\_init\_\_

```python
def __init__(charm: CharmBase, state: State)
```

Initialize the observer and register event handlers.

**Arguments**:

- `charm` - The parent charm to attach the observer to.
- `state` - The charm state.

<a id="jenkins"></a>

# jenkins

Functions to operate Jenkins.

<a id="jenkins.JenkinsError"></a>

## JenkinsError Objects

```python
class JenkinsError(Exception)
```

Base exception for Jenkins errors.

<a id="jenkins.JenkinsPluginError"></a>

## JenkinsPluginError Objects

```python
class JenkinsPluginError(JenkinsError)
```

An error occurred installing Jenkins plugin.

<a id="jenkins.JenkinsBootstrapError"></a>

## JenkinsBootstrapError Objects

```python
class JenkinsBootstrapError(JenkinsError)
```

An error occurred during the bootstrapping process.

<a id="jenkins.ValidationError"></a>

## ValidationError Objects

```python
class ValidationError(Exception)
```

An unexpected data is encountered.

<a id="jenkins.JenkinsNetworkError"></a>

## JenkinsNetworkError Objects

```python
class JenkinsNetworkError(JenkinsError)
```

An error occurred communicating with the upstream Jenkins server.

<a id="jenkins.JenkinsUpdateError"></a>

## JenkinsUpdateError Objects

```python
class JenkinsUpdateError(JenkinsError)
```

An error occurred trying to update Jenkins.

<a id="jenkins.AgentMeta"></a>

## AgentMeta Objects

```python
@dataclasses.dataclass(frozen=True)
class AgentMeta()
```

Metadata for registering Jenkins Agent.

Attributes:
    executors: Number of executors of the agent in string format.
    labels: Comma separated list of labels to be assigned to the agent.
    slavehost: The host name of the agent.

<a id="jenkins.AgentMeta.validate"></a>

#### validate

```python
def validate() -> None
```

Validate the agent metadata.

**Raises**:

- `ValidationError` - if the field contains invalid data.

<a id="jenkins.wait_ready"></a>

#### wait\_ready

```python
def wait_ready(timeout: int = 300, check_interval: int = 10) -> None
```

Wait until Jenkins service is up.

**Arguments**:

- `timeout` - Time in seconds to wait for jenkins to become ready in 10 second intervals.
- `check_interval` - Time in seconds to wait between ready checks.
  

**Raises**:

- `TimeoutError` - if Jenkins status check did not pass within the timeout duration.

<a id="jenkins.Credentials"></a>

## Credentials Objects

```python
@dataclasses.dataclass(frozen=True)
class Credentials()
```

Information needed to log into Jenkins.

Attributes:
    username: The Jenkins account username used to log into Jenkins.
    password: The Jenkins account password used to log into Jenkins.

<a id="jenkins.get_admin_credentials"></a>

#### get\_admin\_credentials

```python
def get_admin_credentials(connectable_container: ops.Container) -> Credentials
```

Retrieve admin credentials.

**Arguments**:

- `connectable_container` - Connectable container to interact with filesystem.
  

**Returns**:

  The Jenkins admin account credentials.

<a id="jenkins.Environment"></a>

## Environment Objects

```python
class Environment(typing.TypedDict)
```

Dictionary mapping of Jenkins environment variables.

Attributes:
    JENKINS_HOME: The Jenkins home directory.
    CASC_JENKINS_CONFIG: The Jenkins configuration-as-code plugin config path.

<a id="jenkins.calculate_env"></a>

#### calculate\_env

```python
def calculate_env() -> Environment
```

Return a dictionary for Jenkins Pebble layer.

**Returns**:

  The dictionary mapping of environment variables for the Jenkins service.

<a id="jenkins.get_version"></a>

#### get\_version

```python
def get_version() -> str
```

Get the Jenkins server version.

**Raises**:

- `JenkinsError` - if Jenkins is unreachable.
  

**Returns**:

  The Jenkins server version.

<a id="jenkins.bootstrap"></a>

#### bootstrap

```python
def bootstrap(connectable_container: ops.Container) -> None
```

Initialize and install Jenkins.

**Arguments**:

- `connectable_container` - The connectable Jenkins workload container.
  

**Raises**:

- `JenkinsBootstrapError` - if there was an error installing given plugins or required plugins.

<a id="jenkins.get_node_secret"></a>

#### get\_node\_secret

```python
def get_node_secret(node_name: str,
                    credentials: Credentials,
                    client: jenkinsapi.jenkins.Jenkins | None = None) -> str
```

Get node secret from jenkins.

**Arguments**:

- `node_name` - The registered node to fetch the secret from.
- `credentials` - The credentials of a Jenkins user with access to the Jenkins API.
- `client` - The API client used to communicate with the Jenkins server.
  

**Returns**:

  The Jenkins agent node secret.
  

**Raises**:

- `JenkinsError` - if an error occurred running groovy script getting the node secret.

<a id="jenkins.add_agent_node"></a>

#### add\_agent\_node

```python
def add_agent_node(agent_meta: AgentMeta,
                   credentials: Credentials,
                   client: jenkinsapi.jenkins.Jenkins | None = None) -> None
```

Add a Jenkins agent node.

**Arguments**:

- `agent_meta` - The Jenkins agent metadata to create the node from.
- `credentials` - The credentials of a Jenkins user with access to the Jenkins API.
- `client` - The API client used to communicate with the Jenkins server.
  

**Raises**:

- `JenkinsError` - if an error occurred running groovy script creating the node.

<a id="jenkins.get_updatable_version"></a>

#### get\_updatable\_version

```python
def get_updatable_version() -> str | None
```

Get version to update to if available.

**Raises**:

- `JenkinsUpdateError` - if there was an error trying to determine next Jenkins update version.
  

**Returns**:

  Patched version string if the update is available. None if latest version is applied.

<a id="jenkins.download_stable_war"></a>

#### download\_stable\_war

```python
def download_stable_war(connectable_container: ops.Container,
                        version: str) -> None
```

Download and replace the war executable.

**Arguments**:

- `connectable_container` - The Jenkins container with jenkins.war executable.
- `version` - Desired version of the war to download.
  

**Raises**:

- `JenkinsNetworkError` - if there was an error fetching the jenkins.war executable.

<a id="jenkins.safe_restart"></a>

#### safe\_restart

```python
def safe_restart(credentials: Credentials,
                 client: jenkinsapi.jenkins.Jenkins | None = None) -> None
```

Safely restart Jenkins server after all jobs are done executing.

**Arguments**:

- `credentials` - The credentials of a Jenkins user with access to the Jenkins API.
- `client` - The API client used to communicate with the Jenkins server.
  

**Raises**:

- `JenkinsError` - if there was an API error calling safe restart.

