<!-- markdownlint-disable -->

<a href="../src/cos.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `cos.py`
Observer module for Jenkins to COS integration. 

**Global Variables**
---------------
- **JENKINS_SCRAPE_JOBS**


---

## <kbd>class</kbd> `Observer`
The Jenkins COS integration observer. 

<a href="../src/cos.py#L63"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>function</kbd> `__init__`

```python
__init__(charm: CharmBase)
```

Initialize the observer and register event handlers. 



**Args:**
 
 - <b>`charm`</b>:  The parent charm to attach the observer to. 


---

#### <kbd>property</kbd> model

Shortcut for more simple access the model. 




---

## <kbd>class</kbd> `PrometheusMetricsJob`
Configuration parameters for prometheus metrics scraping job. 

For more information, see: https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config 

Attrs:  metrics_path: The HTTP resource path on which to fetch metrics from targets.  static_configs: List of labeled statically configured targets for this job. 





---

## <kbd>class</kbd> `PrometheusStaticConfig`
Configuration parameters for prometheus metrics endpoint scraping. 

For more information, see: https://prometheus.io/docs/prometheus/latest/configuration/configuration/#static_config 

Attrs:  targets: list of hosts to scrape, e.g. "*:8080", every unit's port 8080  labels: labels assigned to all metrics scraped from the targets. 





