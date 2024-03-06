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



**Attributes:**
 
 - <b>`agent_discovery_url`</b>:  external hostname to be passed to agents for discovery. 

<a href="../src/agent.py#L39"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(
    charm: CharmBase,
    state: State,
    ingress_observer: Observer,
    jenkins_wrapper: Jenkins
)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 
 - <b>`state`</b>:  The charm state. 
 - <b>`jenkins_wrapper`</b>:  The Jenkins wrapper. 
 - <b>`ingress_observer`</b>:  The ingress observer responsible for agent discovery. 


---

#### <kbd>property</kbd> agent_discovery_url

Return the external hostname to be passed to agents via the integration. 

If we do not have an ingress, then use the pod ip as hostname. The reason to prefer this over the pod name (which is the actual hostname visible from the pod) or a K8s service, is that those are routable virtually exclusively inside the cluster as they rely on the cluster's DNS service, while the ip address is _sometimes_ routable from the outside, e.g., when deploying on MicroK8s on Linux. 



**Returns:**
  The charm's agent discovery url. 

---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 



---

<a href="../src/agent.py#L253"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `reconfigure_agent_discovery`

```python
reconfigure_agent_discovery(_: EventBase) → None
```

Update the agent discovery URL in each of the connected agent's integration data. 

Will cause agents to restart!! 


