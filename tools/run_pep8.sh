#!/bin/bash

set -e
# This is used by run_tests.sh and tox.ini
python tools/hacking.py --doctest

# Until all these issues get fixed, ignore.
PEP8='python tools/hacking.py --ignore=N101,N201,N202,N301,N302,N303,N304,N305,N306,N401,N402,N403,N404,N702,N703,N801,N902'

EXCLUDE='--exclude=.venv,.git,.tox,dist,doc,*lib/python*'
EXCLUDE+=',*egg,build,*tools*'

# Check all .py files
${PEP8} ${EXCLUDE} .

# Check binaries without py extension
${PEP8} bin/heat-api bin/heat-api-cfn bin/heat-api-cloudwatch bin/heat-cfn bin/heat-engine bin/heat-watch

! python tools/pyflakes-bypass.py heat/ | grep "imported but unused\|redefinition of function"

