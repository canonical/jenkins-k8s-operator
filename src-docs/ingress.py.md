<!-- markdownlint-disable -->

<a href="../src/ingress.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `ingress.py`
Observer module for Jenkins to ingress integration. 



---

## <kbd>class</kbd> `Observer`
The Jenkins Ingress integration observer. 

<a href="../src/ingress.py#L17"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(charm: CharmBase, key: str, relation_name: str)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 
 - <b>`key`</b>:  The ops's Object identifier, to have a unique path for event handling. 
 - <b>`relation_name`</b>:  The ingress relation that this observer is managing. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 



---

<a href="../src/ingress.py#L33"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `get_path`

```python
get_path() → str
```

Return the path in whick Jenkins is expected to be listening. 



**Returns:**
  the path for the ingress URL. 

---

<a href="../src/ingress.py#L46"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `is_ingress_ready`

```python
is_ingress_ready() → str
```

Indicate if the ingress relation is ready. 



**Returns:**
  True if ingress is ready 


