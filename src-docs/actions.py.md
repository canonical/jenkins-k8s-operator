<!-- markdownlint-disable -->

<a href="../src/actions.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `actions.py`
Jenkins charm actions. 



---

## <kbd>class</kbd> `Observer`
Jenkins-k8s charm actions observer. 

<a href="../src/actions.py#L15"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(charm: CharmBase, state: State)
```

Initialize the observer and register actions handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 
 - <b>`state`</b>:  The Jenkins charm state. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 



---

<a href="../src/actions.py#L32"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `on_get_admin_password`

```python
on_get_admin_password(event: ActionEvent) → None
```

Handle get-admin-password event. 



**Args:**
 
 - <b>`event`</b>:  The event fired from get-admin-password action. 

---

<a href="../src/actions.py#L42"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `on_rotate_credentials`

```python
on_rotate_credentials(event: ActionEvent) → None
```

Invalidate all sessions and reset admin account password. 



**Args:**
 
 - <b>`event`</b>:  The rotate credentials event. 


