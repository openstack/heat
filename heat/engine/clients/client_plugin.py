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

import abc
import functools
import sys
import weakref

from keystoneclient import auth
from keystoneclient.auth.identity import v2
from keystoneclient.auth.identity import v3
from keystoneclient import exceptions
from keystoneclient import session
from oslo_config import cfg
import six

from heat.common.i18n import _


class ExceptionFilter(object):
    """A context manager that prevents some exceptions from being raised.

    For backwards compatibility, these objects can also be called with the
    exception value as an argument - any non-matching exception will be
    re-raised from this call. We attempt but cannot guarantee to keep the same
    traceback; the context manager method is preferred for this reason except
    in cases where the ignored exception affects control flow.

    Use this class as a decorator for a function that returns whether a given
    exception should be ignored. e.g.

    >>> @ExceptionFilter
    >>> def ignore_assertions(ex):
    ...     return isinstance(ex, AssertionError)

    and then use it as a context manager:

    >>> with ignore_assertions:
    ...     assert False

    or call it:

    >>> try:
    ...     assert False
    ... except Exception as ex:
    ...     ignore_assertions(ex)
    """

    def __init__(self, should_ignore_ex):
        self._should_ignore_ex = should_ignore_ex
        functools.update_wrapper(self, should_ignore_ex)

    def __get__(self, obj, owner=None):
        return type(self)(six.create_bound_method(self._should_ignore_ex, obj))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None:
            return self._should_ignore_ex(exc_val)

    def __call__(self, ex):
        """Re-raise any exception value not being filtered out.

        If the exception was the last to be raised, it will be re-raised with
        its original traceback.
        """
        if not self._should_ignore_ex(ex):
            exc_type, exc_val, traceback = sys.exc_info()
            if exc_val is ex:
                six.reraise(exc_type, exc_val, traceback)
            else:
                raise ex


