# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#

import util
import nose
from nose.plugins.attrib import attr

from heat.common import context
from heat.engine import manager


@attr(speed='slow')
@attr(tag=['func', 'wordpress', 'eip'])
def test_template():

    template = 'WordPress_Single_Instance_With_EIP.template'

    func_utils = util.FuncUtils()

    func_utils.prepare_jeos('F17', 'x86_64', 'cfntools')
    func_utils.create_stack(template, 'F17')
    func_utils.check_cfntools()
    func_utils.wait_for_provisioning()
    #func_utils.check_user_data(template)

    ssh = func_utils.get_ssh_client()

    # 1. ensure wordpress was installed
    wp_file = '/etc/wordpress/wp-config.php'
    stdin, stdout, sterr = ssh.exec_command('ls ' + wp_file)
    result = stdout.readlines().pop().rstrip()
    assert result == wp_file
    print "Wordpress installation detected"

    # 2. check floating ip assignment
    nclient = func_utils.get_nova_client()
    if len(nclient.floating_ips.list()) == 0:
        print 'zero floating IPs detected'
        assert False
    else:
        found = 0
        mylist = nclient.floating_ips.list()
        for item in mylist:
            if item.instance_id == func_utils.phys_rec_id:
                print 'floating IP found', item.ip
                found = 1
                break
        assert found == 1

    func_utils.cleanup()
