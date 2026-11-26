Closes #7. The welcome page showed "Hello,Ana": `greet()` left out the space after the comma. It now returns "Hello, Ana".

## Tests
`tests/test_greet.py::test_greet_puts_a_space_after_the_comma` is new; it failed before the fix and passes after it (`pytest`: 1 passed).
