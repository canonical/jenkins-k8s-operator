<!-- markdownlint-disable -->

<a href="../src/agent.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `agent.py`
The Jenkins agent relation observer. 

**Global Variables**
---------------
- **AGENT_RELATION**
- **DEPRECATED_AGENT_RELATION**
- **JENKINS_SERVICE_NAME**


---

## <kbd>class</kbd> `AgentRelationData`
Relation data required for adding the Jenkins agent. 



**Attributes:**
 
 - <b>`url`</b>:  The Jenkins server url. 
 - <b>`secret`</b>:  The secret for agent node. 





---

## <kbd>class</kbd> `Observer`
The Jenkins agent relation observer. 

<a href="../src/agent.py#L31"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(charm: CharmBase, state: State, jenkins_wrapper: Jenkins)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 
 - <b>`state`</b>:  The charm state. 
 - <b>`jenkins_wrapper`</b>:  The Jenkins wrapper. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 




