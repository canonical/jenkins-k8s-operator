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
- **SYSTEM_PROPERTY_LOGGING**
- **PLUGIN_NAME_GROUP**
- **WHITESPACE**
- **VERSION_GROUP**
- **DEPENDENCIES_GROUP**
- **PLUGIN_CAPTURE**
- **PLUGIN_LINE_CAPTURE**

---

<a href="../src/jenkins.py#L146"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L175"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L199"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `calculate_env`

```python
calculate_env() → Environment
```

Return a dictionary for Jenkins Pebble layer. 



**Returns:**
  The dictionary mapping of environment variables for the Jenkins service. 


---

<a href="../src/jenkins.py#L208"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L381"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L418"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L441"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L466"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L575"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_updatable_version`

```python
get_updatable_version(proxy: ProxyConfig | None = None) → str | None
```

Get version to update to if available. 



**Args:**
 
 - <b>`proxy`</b>:  Proxy server to route the requests through. 



**Raises:**
 
 - <b>`JenkinsUpdateError`</b>:  if there was an error trying to determine next Jenkins update version. 



**Returns:**
 Patched version string if the update is available. None if latest version is applied. 


---

<a href="../src/jenkins.py#L604"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `has_updates_for_lts`

```python
has_updates_for_lts(proxy: ProxyConfig | None = None) → bool
```

Return whether the Jenkins has a patched LTS update available. 



**Args:**
 
 - <b>`proxy`</b>:  Proxy server to route the requests through. 



**Raises:**
 
 - <b>`JenkinsUpdateError`</b>:  If there was an error fetching the Jenkins version information. 



**Returns:**
 True if an update within the same LTS is available. False otherwise. 


---

<a href="../src/jenkins.py#L651"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `update_jenkins`

```python
update_jenkins(container: Container, proxy: ProxyConfig | None = None) → str
```

Update Jenkins and return the updated version. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 
 - <b>`proxy`</b>:  The proxy settings to apply. 



**Raises:**
 
 - <b>`JenkinsUpdateError`</b>:  If there was an error updating Jenkins. 
 - <b>`JenkinsRestartError`</b>:  If there was an error restarting updated Jenkins. 



**Returns:**
 The updated Jenkins version. 


---

<a href="../src/jenkins.py#L718"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L743"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L891"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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
 
 - <b>`JenkinsPluginError`</b>:  if there was an error removing unlisted plugin. 
 - <b>`JenkinsError`</b>:  if there was an error restarting Jenkins after removing the plugin. 
 - <b>`TimeoutError`</b>:  if it took too long to restart Jenkins after removing the plugin. 


---

<a href="../src/jenkins.py#L979"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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
 - <b>`password`</b>:  The Jenkins account password used to log into Jenkins. 





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

## <kbd>class</kbd> `JenkinsNetworkError`
An error occurred communicating with the upstream Jenkins server. 





---

## <kbd>class</kbd> `JenkinsPluginError`
An error occurred installing Jenkins plugin. 





---

## <kbd>class</kbd> `JenkinsProxyError`
An error occurred configuring Jenkins proxy. 





---

## <kbd>class</kbd> `JenkinsRestartError`
An error occurred trying to restart Jenkins. 





---

## <kbd>class</kbd> `JenkinsUpdateError`
An error occurred trying to update Jenkins. 





---

## <kbd>class</kbd> `ValidationError`
An unexpected data is encountered. 





