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

detect_rabbit() {
   PKG_CMD="rpm -q"
   RABBIT_PKG="rabbitmq-server"
   QPID_PKG="qpid-cpp-server"

    # Detect OS type
    # Ubuntu has an lsb_release command which allows us to detect if it is Ubuntu
    if lsb_release -i 2>/dev/null | grep -iq ubuntu
    then
        PKG_CMD="dpkg -s"
        QPID_PKG="qpidd"
    fi
    if $PKG_CMD $RABBIT_PKG > /dev/null 2>&1
    then
        if ! $PKG_CMD $QPID_PKG > /dev/null 2>&1
        then
            return 0
        fi
    fi
    return 1
}

sed_if_rabbit() {
    DEFAULT_RABBIT_PASSWORD="guest"
    conf_path=$1
    if echo $conf_path | grep ".conf$" >/dev/null 2>&1
    then
    if detect_rabbit
        then
            echo "rabbitmq detected, configuring $conf_path for rabbit" >&2
            sed -i "/^rpc_backend\b/ s/impl_qpid/impl_kombu/" $conf_path
            sed -i "/^rpc_backend/a rabbit_password=$DEFAULT_RABBIT_PASSWORD" $conf_path
        fi
    fi
}

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
        else
            echo "Installing $fn in $prefix/$dir" >&2
            install -m 664 $f $prefix/$dir
            if [ $fn = 'heat-engine.conf' ]; then
                sed -i "s/%ENCRYPTION_KEY%/`hexdump -n 16 -v -e '/1 "%02x"' /dev/random`/" $prefix/$f
            fi
            sed_if_rabbit $prefix/$f
        fi
    done
}

install_dir etc $CONF_PREFIX

./setup.py install >/dev/null
rm -rf build heat.egg-info
