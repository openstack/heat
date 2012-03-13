# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
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
Middleware that attaches a context to the WSGI request
"""

from heat.common import utils
from heat.common import wsgi
from heat.common import context


class ContextMiddleware(wsgi.Middleware):
    def __init__(self, app, options):
        self.options = options
        super(ContextMiddleware, self).__init__(app)

    def make_context(self, *args, **kwargs):
        """
        Create a context with the given arguments.
        """

        # Determine the context class to use
        ctxcls = context.RequestContext
        if 'context_class' in self.options:
            ctxcls = utils.import_class(self.options['context_class'])

        return ctxcls(*args, **kwargs)

    def process_request(self, req):
        """
        Extract any authentication information in the request and
        construct an appropriate context from it.
        """
        # Use the default empty context, with admin turned on for
        # backwards compatibility
        req.context = self.make_context(is_admin=True)


def filter_factory(global_conf, **local_conf):
    """
    Factory method for paste.deploy
    """
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return ContextMiddleware(app, conf)

    return filter
