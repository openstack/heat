#!/bin/bash

BASE_DIR=`dirname $0`

function usage {
    echo "Usage: $0 [OPTION]..."
    echo "Run Heat's test suite(s)"
    echo ""
    echo "  -V, --virtual-env        Use virtualenv.  Install automatically if not present."
    echo "                           (Default is to run tests in local environment)"
    echo "  -F, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
    echo "  -f, --func               Functional tests have been removed."
    echo "  -u, --unit               Run unit tests (default when nothing specified)"
    echo "  -p, --pep8               Run pep8 tests"
    echo "  --all                    Run pep8 and unit tests"
    echo "  -c, --coverage           Generate coverage report"
    echo "  -d, --debug              Run tests with testtools instead of testr. This allows you to use the debugger."
    echo "  -h, --help               Print this usage message"
    exit
}

# must not assign -a as an option, needed for selecting custom attributes
no_venv=1
function process_option {
    case "$1" in
        -V|--virtual-env) no_venv=0;;
        -F|--force) force=1;;
        -f|--func) test_func=1;;
        -u|--unit) test_unit=1;;
        -p|--pep8) test_pep8=1;;
        --all) test_unit=1; test_pep8=1;;
        -c|--coverage) coverage=1;;
        -d|--debug) debug=1;;
        -h|--help) usage;;
        *) args="$args $1"; test_unit=1;;
    esac
}

venv=.venv
with_venv=tools/with_venv.sh
wrapper=""
debug=0

function run_tests {
    echo 'Running tests'
    # Remove any extraneous DB migrations
    find heat/db/sqlalchemy/migrate_repo/versions/ -name '*.pyc' -delete

    if [ $debug -eq 1 ]; then
      echo "Debugging..."
      if [ "$args" = "" ]; then
        # Default to running all tests if specific test is not
        # provided.
        testrargs="discover ./heat/tests"
      fi
      ${wrapper} python -m testtools.run $args $testrargs

      # Short circuit because all of the testr and coverage stuff
      # below does not make sense when running testtools.run for
      # debugging purposes.
      return $?
    fi

    # Just run the test suites in current environment
    if [ -n "$args" ] ; then
        args="-t $args"
    fi
    python setup.py testr --slowest $args
}

function run_pep8 {
    echo "Running flake8..."
    bash -c "${wrapper} flake8"
}

# run unit tests with pep8 when no arguments are specified
# otherwise process CLI options
if [[ $# == 0 ]]; then
    test_pep8=1
    test_unit=1
else
    for arg in "$@"; do
        process_option $arg
    done
fi

if [ "$no_venv" == 0 ]
then
    # Remove the virtual environment if --force used
    if [ "$force" == 1 ]; then
        echo "Cleaning virtualenv..."
        rm -rf ${venv}
    fi
    if [ -e ${venv} ]; then
        wrapper="${with_venv}"
    else
        # Automatically install the virtualenv
        python tools/install_venv.py
        wrapper="${with_venv}"
    fi
fi

result=0

# If functional or unit tests have been selected, run them
if [ "$test_unit" == 1 ] || [ "$debug" == 1 ] ; then
    run_tests
    result=$?
fi

# Run pep8 if it was selected
if [ "$test_pep8" == 1 ]; then
    run_pep8
fi

# Generate coverage report
if [ "$coverage" == 1 ]; then
    echo "Generating coverage report in ./cover"
    python setup.py testr --coverage --slowest
    python -m coverage report --show-missing
fi

exit $result
