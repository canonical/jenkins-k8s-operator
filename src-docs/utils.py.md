<!-- markdownlint-disable -->

<a href="../src/utils.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `utils.py`
A collection of utility functions that are used in the charm. 


---

<a href="../src/utils.py#L12"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `generate_random_password`

```python
generate_random_password(length: int) → str
```

Randomly generate a string intended to be used as a password. 



**Args:**
 
 - <b>`length`</b>:  length of the randomly generated string to be returned 

**Returns:**
 A randomly generated string intended to be used as a password. 


---

<a href="../src/utils.py#L24"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `generate_random_hash`

```python
generate_random_hash() → str
```

Generate a hash based on a random string. 



**Returns:**
  A hash based on a random string. 


---

<a href="../src/utils.py#L34"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `split_mem`

```python
split_mem(mem_str) → tuple
```

Split a memory string into a number and a unit. 



**Args:**
 
 - <b>`mem_str`</b>:  a string representing a memory value, e.g. "1Gi" 


---

<a href="../src/utils.py#L47"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `any_memory_to_bytes`

```python
any_memory_to_bytes(mem_str) → int
```

Convert a memory string to bytes. 



**Args:**
 
 - <b>`mem_str`</b>:  a string representing a memory value, e.g. "1Gi" 


---

<a href="../src/utils.py#L76"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `compare_dictionaries`

```python
compare_dictionaries(dict1: dict, dict2: dict) → set
```

Compare two dictionaries and return a set of keys that are different. 


