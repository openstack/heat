#!/bin/sed -nrf

# Skip over the ".." line that starts a comment block.
/^\.{2}[[:space:]]*$/ n

# Loop through the block until a non-indented line is found.
# Append indented lines to the hold space.
: indent
/^ {4}/ {
    s/^ {4}//
    H
    $ b endblock
    n
    b indent
}

# Loop through to the end of the block.
# Clear the hold space if unindented lines are present.
:nonindent
/^[[:space:]]*$/! {
    x
    s/.*//
    x
    $ d
    n
    b nonindent
}

# Print the contents of the hold space (if any) and clear it.
: endblock
s/.*//
x
s/^\n//
/./ {
p
a \

}
