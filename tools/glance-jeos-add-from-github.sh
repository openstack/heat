#!/bin/bash
# Downloads JEOS images from github and installs them in glance

for i in F16-x86_64-cfntools F16-i386-cfntools F17-x86_64-cfntools F17-i386-cfntools F16-x86_64-cfntools-openshift U10-x86_64-cfntools
do
   echo "Downloading and registering $i with OpenStack glance."
glance add name=$i is_public=true disk_format=qcow2 container_format=bare copy_from="http://cloud.github.com/downloads/heat-api/prebuilt-jeos-images/$i.qcow2"
done
