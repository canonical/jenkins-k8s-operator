<!-- markdownlint-disable -->

<a href="../src/auth_proxy.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `auth_proxy.py`
Observer module for Jenkins to auth_proxy integration. 

**Global Variables**
---------------
- **AUTH_PROXY_ALLOWED_ENDPOINTS**
- **AUTH_PROXY_HEADERS**


---

## <kbd>class</kbd> `Observer`
The Jenkins Auth Proxy integration observer. 

<a href="../src/auth_proxy.py#L25"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(charm: CharmBase, ingress: IngressPerAppRequirer)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  the parent charm to attach the observer to. 
 - <b>`ingress`</b>:  the ingress object from which to extract the necessary settings. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 




