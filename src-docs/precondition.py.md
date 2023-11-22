<!-- markdownlint-disable -->

<a href="../src/precondition.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `precondition.py`
The Jenkins charm precondition checking module. 


---

<a href="../src/precondition.py#L54"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `check`

```python
check(charm: CharmBase, charm_state: State) → None
```

Check all preconditions required to start the Jenkins service. 



**Args:**
 
 - <b>`charm`</b>:  The Jenkins charm. 
 - <b>`charm_state`</b>:  The charm state. 


---

## <kbd>class</kbd> `ConditionCheckError`
Represents an error with charm state. 

<a href="../src/precondition.py#L13"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(msg: str = '')
```

Initialize a new instance of the ConditionCheckBaseError exception. 



**Args:**
 
 - <b>`msg`</b>:  Explanation of the error. 





