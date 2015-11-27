#!/bin/bash

if [ $EUID -ne 0 ]; then
    echo "This script must be run as root." >&2
    exit
fi

type -P pip-python &> /dev/null && have_pip_python=1 || have_pip_python=0
if [ $have_pip_python -eq 1 ]; then
    pip-python uninstall -y heat
    exit
fi

type -P pip &> /dev/null && have_pip=1 || have_pip=0
if [ $have_pip -eq 1 ]; then
    pip uninstall -y heat
    exit
fi

echo "pip-python not found. install package (probably python-pip) or run
'easy_install pip', then rerun $0" >&2;
