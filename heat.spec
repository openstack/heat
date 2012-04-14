%{!?python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")}

Name: heat
Summary: The Heat project
Version: 0.0.1
Release: 1
License: ASL 2.0
Prefix: %{_prefix}
Group: System Environment/Base
URL: http://www.heat-project.org
Source0: http://heat-project.org/downloads/%{name}-%{version}/%{name}-%{version}.tar.gz

Requires: pacemaker-cloud

BuildArch: noarch
BuildRequires: python-glance

BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot

%prep
%setup -q -n %{name}-%{version}

%build
python setup.py build

%install
python setup.py install -O1 --root=$RPM_BUILD_ROOT --record=INSTALLED_FILES
mkdir -p $RPM_BUILD_ROOT/var/log/heat/
mkdir -p $RPM_BUILD_ROOT/var/lib/heat/
mkdir -p $RPM_BUILD_ROOT/etc/heat/
cp etc/* $RPM_BUILD_ROOT/etc/heat/
mkdir -p $RPM_BUILD_ROOT/%{_mandir}/man1/ 
cp -v docs/man/man1/heat.1 $RPM_BUILD_ROOT/%{_mandir}/man1/
rm -rf $RPM_BUILD_ROOT/var/lib/heat/.dummy
rm -rf $RPM_BUILD_ROOT/%{python_sitelib}/heat/vcsversion.*
rm -rf $RPM_BUILD_ROOT/%{python_sitelib}/heat/tests
rm -rf $RPM_BUILD_ROOT/%{python_sitelib}/heat-0.0.1-py2.7.egg-info

%clean
rm -rf $RPM_BUILD_ROOT

%description
Heat provides a programmable interface to orchestrate the setup of multiple cloud applications

%package api
License: ASL 2.0
Summary: External API for the Heat project
Group: System Environment/Base
Requires: %{name} = %{version}-%{release}

%description api
This package contains the external api for the Heat project

%package common 
License: ASL 2.0
Summary: Common utilities for the Heat project
Group: System Environment/Base
Requires: %{name} = %{version}-%{release}

%description common 
This package contains the common utilities for the Heat project

%package engine 
License: ASL 2.0
Summary: Engine for the Heat project
Group: System Environment/Base
Requires: %{name} = %{version}-%{release}

%description engine 
This package contains the engine and internal API for the Heat project

%package jeos 
License: ASL 2.0
Summary: JEOS configuration files for the Heat project
Group: System Environment/Base
Requires: %{name} = %{version}-%{release}

%description jeos 
This package contains the Just Enough OS configuration files supported by the Heat project

%package openstack 
License: ASL 2.0
Summary: OpenStack integration for the Heat project
Group: System Environment/Base
Requires: %{name} = %{version}-%{release}

%description openstack
This package contains the OpenStack integration for the Heat project


%files
%doc README.rst
%defattr(-,root,root,-)
%{_mandir}/man1/*.gz
%{_bindir}/heat
%{_bindir}/heat-db-setup-fedora
%{python_sitelib}/heat/db/*
%{python_sitelib}/heat/__init__.*
%{python_sitelib}/heat/client.*
%{python_sitelib}/heat/cloudformations.*
%{python_sitelib}/heat/version.*
%config(noreplace) /etc/heat

%files api
%defattr(-,root,root,-)
%{_bindir}/heat-api
%{python_sitelib}/heat/api/__init__.*
%{python_sitelib}/heat/api/versions.*
%{python_sitelib}/heat/api/middleware/__init__.*
%{python_sitelib}/heat/api/middleware/version_negotiation.*
%{python_sitelib}/heat/api/middleware/context.*
%{python_sitelib}/heat/api/v1/__init__.*
%{python_sitelib}/heat/api/v1/stacks.*
%{_localstatedir}/log/heat/api.log

%files common
%defattr(-,root,root,-)
%{python_sitelib}/heat/common/auth.*
%{python_sitelib}/heat/common/client.*
%{python_sitelib}/heat/common/config.*
%{python_sitelib}/heat/common/context.*
%{python_sitelib}/heat/common/crypt.*
%{python_sitelib}/heat/common/exception.*
%{python_sitelib}/heat/common/__init__.*
%{python_sitelib}/heat/common/policy.*
%{python_sitelib}/heat/common/utils.*
%{python_sitelib}/heat/common/wsgi.*

%files engine
%defattr(-,root,root,-)
%{_bindir}/heat-engine
%{python_sitelib}/heat/engine/*
%{python_sitelib}/heat/openstack/*
%{python_sitelib}/heat/cfntools/*
%{python_sitelib}/heat/cloudinit/*
%{python_sitelib}/heat/rpc/*
%{python_sitelib}/heat/context.*
%{python_sitelib}/heat/manager.*
%{python_sitelib}/heat/service.*
%{_localstatedir}/log/heat/engine.log

%files jeos
%defattr(-,root,root,-)
%{python_sitelib}/heat/jeos/F16-x86_64-gold-jeos.tdl
%{python_sitelib}/heat/jeos/F16-i386-gold-jeos.tdl
%{python_sitelib}/heat/jeos/F17-x86_64-gold-jeos.tdl
%{python_sitelib}/heat/jeos/F17-i386-gold-jeos.tdl
%{python_sitelib}/heat/jeos/F16-x86_64-cfntools-jeos.tdl
%{python_sitelib}/heat/jeos/F16-i386-cfntools-jeos.tdl
%{python_sitelib}/heat/jeos/F17-x86_64-cfntools-jeos.tdl
%{python_sitelib}/heat/jeos/F17-i386-cfntools-jeos.tdl

%files openstack
%defattr(-,root,root,-)
%{python_sitelib}/heat/openstack/__init__.*
%{python_sitelib}/heat/openstack/common/cfg.*
%{python_sitelib}/heat/openstack/common/__init__.*
