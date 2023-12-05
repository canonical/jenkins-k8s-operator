<!-- markdownlint-disable -->

<a href="../src/charm.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `charm.py`
Charm Jenkins. 



---

## <kbd>class</kbd> `JenkinsK8sOperatorCharm`
Charm Jenkins. 



**Attributes:**
 
 - <b>`is_storage_ready`</b>:  Whether the Jenkins home storage is mounted. 

<a href="../src/charm.py#L40"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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

#### <kbd>property</kbd> is_storage_ready

Return whether the Jenkins home storage is mounted. 



**Returns:**
  True if storage is mounted, False otherwise. 

---

#### <kbd>property</kbd> meta

Metadata of this charm. 

---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 

---

#### <kbd>property</kbd> unit

Unit that this execution is responsible for. 




