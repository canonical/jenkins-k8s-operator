<!-- markdownlint-disable -->

<a href="../src/charm.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `charm.py`
Charm Jenkins. 

**Global Variables**
---------------
- **JENKINS_SERVICE_NAME**
- **AGENT_DISCOVERY_INGRESS_RELATION_NAME**


---

## <kbd>class</kbd> `JenkinsK8sOperatorCharm`
Charmed Jenkins. 

<a href="../src/charm.py#L38"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(*args: Any)
```

Initialize the charm and register event handlers. 



**Args:**
 
 - <b>`args`</b>:  Arguments to initialize the charm base. 



**Raises:**
 
 - <b>`RuntimeError`</b>:  if invalid state value was encountered from relation. 


---

#### <kbd>property</kbd> app

Application that this unit is part of. 

---

#### <kbd>property</kbd> charm_dir

Root directory of the charm as it is running. 

---

#### <kbd>property</kbd> config

A mapping containing the charm's config and current values. 

---

#### <kbd>property</kbd> meta

Metadata of this charm. 

---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 

---

#### <kbd>property</kbd> unit

Unit that this execution is responsible for. 




