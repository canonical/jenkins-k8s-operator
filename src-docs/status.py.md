<!-- markdownlint-disable -->

<a href="../src/status.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `status.py`
The charm status module. 


---

<a href="../src/status.py#L11"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_priority_status`

```python
get_priority_status(statuses: Iterable[StatusBase]) → StatusBase
```

Get status to display out of all possible statuses returned by charm components. 



**Args:**
 
 - <b>`statuses`</b>:  Statuses returned by components of the charm. 



**Returns:**
 The final status to display. 


