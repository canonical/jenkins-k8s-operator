<!-- markdownlint-disable -->

<a href="../src/jenkins.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `jenkins.py`
Functions to operate Jenkins. 

**Global Variables**
---------------
- **WEB_PORT**
- **LOGIN_PATH**
- **JUJU_API_TOKEN**
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

<a href="../src/jenkins.py#L116"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L653"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

<a href="../src/jenkins.py#L708"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `install_default_config`

```python
install_default_config(container: Container) → None
```

Install default jenkins-config.xml. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 


---

<a href="../src/jenkins.py#L811"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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
 - <b>`password_or_token`</b>:  The Jenkins API token or account password used to log into Jenkins. 





---

## <kbd>class</kbd> `Environment`
Dictionary mapping of Jenkins environment variables. 



**Attributes:**
 
 - <b>`JENKINS_HOME`</b>:  The Jenkins home directory. 
 - <b>`JENKINS_PREFIX`</b>:  The prefix in which Jenkins will be accessible. 





---

## <kbd>class</kbd> `Jenkins`
Wrapper for Jenkins functionality. 

Attrs:  environment: the Jenkins environment configuration.  web_url: the Jenkins web URL.  login_url: the Jenkins login URL.  version: the Jenkins version. 

<a href="../src/jenkins.py#L162"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(environment: Environment)
```

Construct a Jenkins class. 



**Args:**
 
 - <b>`environment`</b>:  the Jenkins environment. 


---

#### <kbd>property</kbd> login_url

Get the Jenkins login URL. 

Returns: the login URL. 

---

#### <kbd>property</kbd> version

Get the Jenkins server version. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if Jenkins is unreachable. 



**Returns:**
 The Jenkins server version. 

---

#### <kbd>property</kbd> web_url

Get the Jenkins web URL. 

Returns: the web URL. 



---

<a href="../src/jenkins.py#L398"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `add_agent_node`

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

<a href="../src/jenkins.py#L315"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `bootstrap`

```python
bootstrap(
    container: Container,
    jenkins_config_file: str,
    proxy_config: ProxyConfig | None = None
) → None
```

Initialize and install Jenkins. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container. 
 - <b>`jenkins_config_file`</b>:  the path to the Jenkins configuration file to install. 
 - <b>`proxy_config`</b>:  The Jenkins proxy configuration settings. 



**Raises:**
 
 - <b>`JenkinsBootstrapError`</b>:  if there was an error installing the plugins plugins. 

---

<a href="../src/jenkins.py#L340"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `get_node_secret`

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

<a href="../src/jenkins.py#L418"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `remove_agent_node`

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

<a href="../src/jenkins.py#L548"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `remove_unlisted_plugins`

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

<a href="../src/jenkins.py#L520"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `rotate_credentials`

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

<a href="../src/jenkins.py#L466"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `safe_restart`

```python
safe_restart(container: Container) → None
```

Safely restart Jenkins server after all jobs are done executing. 



**Args:**
 
 - <b>`container`</b>:  The Jenkins workload container to interact with filesystem. 



**Raises:**
 
 - <b>`JenkinsError`</b>:  if there was an API error calling safe restart. 

---

<a href="../src/jenkins.py#L214"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `wait_ready`

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

<a href="../src/jenkins.py#L644"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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





