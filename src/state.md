Module src.state
================
Jenkins States.

Classes
-------

`CharmConfigInvalidError(msg: str)`
:   Exception raised when a charm configuration is found to be invalid.
    
    Attrs:
        msg: Explanation of the error.
    
    Initialize a new instance of the CharmConfigInvalidError exception.
    
    Args:
        msg: Explanation of the error.

    ### Ancestors (in MRO)

    * src.state.CharmStateBaseError
    * builtins.Exception
    * builtins.BaseException

`CharmStateBaseError(*args, **kwargs)`
:   Represents error with charm state.

    ### Ancestors (in MRO)

    * builtins.Exception
    * builtins.BaseException

    ### Descendants

    * src.state.CharmConfigInvalidError

`State(update_time_range: Optional[timerange.Range], jenkins_service_name: str = 'jenkins')`
:   The Jenkins k8s operator charm state.
    
    Attrs:
        jenkins_service_name: The Jenkins service name. Note that the container name is the same.
        update_time_range: Time range to allow Jenkins to update version.

    ### Class variables

    `jenkins_service_name: str`
    :

    `update_time_range: Optional[timerange.Range]`
    :

    ### Static methods

    `from_charm(charm: ops.charm.CharmBase) ‑> src.state.State`
    :   Initialize the state from charm.
        
        Args:
            charm: The charm root JenkinsK8SOperatorCharm.
        
        Returns:
            Current state of Jenkins.
        
        Raises:
            CharmConfigInvalidError: if invalid state values were encountered.