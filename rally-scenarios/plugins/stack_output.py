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
#    under the License.

from rally import consts
from rally.plugins.openstack import scenario
from rally.plugins.openstack.scenarios.heat import utils
from rally.task import atomic
from rally.task import types
from rally.task import validation


class CustomHeatBenchmark(utils.HeatScenario):
    @atomic.action_timer("heat.show_output_new")
    def _stack_show_output_new(self, stack, output_key):
        """Execute output_show for specified 'output_key'.

        This method uses new output API call.

        :param stack: stack with output_key output.
        :param output_key: The name of the output.
        """
        self.clients("heat").stacks.output_show(stack.id, output_key)

    @atomic.action_timer("heat.show_output_old")
    def _stack_show_output_old(self, stack, output_key):
        """Execute output_show for specified 'output_key'.

        This method uses old way for getting output value.
        It gets whole stack object and then finds necessary 'output_key'.

        :param stack: stack with output_key output.
        :param output_key: The name of the output.
        """
        # this code copy-pasted and adopted for rally from old client version
        # https://github.com/openstack/python-heatclient/blob/0.8.0/heatclient/
        # v1/shell.py#L682-L699
        stack = self.clients("heat").stacks.get(stack_id=stack.id)
        for output in stack.to_dict().get('outputs', []):
            if output['output_key'] == output_key:
                break

    @atomic.action_timer("heat.list_output_new")
    def _stack_list_output_new(self, stack):
        """Execute output_list for specified 'stack'.

        This method uses new output API call.

        :param stack: stack to call output-list.
        """
        self.clients("heat").stacks.output_list(stack.id)

    @atomic.action_timer("heat.list_output_old")
    def _stack_list_output_old(self, stack):
        """Execute output_list for specified 'stack'.

        This method uses old way for getting output value.
        It gets whole stack object and then prints all outputs
        belongs this stack.

        :param stack: stack to call output-list.
        """
        # this code copy-pasted and adopted for rally from old client version
        # https://github.com/openstack/python-heatclient/blob/0.8.0/heatclient/
        # v1/shell.py#L649-L663
        stack = self.clients("heat").stacks.get(stack_id=stack.id)
        stack.to_dict()['outputs']

    @types.set(template_path=types.FileType, files=types.FileTypeDict)
    @validation.required_services(consts.Service.HEAT)
    @validation.required_openstack(users=True)
    @scenario.configure(context={"cleanup": ["heat"]})
    def create_stack_and_show_output_old(self, template_path, output_key,
                                         parameters=None, files=None,
                                         environment=None):
        """Create stack and show output by using old algorithm.

        Measure performance of the following commands:
        heat stack-create
        heat output-show
        heat stack-delete

        :param template_path: path to stack template file
        :param parameters: parameters to use in heat template
        :param files: files used in template
        :param environment: stack environment definition
        """
        stack = self._create_stack(
            template_path, parameters, files, environment)
        self._stack_show_output_old(stack, output_key)

    @types.set(template_path=types.FileType, files=types.FileTypeDict)
    @validation.required_services(consts.Service.HEAT)
    @validation.required_openstack(users=True)
    @scenario.configure(context={"cleanup": ["heat"]})
    def create_stack_and_show_output_new(self, template_path, output_key,
                                         parameters=None, files=None,
                                         environment=None):
        """Create stack and show output by using new algorithm.

        Measure performance of the following commands:
        heat stack-create
        heat output-show
        heat stack-delete

        :param template_path: path to stack template file
        :param output_key: the stack output key that corresponds to
                           the scaling webhook
        :param parameters: parameters to use in heat template
        :param files: files used in template
        :param environment: stack environment definition
        """
        stack = self._create_stack(
            template_path, parameters, files, environment)
        self._stack_show_output_new(stack, output_key)

    @types.set(template_path=types.FileType, files=types.FileTypeDict)
    @validation.required_services(consts.Service.HEAT)
    @validation.required_openstack(users=True)
    @scenario.configure(context={"cleanup": ["heat"]})
    def create_stack_and_list_output_old(self, template_path,
                                         parameters=None, files=None,
                                         environment=None):
        """Create stack and list outputs by using old algorithm.

        Measure performance of the following commands:
        heat stack-create
        heat output-list
        heat stack-delete

        :param template_path: path to stack template file
        :param parameters: parameters to use in heat template
        :param files: files used in template
        :param environment: stack environment definition
        """
        stack = self._create_stack(
            template_path, parameters, files, environment)
        self._stack_list_output_old(stack)

    @types.set(template_path=types.FileType, files=types.FileTypeDict)
    @validation.required_services(consts.Service.HEAT)
    @validation.required_openstack(users=True)
    @scenario.configure(context={"cleanup": ["heat"]})
    def create_stack_and_list_output_new(self, template_path,
                                         parameters=None, files=None,
                                         environment=None):
        """Create stack and list outputs by using new algorithm.

        Measure performance of the following commands:
        heat stack-create
        heat output-list
        heat stack-delete

        :param template_path: path to stack template file
        :param output_key: the stack output key that corresponds to
                           the scaling webhook
        :param parameters: parameters to use in heat template
        :param files: files used in template
        :param environment: stack environment definition
        """
        stack = self._create_stack(
            template_path, parameters, files, environment)
        self._stack_list_output_new(stack)
