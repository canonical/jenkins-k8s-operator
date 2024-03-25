<!-- markdownlint-disable -->

<a href="../src/pebble.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `pebble.py`
Pebble functionality. 

**Global Variables**
---------------
- **JENKINS_SERVICE_NAME**

---

<a href="../src/pebble.py#L20"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `replan_jenkins`

```python
replan_jenkins(
    container: Container,
    jenkins_instance: Jenkins,
    state: State
) → None
```

Replan the jenkins services. 



**Args:**
 
 - <b>`container`</b>:  the container for with to replan the services. 
 - <b>`jenkins_instance`</b>:  the Jenkins instance. 
 - <b>`state`</b>:  the charm state. 



**Raises:**
 
 - <b>`JenkinsBootstrapError`</b>:  if an error occurs while bootstrapping Jenkins. 