@six.add_metaclass(abc.ABCMeta)
class ClientPlugin(object):

    # Module which contains all exceptions classes which the client
    # may emit
    exceptions_module = None

    # supported service types, service like cinder support multiple service
    # types, so its used in list format
    service_types = []

    def __init__(self, context):
        self._context = weakref.ref(context)
        self._clients = weakref.ref(context.clients)
        self._client = None
        self._keystone_session_obj = None

    @property
    def context(self):
        ctxt = self._context()
        assert ctxt is not None, "Need a reference to the context"
        return ctxt

    @property
    def clients(self):
        return self._clients()

    @property
    def _keystone_session(self):
        # FIXME(jamielennox): This session object is essentially static as the
        # options won't change. Further it is allowed to be shared by multiple
        # authentication requests so there is no reason to construct it fresh
        # for every client plugin. It should be global and shared amongst them.
        if not self._keystone_session_obj:
            o = {'cacert': self._get_client_option('keystone', 'ca_file'),
                 'insecure': self._get_client_option('keystone', 'insecure'),
                 'cert': self._get_client_option('keystone', 'cert_file'),
                 'key': self._get_client_option('keystone', 'key_file')}

            self._keystone_session_obj = session.Session.construct(o)

        return self._keystone_session_obj

    def client(self):
        if not self._client:
            self._client = self._create()
        return self._client

    @abc.abstractmethod
    def _create(self):
        """Return a newly created client."""
        pass

    @property
    def auth_token(self):
        # NOTE(jamielennox): use the session defined by the keystoneclient
        # options as traditionally the token was always retrieved from
        # keystoneclient.
        return self.context.auth_plugin.get_token(self._keystone_session)

    def url_for(self, **kwargs):
        def get_endpoint():
            auth_plugin = self.context.auth_plugin
            return auth_plugin.get_endpoint(self._keystone_session, **kwargs)

        # NOTE(jamielennox): use the session defined by the keystoneclient
        # options as traditionally the token was always retrieved from
        # keystoneclient.
        try:
            kwargs.setdefault('interface', kwargs.pop('endpoint_type'))
        except KeyError:
            pass

        reg = self.context.region_name or cfg.CONF.region_name_for_services
        kwargs.setdefault('region_name', reg)
        url = None
        try:
            url = get_endpoint()
        except exceptions.EmptyCatalog:
            kc = self.clients.client('keystone').client

            auth_plugin = self.context.auth_plugin
            endpoint = auth_plugin.get_endpoint(None,
                                                interface=auth.AUTH_INTERFACE)
            token = auth_plugin.get_token(None)
            project_id = auth_plugin.get_project_id(None)

            if kc.version == 'v3':
                token_obj = v3.Token(endpoint, token, project_id=project_id)
                catalog_key = 'catalog'
                access_key = 'token'
            elif kc.version == 'v2.0':
                endpoint = endpoint.replace('v3', 'v2.0')
                token_obj = v2.Token(endpoint, token, tenant_id=project_id)
                catalog_key = 'serviceCatalog'
                access_key = 'access'
            else:
                raise exceptions.Error(_("Unknown Keystone version"))

            auth_ref = token_obj.get_auth_ref(self._keystone_session)

            if catalog_key in auth_ref:
                access_info = self.context.auth_token_info[access_key]
                access_info[catalog_key] = auth_ref[catalog_key]
                self.context.reload_auth_plugin()
                url = get_endpoint()

        # NOTE(jamielennox): raising exception maintains compatibility with
        # older keystoneclient service catalog searching.
        if url is None:
            raise exceptions.EndpointNotFound()

        return url

    def _get_client_option(self, client, option):
        # look for the option in the [clients_${client}] section
        # unknown options raise cfg.NoSuchOptError
        try:
            group_name = 'clients_' + client
            cfg.CONF.import_opt(option, 'heat.common.config',
                                group=group_name)
            v = getattr(getattr(cfg.CONF, group_name), option)
            if v is not None:
                return v
        except cfg.NoSuchGroupError:
            pass  # do not error if the client is unknown
        # look for the option in the generic [clients] section
        cfg.CONF.import_opt(option, 'heat.common.config', group='clients')
        return getattr(cfg.CONF.clients, option)

    def is_client_exception(self, ex):
        """Returns True if the current exception comes from the client."""
        if self.exceptions_module:
            if isinstance(self.exceptions_module, list):
                for m in self.exceptions_module:
                    if type(ex) in six.itervalues(m.__dict__):
                        return True
            else:
                return type(ex) in six.itervalues(
                    self.exceptions_module.__dict__)
        return False

    def is_not_found(self, ex):
        """Returns True if the exception is a not-found."""
        return False

    def is_over_limit(self, ex):
        """Returns True if the exception is an over-limit."""
        return False

    def is_conflict(self, ex):
        """Returns True if the exception is a conflict."""
        return False

    @ExceptionFilter
    def ignore_not_found(self, ex):
        """Raises the exception unless it is a not-found."""
        return self.is_not_found(ex)

    @ExceptionFilter
    def ignore_conflict_and_not_found(self, ex):
        """Raises the exception unless it is a conflict or not-found."""
        return self.is_conflict(ex) or self.is_not_found(ex)

    def _get_client_args(self,
                         service_name,
                         service_type):
        endpoint_type = self._get_client_option(service_name,
                                                'endpoint_type')
        endpoint = self.url_for(service_type=service_type,
                                endpoint_type=endpoint_type)
        args = {
            'auth_url': self.context.auth_url,
            'service_type': service_type,
            'project_id': self.context.tenant_id,
            'token': lambda: self.auth_token,
            'endpoint_type': endpoint_type,
            'os_endpoint': endpoint,
            'cacert': self._get_client_option(service_name, 'ca_file'),
            'cert_file': self._get_client_option(service_name, 'cert_file'),
            'key_file': self._get_client_option(service_name, 'key_file'),
            'insecure': self._get_client_option(service_name, 'insecure')
        }

        return args
        # FIXME(kanagaraj-manickam) Update other client plugins to leverage
        # this method (bug 1461041)

    def does_endpoint_exist(self,
                            service_type,
                            service_name):
        endpoint_type = self._get_client_option(service_name,
                                                'endpoint_type')
        try:
            self.url_for(service_type=service_type,
                         endpoint_type=endpoint_type)
            return True
        except exceptions.EndpointNotFound:
            return False
