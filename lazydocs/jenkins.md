<!-- markdownlint-disable -->

<a href="../src/jenkins.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `jenkins`
Functions to operate Jenkins. 

**Global Variables**
---------------
- **jenkinsapi**
- **WEB_PORT**
- **WEB_URL**
- **LOGIN_URL**
- **REQUIRED_PLUGINS**
- **USER**
- **GROUP**
- **BUILT_IN_NODE_NAME**
- **RSS_FEED_URL**
- **WAR_DOWNLOAD_URL**
- **SYSTEM_PROPERTY_HEADLESS**

---

<a href="../src/jenkins.py#L160"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `wait_ready`

```python
wait_ready(timeout: int = 300, check_interval: int = 10) → None
```

Wait until Jenkins service is up. 



**Args:**
 
 - <b>`timeout`</b>:  Time in seconds to wait for jenkins to become ready in 10 second intervals. 
 - <b>`check_interval`</b>:  Time in seconds to wait between ready checks. 



**Raises:**
 
 - <b>`TimeoutError`</b>:  if Jenkins status check did not pass within the timeout duration. 


---

<a href="../src/jenkins.py#L189"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_admin_credentials`

```python
get_admin_credentials(connectable_container: Container) → Credentials
```

Retrieve admin credentials. 



**Args:**
 
 - <b>`connectable_container`</b>:  Connectable container to interact with filesystem. 



**Returns:**
 The Jenkins admin account credentials. 


---

<a href="../src/jenkins.py#L217"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `calculate_env`

```python
calculate_env() → Environment
```

Return a dictionary for Jenkins Pebble layer. 



**Returns:**
  The dictionary mapping of environment variables for the Jenkins service. 


---

<a href="../src/jenkins.py#L228"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_version`

```python
get_version() → str
```

Get the Jenkins server version. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if Jenkins is unreachable. 



**Returns:**
 The Jenkins server version. 


---

<a href="../src/jenkins.py#L322"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `bootstrap`

```python
bootstrap(connectable_container: Container) → None
```

Initialize and install Jenkins. 



**Args:**
 
 - <b>`connectable_container`</b>:  The connectable Jenkins workload container. 



**Raises:**
 
 - <b>`JenkinsBootstrapError`</b>:  if there was an error installing given plugins or required plugins. 


---

<a href="../src/jenkins.py#L358"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_node_secret`

```python
get_node_secret(
    node_name: str,
    credentials: Credentials,
    client: Jenkins | None = None
) → str
```

Get node secret from jenkins. 



**Args:**
 
 - <b>`node_name`</b>:  The registered node to fetch the secret from. 
 - <b>`credentials`</b>:  The credentials of a Jenkins user with access to the Jenkins API. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Returns:**
 The Jenkins agent node secret. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script getting the node secret. 


---

<a href="../src/jenkins.py#L386"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `add_agent_node`

```python
add_agent_node(
    agent_meta: AgentMeta,
    credentials: Credentials,
    client: Jenkins | None = None
) → None
```

Add a Jenkins agent node. 



**Args:**
 
 - <b>`agent_meta`</b>:  The Jenkins agent metadata to create the node from. 
 - <b>`credentials`</b>:  The credentials of a Jenkins user with access to the Jenkins API. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script creating the node. 


---

<a href="../src/jenkins.py#L499"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_updatable_version`

```python
get_updatable_version() → str | None
```

Get version to update to if available. 



**Raises:**
 
 - <b>`JenkinsUpdateError`</b>:  if there was an error trying to determine next Jenkins update version. 



**Returns:**
 Patched version string if the update is available. None if latest version is applied. 


---

<a href="../src/jenkins.py#L525"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `download_stable_war`

```python
download_stable_war(connectable_container: Container, version: str) → None
```

Download and replace the war executable. 



**Args:**
 
 - <b>`connectable_container`</b>:  The Jenkins container with jenkins.war executable. 
 - <b>`version`</b>:  Desired version of the war to download. 



**Raises:**
 
 - <b>`JenkinsNetworkError`</b>:  if there was an error fetching the jenkins.war executable. 


---

<a href="../src/jenkins.py#L585"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `safe_restart`

```python
safe_restart(credentials: Credentials, client: Jenkins | None = None) → None
```

Safely restart Jenkins server after all jobs are done executing. 



**Args:**
 
 - <b>`credentials`</b>:  The credentials of a Jenkins user with access to the Jenkins API. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if there was an API error calling safe restart. 


---

<a href="../src/jenkins.py#L62"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `JenkinsError`
Base exception for Jenkins errors. 





---

<a href="../src/jenkins.py#L66"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `JenkinsPluginError`
An error occurred installing Jenkins plugin. 





---

<a href="../src/jenkins.py#L70"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `JenkinsBootstrapError`
An error occurred during the bootstrapping process. 





---

<a href="../src/jenkins.py#L74"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `ValidationError`
An unexpected data is encountered. 





---

<a href="../src/jenkins.py#L78"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `JenkinsNetworkError`
An error occurred communicating with the upstream Jenkins server. 





---

<a href="../src/jenkins.py#L82"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `JenkinsUpdateError`
An error occurred trying to update Jenkins. 





---

<a href="../src/jenkins.py#L86"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `AgentMeta`
Metadata for registering Jenkins Agent. 



**Attributes:**
 
 - <b>`executors`</b>:  Number of executors of the agent in string format. 
 - <b>`labels`</b>:  Comma separated list of labels to be assigned to the agent. 
 - <b>`slavehost`</b>:  The host name of the agent. 

<a href="../<string>"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(executors: str, labels: str, slavehost: str) → None
```








---

<a href="../src/jenkins.py#L100"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `validate`

```python
validate() → None
```

Validate the agent metadata. 



**Raises:**
 
 - <b>`ValidationError`</b>:  if the field contains invalid data. 


---

<a href="../src/jenkins.py#L176"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `Credentials`
Information needed to log into Jenkins. 



**Attributes:**
 
 - <b>`username`</b>:  The Jenkins account username used to log into Jenkins. 
 - <b>`password`</b>:  The Jenkins account password used to log into Jenkins. 

<a href="../<string>"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(username: str, password: str) → None
```









---

<a href="../src/jenkins.py#L205"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `Environment`
Dictionary mapping of Jenkins environment variables. 



**Attributes:**
 
 - <b>`JENKINS_HOME`</b>:  The Jenkins home directory. 
 - <b>`CASC_JENKINS_CONFIG`</b>:  The Jenkins configuration-as-code plugin config path. 







---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
