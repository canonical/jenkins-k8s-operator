<!-- markdownlint-disable -->

<a href="../src/state.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `state.py`
Jenkins States. 

**Global Variables**
---------------
- **AGENT_RELATION**
- **DEPRECATED_AGENT_RELATION**


---

## <kbd>class</kbd> `AgentMeta`
Metadata for registering Jenkins Agent. 



**Attributes:**
 
 - <b>`executors`</b>:  Number of executors of the agent in string format. 
 - <b>`labels`</b>:  Comma separated list of labels to be assigned to the agent. 
 - <b>`name`</b>:  The host name of the agent. 




---

<a href="../src/state.py#L119"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `from_agent_relation`

```python
from_agent_relation(
    relation_data: RelationDataContent
) → Optional[ForwardRef('AgentMeta')]
```

Instantiate AgentMeta from charm relation databag. 



**Args:**
 
 - <b>`relation_data`</b>:  The unit relation databag. 



**Returns:**
 AgentMeta if complete values(executors, labels, slavehost) are set. None otherwise. 

---

<a href="../src/state.py#L100"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `from_deprecated_agent_relation`

```python
from_deprecated_agent_relation(
    relation_data: RelationDataContent
) → Optional[ForwardRef('AgentMeta')]
```

Instantiate AgentMeta from charm relation databag. 



**Args:**
 
 - <b>`relation_data`</b>:  The unit relation databag. 



**Returns:**
 AgentMeta if complete values(executors, labels, slavehost) are set. None otherwise. 

---

<a href="../src/state.py#L87"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `numeric_executors`

```python
numeric_executors(value: str) → int
```

Validate executors field can be converted to int. 



**Args:**
 
 - <b>`value`</b>:  The value of executors field. 



**Returns:**
 Coerced numerical value of executors. 


---

## <kbd>class</kbd> `CharmConfigInvalidError`
Exception raised when a charm configuration is found to be invalid. 



**Attributes:**
 
 - <b>`msg`</b>:  Explanation of the error. 

<a href="../src/state.py#L33"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str)
```

Initialize a new instance of the CharmConfigInvalidError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





---

## <kbd>class</kbd> `CharmIllegalNumUnitsError`
Represents an error with invalid number of units deployed. 



**Attributes:**
 
 - <b>`msg`</b>:  Explanation of the error. 

<a href="../src/state.py#L65"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str)
```

Initialize a new instance of the CharmIllegalNumUnitsError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





---

## <kbd>class</kbd> `CharmRelationDataInvalidError`
Represents an error with invalid data in relation data. 



**Attributes:**
 
 - <b>`msg`</b>:  Explanation of the error. 

<a href="../src/state.py#L49"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str)
```

Initialize a new instance of the CharmRelationDataInvalidError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





---

## <kbd>class</kbd> `CharmStateBaseError`
Represents an error with charm state. 





---

## <kbd>class</kbd> `ProxyConfig`
Configuration for accessing Jenkins through proxy. 



**Attributes:**
 
 - <b>`http_proxy`</b>:  The http proxy URL. 
 - <b>`https_proxy`</b>:  The https proxy URL. 
 - <b>`no_proxy`</b>:  Comma separated list of hostnames to bypass proxy. 




---

<a href="../src/state.py#L199"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `from_env`

```python
from_env() → Optional[ForwardRef('ProxyConfig')]
```

Instantiate ProxyConfig from juju charm environment. 



**Returns:**
  ProxyConfig if proxy configuration is provided, None otherwise. 


---

## <kbd>class</kbd> `State`
The Jenkins k8s operator charm state. 



**Attributes:**
 
 - <b>`restart_time_range`</b>:  Time range to allow Jenkins to update version. 
 - <b>`agent_relation_meta`</b>:  Metadata of all agents from units related through agent relation. 
 - <b>`deprecated_agent_relation_meta`</b>:  Metadata of all agents from units related through  deprecated agent relation. 
 - <b>`proxy_config`</b>:  Proxy configuration to access Jenkins upstream through. 
 - <b>`plugins`</b>:  The list of allowed plugins to install. 
 - <b>`jenkins_service_name`</b>:  The Jenkins service name. Note that the container name is the same. 




---

<a href="../src/state.py#L240"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `from_charm`

```python
from_charm(charm: CharmBase) → State
```

Initialize the state from charm. 



**Args:**
 
 - <b>`charm`</b>:  The charm root JenkinsK8SOperatorCharm. 



**Returns:**
 Current state of Jenkins. 



**Raises:**
 
 - <b>`CharmConfigInvalidError`</b>:  if invalid state values were encountered. 
 - <b>`CharmRelationDataInvalidError`</b>:  if invalid relation data was received. 
 - <b>`CharmIllegalNumUnitsError`</b>:  if more than 1 unit of Jenkins charm is deployed. 


