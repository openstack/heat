#!/usr/bin/python

import gettext
import sys
import os.path
import json

possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'heat', '__init__.py')):
    sys.path.insert(0, possible_topdir)

gettext.install('heat', unicode=1)

from heat.engine import parser

parameter_count = 1


def setparam(t, key, value):
    global parameter_count
    key_name = 'Parameters.member.%d.ParameterKey' % parameter_count
    value_name = 'Parameters.member.%d.ParameterValue' % parameter_count

    t[key_name] = key
    t[value_name] = value
    parameter_count += 1


filename = sys.argv[1]
with open(filename) as f:
    json_blob = json.load(f)

    (stack_name, tmp) = os.path.splitext(os.path.basename(filename))

    params_dict = {}
    setparam(params_dict, 'AWS::StackName', stack_name)

# Don't immediately see a way to have key name as a parameter and also
# file injection and monitoring
# need to insert key on creation and know what private key is
    setparam(params_dict, 'KeyName', 'sdake_key')
    # ^ that gets inserted into image

    setparam(params_dict, 'AWS::StackName', stack_name)
    setparam(params_dict, 'InstanceType', 'm1.xlarge')
    setparam(params_dict, 'DBUsername', 'eddie.jones')
    setparam(params_dict, 'DBPassword', 'adm1n')
    setparam(params_dict, 'DBRootPassword', 'admone')
    setparam(params_dict, 'LinuxDistribution', 'F16')

    # set the keystone auth environs up
    username = os.environ['OS_USERNAME']
    password = os.environ['OS_PASSWORD']
    tenant = os.environ['OS_TENANT_NAME']
    auth_url = os.environ['OS_AUTH_URL']

    params_dict['KeyStoneCreds'] = dict(username=username,
                                        password=password,
                                        tenant=tenant,
                                        auth_url=auth_url,
                                        strategy='keystone')

    stack = parser.Stack(stack_name, json_blob, params_dict)
    stack.start()
