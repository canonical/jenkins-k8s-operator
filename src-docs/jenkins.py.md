<!-- markdownlint-disable -->

<a href="../src/jenkins.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `jenkins.py`
Functions to operate Jenkins. 

**Global Variables**
---------------
- **WEB_PORT**
- **WEB_URL**
- **LOGIN_PATH**
- **LOGIN_URL**
- **REQUIRED_PLUGINS**
- **USER**
- **GROUP**
- **BUILT_IN_NODE_NAME**
- **RSS_FEED_URL**
- **WAR_DOWNLOAD_URL**
- **SYSTEM_PROPERTY_HEADLESS**
- **SYSTEM_PROPERTY_LOGGING**
- **DEFAULT_JENKINS_CONFIG**
- **JENKINS_LOGGING_CONFIG**
- **PLUGIN_NAME_GROUP**
- **WHITESPACE**
- **VERSION_GROUP**
- **DEPENDENCIES_GROUP**
- **PLUGIN_CAPTURE**
- **PLUGIN_LINE_CAPTURE**

---

<a href="../src/jenkins.py#L113"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L185"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L217"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `is_storage_ready`

```python
is_storage_ready(container: Optional[Container]) → bool
```

Return whether the Jenkins home directory is mounted and owned by jenkins. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 



**Raises:**
 
 - <b>`StorageMountError`</b>:  if there was an error getting storage information. 



**Returns:**
 True if home directory is mounted and owned by jenkins, False otherwise. 


---

<a href="../src/jenkins.py#L242"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `calculate_env`

```python
calculate_env() → Environment
```

Return a dictionary for Jenkins Pebble layer. 



**Returns:**
  The dictionary mapping of environment variables for the Jenkins service. 


---

<a href="../src/jenkins.py#L251"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L436"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `bootstrap`

```python
bootstrap(container: Container, proxy_config: ProxyConfig | None = None) → None
```

Initialize and install Jenkins. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 
 - <b>`proxy_config`</b>:  The Jenkins proxy configuration settings. 



**Raises:**
 
 - <b>`JenkinsBootstrapError`</b>:  if there was an error installing given plugins or required plugins. 


---

<a href="../src/jenkins.py#L474"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_node_secret`

```python
get_node_secret(node_name: str, container: Container) → str
```

Get node secret from jenkins. 



**Args:**
 
 - <b>`node_name`</b>:  The registered node to fetch the secret from. 
 - <b>`container`</b>:  The Jenkins workload container. 



**Returns:**
 The Jenkins agent node secret. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script getting the node secret. 


---

<a href="../src/jenkins.py#L531"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `add_agent_node`

```python
add_agent_node(agent_meta: AgentMeta, container: Container) → None
```

Add a Jenkins agent node. 



**Args:**
 
 - <b>`agent_meta`</b>:  The Jenkins agent metadata to create the node from. 
 - <b>`container`</b>:  The Jenkins workload container. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script creating the node. 


---

<a href="../src/jenkins.py#L552"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `remove_agent_node`

```python
remove_agent_node(agent_name: str, container: Container) → None
```

Remove a Jenkins agent node. 



**Args:**
 
 - <b>`agent_name`</b>:  The agent node name to remove. 
 - <b>`container`</b>:  The Jenkins workload container. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if an error occurred running groovy script removing the node. 


---

<a href="../src/jenkins.py#L605"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `safe_restart`

```python
safe_restart(container: Container) → None
```

Safely restart Jenkins server after all jobs are done executing. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container to interact with filesystem. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if there was an API error calling safe restart. 


---

<a href="../src/jenkins.py#L630"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L810"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `remove_unlisted_plugins`

```python
remove_unlisted_plugins(
    plugins: Optional[Iterable[str]],
    container: Container
) → None
```

Remove plugins that are not in the list of desired plugins. 



**Args:**
 
 - <b>`plugins`</b>:  The list of plugins that can be installed. 
 - <b>`container`</b>:  The workload container. 



**Raises:**
 
 - <b>`JenkinsPluginError`</b>:  if there was an error removing unlisted plugin or there are plugins  currently being installed. 
 - <b>`JenkinsError`</b>:  if there was an error restarting Jenkins after removing the plugin. 
 - <b>`TimeoutError`</b>:  if it took too long to restart Jenkins after removing the plugin. 


---

<a href="../src/jenkins.py#L906"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `rotate_credentials`

```python
rotate_credentials(container: Container) → str
```

Invalidate all Jenkins sessions and create new password for admin account. 



**Args:**
 
 - <b>`container`</b>:  The workload container. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if any error happened running the groovy script to invalidate sessions. 



**Returns:**
 The new generated password. 


---

## <kbd>class</kbd> `Credentials`
Information needed to log into Jenkins. 



**Attributes:**
 
 - <b>`username`</b>:  The Jenkins account username used to log into Jenkins. 
 - <b>`password_or_token`</b>:  The Jenkins API token or account password used to log into Jenkins. 





---

## <kbd>class</kbd> `Environment`
Dictionary mapping of Jenkins environment variables. 



**Attributes:**
 
 - <b>`JENKINS_HOME`</b>:  The Jenkins home directory. 





---

## <kbd>class</kbd> `JenkinsBootstrapError`
An error occurred during the bootstrapping process. 





---

## <kbd>class</kbd> `JenkinsError`
Base exception for Jenkins errors. 





---

## <kbd>class</kbd> `JenkinsPluginError`
An error occurred installing Jenkins plugin. 





---

## <kbd>class</kbd> `StorageMountError`
Represents an error probing for Jenkins storage mount. 



**Attributes:**
 
 - <b>`msg`</b>:  Explanation of the error. 

<a href="../src/jenkins.py#L208"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str)
```

Initialize a new instance of the StorageMountError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





---

## <kbd>class</kbd> `ValidationError`
An unexpected data is encountered. 





