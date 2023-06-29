<!-- markdownlint-disable -->

<a href="../src/timerange.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `timerange`
The module for checking time ranges. 



---

<a href="../src/timerange.py#L11"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `InvalidTimeRangeError`
Represents an invalid time range. 





---

<a href="../src/timerange.py#L15"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `Range`
Time range to allow Jenkins to update version. 

Attrs:  start: Hour to allow updates from in UTC time, in 24 hour format.  end: Hour to allow updates until in UTC time, in 24 hour format. 




---

<a href="../src/timerange.py#L76"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `check_now`

```python
check_now() → bool
```

Check whether the current time is within the defined bounds. 



**Returns:**
  True if within bounds, False otherwise. 

---

<a href="../src/timerange.py#L49"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `from_str`

```python
from_str(time_range: str) → Range
```

Instantiate the class from string time range. 



**Args:**
 
 - <b>`time_range`</b>:  The time range string in H(H)-H(H) format, in UTC. 



**Raises:**
 
 - <b>`InvalidTimeRangeError`</b>:  if invalid time range was given. 



**Returns:**
 
 - <b>`UpdateTimeRange`</b>:  if a valid time range was given. 

---

<a href="../src/timerange.py#L27"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>classmethod</kbd> `validate_range`

```python
validate_range(values: dict) → dict
```

Validate the time range. 



**Args:**
 
 - <b>`values`</b>:  The value keys of the model. 



**Returns:**
 A dictionary validated values. 



**Raises:**
 
 - <b>`ValueError`</b>:  if the time range are out of bounds of 24H format. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
