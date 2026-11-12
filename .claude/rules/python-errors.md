---
description: Python error-handling rules (exceptions, failure reporting, sentinels, conditions) with bad and good examples.
paths:
  - "**/*.py"
---
<!-- master: ai-code-review/rules/python-errors.md; do not edit generated copies @ bbac8b79329a -->

## Catch specific exceptions
Ctrl-C and sys.exit() arrive as exceptions too; a bare `except:` eats them, and any broad catch buries real bugs such as a NameError.
```python
# bad
try:
    port = int(env["PORT"])
except:
    port = DEFAULT_PORT
```
```python
# good
try:
    port = int(env["PORT"])
except (KeyError, ValueError):
    port = DEFAULT_PORT
```
<!-- src: course -->

## Handle ValueError at the default JSON decoder boundary
`json.JSONDecodeError` subclasses `ValueError`. In this default `json.loads` example, the leading-U+FEFF `str` raises `JSONDecodeError`; with Python's default 4,300-digit limit, the 10,000-digit integer raises plain `ValueError`. Catch `ValueError` around this call alone and report rejection through the defined `InvalidJSON` error.

Both examples use these inputs and error type:
```python
import json

class InvalidJSON(ValueError):
    pass

bom_text = '\ufeff{"quantity":1}'
huge_integer = '{"quantity":' + "9" * 10_000 + "}"
```
```python
# bad: huge_integer escapes as plain ValueError
def decode_document(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidJSON("Invalid JSON document.") from exc
```
```python
# good: both inputs raise InvalidJSON with the decoder error as the cause
def decode_document(raw: str):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise InvalidJSON("Invalid JSON document.") from exc

def process_document(raw: str, validate_document):
    data = decode_document(raw)
    validate_document(data)  # Downstream ValueError and TypeError propagate.
    return data
```
In this example, return decoded data unchanged and validate outside the decoder's try block; preserve omitted keys, null, false, zero and empty values. Leave the default digit limit and BOM rejection intact for these fixtures. UTF-8 BOM bytes are accepted by `json.loads`; the failing fixture is a `str`.

When adapting this pattern, preserve existing intentional BOM normalization, custom decoder hooks, numeric policies and caller-visible error contracts. Distinguish hook and validator failures from default decoder failures; do not relabel them as `InvalidJSON`.
<!-- src: review miss, JSON decoder ValueError -->

## Return or raise, never print, to report failure
Console output is invisible to the calling code, which carries on as if the call had worked.
```python
# bad
def withdraw(account, amount):
    if amount > account.balance:
        print("Insufficient funds")
        return
    account.balance -= amount
```
```python
# good
def withdraw(account, amount):
    if amount > account.balance:
        raise InsufficientFunds(account.id, amount)
    account.balance -= amount
```
<!-- src: course, catalog D14 -->

## Do not return error sentinels
An error string, None or -1 travels on as data until something far away crashes or computes garbage.
```python
# bad
def parse_quantity(text):
    if not text.isdigit():
        return "invalid quantity"
    return int(text)
subtotal = unit_price * parse_quantity(raw)  # 3 * "invalid quantity" is a string
```
```python
# good
def parse_quantity(text):
    if not text.isdigit():
        raise ValueError(f"invalid quantity: {text!r}")
    return int(text)
```
<!-- src: catalog D10 -->

## Test the condition you mean, not truthiness
Zero, an empty string and an empty list are falsy, so a bare truthiness test treats real values as missing; spell out the condition.
```python
# bad
def set_volume(level=None):
    if level:
        mixer.volume = level  # level 0 (mute) is ignored
```
```python
# good
def set_volume(level=None):
    if level is not None:
        mixer.volume = level
```
<!-- src: course -->
