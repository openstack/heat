#!/bin/bash

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

# Install prefix for config files (e.g. "/usr/local").
# Leave empty to install into /etc
CONF_PREFIX=""
LOG_DIR=/var/log/heat


install -d $LOG_DIR


archive_file() {
    local f=$1

    if [ -e $CONF_PREFIX/$f ]; then
        echo "Archiving configuration file $CONF_PREFIX/$f" >&2
        mv $CONF_PREFIX/$f $CONF_PREFIX/$f.bak
    fi
}

# Archive existing heat-api* config files in preparation
# for change to heat-api-cfn*, and future use of heat-api*
# for the OpenStack API.
archive_file etc/heat/heat-api.conf
archive_file etc/heat/heat-api-paste.ini


install_dir() {
    local dir=$1
    local prefix=$2

    for fn in $(ls $dir); do
        f=$dir/$fn
        if [ -d $f ]; then
            [ -d $prefix/$f ] || install -d $prefix/$f
            install_dir $f $prefix
        elif [ -f $prefix/$f ]; then
            echo "NOT replacing existing config file $prefix/$f" >&2
            diff -u $prefix/$f $f
        elif [ $fn = 'heat-engine.conf' ]; then
            cat $f | sed s/%ENCRYPTION_KEY%/`hexdump -n 16 -v -e '/1 "%02x"' /dev/random`/ > $prefix/$f
        else

            echo "Installing $fn in $prefix/$dir" >&2
            install -m 664 $f $prefix/$dir
        fi
    done
}

install_dir etc $CONF_PREFIX


./setup.py install >/dev/null
rm -rf build heat.egg-info
