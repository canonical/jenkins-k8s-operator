<!-- markdownlint-disable -->

<a href="../src/state.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `state.py`
Jenkins States. 



---

## <kbd>class</kbd> `CharmConfigInvalidError`
Exception raised when a charm configuration is found to be invalid. 



**Attributes:**
 
 - <b>`msg`</b>:  Explanation of the error. 

<a href="../src/state.py#L27"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str)
```

Initialize a new instance of the CharmConfigInvalidError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





---

## <kbd>class</kbd> `CharmStateBaseError`
Represents an error with charm state. 





---

## <kbd>class</kbd> `State`
The Jenkins k8s operator charm state. 



**Attributes:**
 
 - <b>`jenkins_service_name`</b>:  The Jenkins service name. Note that the container name is the same. 
 - <b>`update_time_range`</b>:  Time range to allow Jenkins to update version. 




---

<a href="../src/state.py#L48"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

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


