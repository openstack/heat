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
#    under the License.

"""
Client implementation based on the boto AWS client library
"""

from heat.openstack.common import log as logging
logger = logging.getLogger(__name__)

from boto.cloudformation import CloudFormationConnection


class BotoClient(CloudFormationConnection):

    def list_stacks(self, **kwargs):
        return super(BotoClient, self).list_stacks()

    def describe_stacks(self, **kwargs):
        try:
            stack_name = kwargs['StackName']
        except KeyError:
            stack_name = None
        return super(BotoClient, self).describe_stacks(stack_name)

    def create_stack(self, **kwargs):
        if 'TemplateUrl' in kwargs:
            return super(BotoClient, self).create_stack(kwargs['StackName'],
                                     template_url=kwargs['TemplateUrl'],
                                     parameters=kwargs['Parameters'])
        elif 'TemplateBody' in kwargs:
            return super(BotoClient, self).create_stack(kwargs['StackName'],
                                     template_body=kwargs['TemplateBody'],
                                     parameters=kwargs['Parameters'])
        else:
            logger.error("Must specify TemplateUrl or TemplateBody!")

    def update_stack(self, **kwargs):
        if 'TemplateUrl' in kwargs:
            return super(BotoClient, self).update_stack(kwargs['StackName'],
                                     template_url=kwargs['TemplateUrl'],
                                     parameters=kwargs['Parameters'])
        elif 'TemplateBody' in kwargs:
            return super(BotoClient, self).update_stack(kwargs['StackName'],
                                     template_body=kwargs['TemplateBody'],
                                     parameters=kwargs['Parameters'])
        else:
            logger.error("Must specify TemplateUrl or TemplateBody!")

    def delete_stack(self, **kwargs):
        return super(BotoClient, self).delete_stack(kwargs['StackName'])

    def list_stack_events(self, **kwargs):
        return super(BotoClient, self).describe_stack_events(
                     kwargs['StackName'])

    def describe_stack_resource(self, **kwargs):
        return super(BotoClient, self).describe_stack_resource(
                     kwargs['StackName'], kwargs['LogicalResourceId'])

    def describe_stack_resources(self, **kwargs):
        # Check if this is a StackName, if not assume it's a physical res ID
        # Note this is slower for the common case, which is probably StackName
        # than just doing a try/catch over the StackName case then retrying
        # on failure with kwargs['NameOrPid'] as the physical resource ID,
        # however boto spews errors when raising an exception so we can't
        list_stacks = self.list_stacks()
        stack_names = [s.stack_name for s in list_stacks]
        if kwargs['NameOrPid'] in stack_names:
            logger.debug("Looking up resources for StackName:%s" %
                          kwargs['NameOrPid'])
            return super(BotoClient, self).describe_stack_resources(
                         stack_name_or_id=kwargs['NameOrPid'],
                         logical_resource_id=kwargs['LogicalResourceId'])
        else:
            logger.debug("Looking up resources for PhysicalResourceId:%s" %
                          kwargs['NameOrPid'])
            return super(BotoClient, self).describe_stack_resources(
                         stack_name_or_id=None,
                         logical_resource_id=kwargs['LogicalResourceId'],
                         physical_resource_id=kwargs['NameOrPid'])

    def list_stack_resources(self, **kwargs):
        return super(BotoClient, self).list_stack_resources(
                     kwargs['StackName'])

    def validate_template(self, **kwargs):
        if 'TemplateUrl' in kwargs:
            return super(BotoClient, self).validate_template(
                         template_url=kwargs['TemplateUrl'])
        elif 'TemplateBody' in kwargs:
            return super(BotoClient, self).validate_template(
                         template_body=kwargs['TemplateBody'])
        else:
            logger.error("Must specify TemplateUrl or TemplateBody!")

    def get_template(self, **kwargs):
        return super(BotoClient, self).get_template(kwargs['StackName'])

    def estimate_template_cost(self, **kwargs):
        if 'TemplateUrl' in kwargs:
            return super(BotoClient, self).estimate_template_cost(
                         kwargs['StackName'],
                         template_url=kwargs['TemplateUrl'],
                         parameters=kwargs['Parameters'])
        elif 'TemplateBody' in kwargs:
            return super(BotoClient, self).estimate_template_cost(
                         kwargs['StackName'],
                         template_body=kwargs['TemplateBody'],
                         parameters=kwargs['Parameters'])
        else:
            logger.error("Must specify TemplateUrl or TemplateBody!")

    def format_stack_event(self, events):
        '''
        Return string formatted representation of
        boto.cloudformation.stack.StackEvent objects
        '''
        ret = []
        for event in events:
            ret.append("EventId : %s" % event.event_id)
            ret.append("LogicalResourceId : %s" % event.logical_resource_id)
            ret.append("PhysicalResourceId : %s" % event.physical_resource_id)
            ret.append("ResourceProperties : %s" % event.resource_properties)
            ret.append("ResourceStatus : %s" % event.resource_status)
            ret.append("ResourceStatusReason : %s" %
                        event.resource_status_reason)
            ret.append("ResourceType : %s" % event.resource_type)
            ret.append("StackId : %s" % event.stack_id)
            ret.append("StackName : %s" % event.stack_name)
            ret.append("Timestamp : %s" % event.timestamp)
            ret.append("--")
        return '\n'.join(ret)

    def format_stack(self, stacks):
        '''
        Return string formatted representation of
        boto.cloudformation.stack.Stack objects
        '''
        ret = []
        for s in stacks:
            ret.append("Capabilities : %s" % s.capabilities)
            ret.append("CreationTime : %s" % s.creation_time)
            ret.append("Description : %s" % s.description)
            ret.append("DisableRollback : %s" % s.disable_rollback)
            ret.append("NotificationARNs : %s" % s.notification_arns)
            ret.append("Outputs : %s" % s.outputs)
            ret.append("Parameters : %s" % s.parameters)
            ret.append("StackId : %s" % s.stack_id)
            ret.append("StackName : %s" % s.stack_name)
            ret.append("StackStatus : %s" % s.stack_status)
            ret.append("StackStatusReason : %s" % s.stack_status_reason)
            ret.append("TimeoutInMinutes : %s" % s.timeout_in_minutes)
            ret.append("--")
        return '\n'.join(ret)

    def format_stack_resource(self, resources):
        '''
        Return string formatted representation of
        boto.cloudformation.stack.StackResource objects
        '''
        ret = []
        for res in resources:
            ret.append("LogicalResourceId : %s" % res.logical_resource_id)
            ret.append("PhysicalResourceId : %s" % res.physical_resource_id)
            ret.append("ResourceStatus : %s" % res.resource_status)
            ret.append("ResourceStatusReason : %s" %
                        res.resource_status_reason)
            ret.append("ResourceType : %s" % res.resource_type)
            ret.append("StackId : %s" % res.stack_id)
            ret.append("StackName : %s" % res.stack_name)
            ret.append("Timestamp : %s" % res.timestamp)
            ret.append("--")
        return '\n'.join(ret)

    def format_stack_resource_summary(self, resources):
        '''
        Return string formatted representation of
        boto.cloudformation.stack.StackResourceSummary objects
        '''
        ret = []
        for res in resources:
            ret.append("LastUpdatedTimestamp : %s" %
                        res.last_updated_timestamp)
            ret.append("LogicalResourceId : %s" % res.logical_resource_id)
            ret.append("PhysicalResourceId : %s" % res.physical_resource_id)
            ret.append("ResourceStatus : %s" % res.resource_status)
            ret.append("ResourceStatusReason : %s" %
                        res.resource_status_reason)
            ret.append("ResourceType : %s" % res.resource_type)
            ret.append("--")
        return '\n'.join(ret)

    def format_stack_summary(self, summaries):
        '''
        Return string formatted representation of
        boto.cloudformation.stack.StackSummary objects
        '''
        ret = []
        for s in summaries:
            ret.append("StackId : %s" % s.stack_id)
            ret.append("StackName : %s" % s.stack_name)
            ret.append("CreationTime : %s" % s.creation_time)
            ret.append("StackStatus : %s" % s.stack_status)
            ret.append("TemplateDescription : %s" % s.template_description)
            ret.append("--")
        return '\n'.join(ret)

    def format_template(self, template):
        '''
        String formatted representation of
        boto.cloudformation.template.Template object
        '''
        ret = []
        ret.append("Description : %s" % template.description)
        for p in template.template_parameters:
            ret.append("Parameter : ")
            ret.append("  NoEcho : %s" % p.no_echo)
            ret.append("  Description : %s" % p.description)
            ret.append("  ParameterKey : %s" % p.parameter_key)
        ret.append("--")
        return '\n'.join(ret)

    def format_parameters(self, options):
        '''
        Returns a dict containing list-of-tuple format
        as expected by boto for request parameters
        '''
        parameters = {}
        params = []
        if options.parameters:
            for p in options.parameters.split(';'):
                (n, v) = p.split('=')
                params.append((n, v))
        parameters['Parameters'] = params
        return parameters


def get_client(host, port=None, username=None,
               password=None, tenant=None,
               auth_url=None, auth_strategy=None,
               auth_token=None, region=None,
               is_silent_upload=False, insecure=True):

    """
    Returns a new boto client object to a heat server
    """

    # Note we pass None/None for the keys so boto reads /etc/boto.cfg
    # Also note is_secure is defaulted to False as HTTPS connections
    # don't seem to work atm, FIXME
    cloudformation = BotoClient(aws_access_key_id=None,
        aws_secret_access_key=None, is_secure=False,
        port=port, path="/v1")
    if cloudformation:
        logger.debug("Got CF connection object OK")
    else:
        logger.error("Error establishing connection!")
        sys.exit(1)

    return cloudformation
