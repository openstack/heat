#!/bin/sh

mkdir -p /var/log/heat
mkdir -p /etc/heat

pushd etc
for f in *
do
    if [ -d $f ] ; then
        #ignore
        s=0
    elif [ -f $f ] ; then
        echo not coping over /etc/heat/$f
        diff -u /etc/heat/$f $f
    else
        cp $f /etc/heat/
    fi
done
popd

./setup.py install --root=/ >/dev/null
rm -rf build heat.egg-info

