Module src.agent
================
The Jenkins agent relation observer.

Classes
-------

`AgentRelationData(*args, **kwargs)`
:   Relation data required for adding the Jenkins agent.
    
    Attrs:
        url: The Jenkins server url.
        secret: The secret for agent node.

    ### Ancestors (in MRO)

    * builtins.dict

    ### Class variables

    `secret: str`
    :

    `url: str`
    :

`Observer(charm: ops.charm.CharmBase, state: state.State)`
:   The Jenkins agent relation observer.
    
    Initialize the observer and register event handlers.
    
    Args:
        charm: The parent charm to attach the observer to.
        state: The charm state.

    ### Ancestors (in MRO)

    * ops.framework.Object