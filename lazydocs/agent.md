<!-- markdownlint-disable -->

<a href="../src/agent.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `agent`
The Jenkins agent relation observer. 



---

<a href="../src/agent.py#L18"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `AgentRelationData`
Relation data required for adding the Jenkins agent. 



**Attributes:**
 
 - <b>`url`</b>:  The Jenkins server url. 
 - <b>`secret`</b>:  The secret for agent node. 





---

<a href="../src/agent.py#L30"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `Observer`
The Jenkins agent relation observer. 

<a href="../src/agent.py#L33"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(charm: CharmBase, state: State)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 
 - <b>`state`</b>:  The charm state. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 






---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
