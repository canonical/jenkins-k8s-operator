Module src.timerange
====================
The module for checking time ranges.

Classes
-------

`InvalidTimeRangeError(*args, **kwargs)`
:   Represents an invalid time range.

    ### Ancestors (in MRO)

    * builtins.Exception
    * builtins.BaseException

`Range(**data: Any)`
:   Time range to allow Jenkins to update version.
    
    Attrs:
        start: Hour to allow updates from in UTC time, in 24 hour format.
        end: Hour to allow updates until in UTC time, in 24 hour format.
    
    Create a new model by parsing and validating input data from keyword arguments.
    
    Raises ValidationError if the input data cannot be parsed to form a valid model.

    ### Ancestors (in MRO)

    * pydantic.main.BaseModel
    * pydantic.utils.Representation

    ### Class variables

    `end: int`
    :

    `start: int`
    :

    ### Static methods

    `from_str(time_range: str) ‑> src.timerange.Range`
    :   Instantiate the class from string time range.
        
        Args:
            time_range: The time range string in H(H)-H(H) format, in UTC.
        
        Raises:
            InvalidTimeRangeError: if invalid time range was given.
        
        Returns:
            UpdateTimeRange: if a valid time range was given.

    `validate_range(values: dict) ‑> dict`
    :   Validate the time range.
        
        Args:
            values: The value keys of the model.
        
        Returns:
            A dictionary validated values.
        
        Raises:
            ValueError: if the time range are out of bounds of 24H format.

    ### Methods

    `check_now(self) ‑> bool`
    :   Check whether the current time is within the defined bounds.
        
        Returns:
            True if within bounds, False otherwise.