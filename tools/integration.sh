#!/bin/bash

TOOLS_DIR=`dirname $0`
HEAT_DIR="$TOOLS_DIR/.."

clean() {
    $TOOLS_DIR/uninstall-heat -y -r ""
}

error() {
    echo "Failed :("
}

run() {
    bash -c "$($TOOLS_DIR/rst2script.sed $HEAT_DIR/docs/GettingStarted.rst)" || error
}

case $1 in
    clean|run)
        $1
        ;;
    *)
        clean
        run
        ;;
esac
