<!-- markdownlint-disable -->

<a href="../src/jenkins.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `jenkins.py`
Functions to operate Jenkins. 

**Global Variables**
---------------
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

<a href="../src/jenkins.py#L126"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L155"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_admin_credentials`

```python
get_admin_credentials(container: Container) → Credentials
```

Retrieve admin credentials. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container to interact with filesystem. 



**Returns:**
 The Jenkins admin account credentials. 


---

<a href="../src/jenkins.py#L181"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `calculate_env`

```python
calculate_env() → Environment
```

Return a dictionary for Jenkins Pebble layer. 



**Returns:**
  The dictionary mapping of environment variables for the Jenkins service. 


---

<a href="../src/jenkins.py#L192"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L284"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `bootstrap`

```python
bootstrap(container: Container) → None
```

Initialize and install Jenkins. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 



**Raises:**
 
 - <b>`JenkinsBootstrapError`</b>:  if there was an error installing given plugins or required plugins. 


---

<a href="../src/jenkins.py#L320"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_node_secret`

```python
get_node_secret(
    node_name: str,
    container: Container,
    client: Jenkins | None = None
) → str
```

Get node secret from jenkins. 



**Args:**
 
 - <b>`node_name`</b>:  The registered node to fetch the secret from. 
 - <b>`container`</b>:  The Jenkins workload container. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Returns:**
 The Jenkins agent node secret. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script getting the node secret. 


---

<a href="../src/jenkins.py#L348"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `add_agent_node`

```python
add_agent_node(
    agent_meta: AgentMeta,
    container: Container,
    client: Jenkins | None = None
) → None
```

Add a Jenkins agent node. 



**Args:**
 
 - <b>`agent_meta`</b>:  The Jenkins agent metadata to create the node from. 
 - <b>`container`</b>:  The Jenkins workload container. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script creating the node. 


---

<a href="../src/jenkins.py#L378"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `remove_agent_node`

```python
remove_agent_node(
    agent_name: str,
    credentials: Credentials,
    client: Jenkins | None = None
) → None
```

Remove a Jenkins agent node. 



**Args:**
 
 - <b>`agent_name`</b>:  The agent node name to remove. 
 - <b>`credentials`</b>:  The credentials of a Jenkins user with access to the Jenkins API. 
 - <b>`client`</b>:  The API client used to communicate with the Jenkins server. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script removing the node. 


---

<a href="../src/jenkins.py#L484"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L510"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `download_stable_war`

```python
download_stable_war(container: Container, version: str) → None
```

Download and replace the war executable. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins container with jenkins.war executable. 
 - <b>`version`</b>:  Desired version of the war to download. 



**Raises:**
 
 - <b>`JenkinsNetworkError`</b>:  if there was an error fetching the jenkins.war executable. 


---

<a href="../src/jenkins.py#L570"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L598"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_agent_name`

```python
get_agent_name(unit_name: str) → str
```

Infer agent name from unit name. 



**Args:**
 
 - <b>`unit_name`</b>:  The agent unit name. 



**Returns:**
 The agent node name registered on Jenkins server. 


---

## <kbd>class</kbd> `Credentials`
Information needed to log into Jenkins. 



**Attributes:**
 
 - <b>`username`</b>:  The Jenkins account username used to log into Jenkins. 
 - <b>`password`</b>:  The Jenkins account password used to log into Jenkins. 





---

## <kbd>class</kbd> `Environment`
Dictionary mapping of Jenkins environment variables. 



**Attributes:**
 
 - <b>`JENKINS_HOME`</b>:  The Jenkins home directory. 
 - <b>`CASC_JENKINS_CONFIG`</b>:  The Jenkins configuration-as-code plugin config path. 





---

## <kbd>class</kbd> `JenkinsBootstrapError`
An error occurred during the bootstrapping process. 





---

## <kbd>class</kbd> `JenkinsError`
Base exception for Jenkins errors. 





---

## <kbd>class</kbd> `JenkinsNetworkError`
An error occurred communicating with the upstream Jenkins server. 





---

## <kbd>class</kbd> `JenkinsPluginError`
An error occurred installing Jenkins plugin. 





---

## <kbd>class</kbd> `JenkinsUpdateError`
An error occurred trying to update Jenkins. 





---

## <kbd>class</kbd> `ValidationError`
An unexpected data is encountered. 




