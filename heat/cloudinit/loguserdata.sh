#!/bin/bash
chmod +x /var/lib/cloud/data/cfn-userdata
script -f -c /var/lib/cloud/data/cfn-userdata /var/log/heat-provision.log
