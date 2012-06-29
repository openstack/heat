#!/bin/bash

function usage {
  echo "Usage: $0 [OPTION]..."
  echo "Run Heat's test suite(s)"
  echo ""
  echo "  -V, --virtual-env        Always use virtualenv.  Install automatically if not present"
  echo "  -N, --no-virtual-env     Don't use virtualenv.  Run tests in local environment"
  echo "  -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added."
  echo "  --unittests-only         Run unit tests only."
  echo "  -p, --pep8               Just run pep8"
  echo "  -P, --no-pep8            Don't run static code checks"
  echo "  -c, --coverage           Generate coverage report"
  echo "  -h, --help               Print this usage message"
  echo ""
  echo "Note: with no options specified, the script will try to run the tests in a virtual environment,"
  echo "      If no virtualenv is found, the script will ask if you would like to create one.  If you "
  echo "      prefer to run tests NOT in a virtual environment, simply pass the -N option."
  exit
}

function process_option {
  case "$1" in
    -V|--virtual-env) let always_venv=1; let never_venv=0;;
    -N|--no-virtual-env) let always_venv=0; let never_venv=1;;
    -f|--force) let force=1;;
    --unittests-only) noseargs="$noseargs -a tag=unit";;
    -p|--pep8) let just_pep8=1;;
    -P|--no-pep8) no_pep8=1;;
    -c|--coverage) coverage=1;;
    -h|--help) usage;;
    *) noseargs="$noseargs $1"
  esac
}

venv=.venv
with_venv=tools/with_venv.sh
always_venv=0
never_venv=1
force=0
noseargs=
wrapper=""
just_pep8=0
no_pep8=0
coverage=0

for arg in "$@"; do
  process_option $arg
done

# If enabled, tell nose to collect coverage data
if [ $coverage -eq 1 ]; then
    noseopts="$noseopts --with-coverage --cover-package=heat"
fi

NOSETESTS="python heat/testing/runner.py $noseopts $noseargs"

function run_tests {
  echo 'Running tests'
  # Just run the test suites in current environment
  ${wrapper} $NOSETESTS 2> run_tests.err.log
}

function run_pep8 {
  echo "Running pep8 ..."
  PEP8_OPTIONS="--exclude=$PEP8_EXCLUDE --repeat"
  PEP8_INCLUDE="bin/heat bin/heat-boto bin/heat-api bin/heat-engine heat tools setup.py heat/testing/runner.py"
  ${wrapper} pep8 $PEP8_OPTIONS $PEP8_INCLUDE
}

if [ $never_venv -eq 0 ]
then
  # Remove the virtual environment if --force used
  if [ $force -eq 1 ]; then
    echo "Cleaning virtualenv..."
    rm -rf ${venv}
  fi
  if [ -e ${venv} ]; then
    wrapper="${with_venv}"
  else
    if [ $always_venv -eq 1 ]; then
      # Automatically install the virtualenv
      python tools/install_venv.py
      wrapper="${with_venv}"
    else
      echo -e "No virtual environment found...create one? (Y/n) \c"
      read use_ve
      if [ "x$use_ve" = "xY" -o "x$use_ve" = "x" -o "x$use_ve" = "xy" ]; then
        # Install the virtualenv and run the test suite in it
        python tools/install_venv.py
        wrapper=${with_venv}
      fi
    fi
  fi
fi

# Delete old coverage data from previous runs
if [ $coverage -eq 1 ]; then
    ${wrapper} coverage erase
fi

if [ $just_pep8 -eq 1 ]; then
  run_pep8
  exit
fi

run_tests

# NOTE(sirp): we only want to run pep8 when we're running the full-test suite,
# not when we're running tests individually. To handle this, we need to
# distinguish between options (noseopts), which begin with a '-', and
# arguments (noseargs).
if [ -z "$noseargs" ]; then
  if [ $no_pep8 -eq 0 ]; then
    run_pep8
  fi
fi

if [ $coverage -eq 1 ]; then
    echo "Generating coverage report in covhtml/"
    # Don't compute coverage for common code, which is tested elsewhere
    ${wrapper} coverage html --include='heat/*' --omit='heat/openstack/common/*' -d covhtml -i
fi
