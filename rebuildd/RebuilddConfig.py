# rebuildd - Debian packages rebuild tool
#
# (c) 2007 - Julien Danjou <acid@debian.org>
#
#   This software is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; version 2 dated June, 1991.
#
#   This software is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this software; if not, write to the Free Software
#   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#

import ConfigParser
import os

class RebuilddConfig(object, ConfigParser.ConfigParser):
    """Main configuration singleton"""

    config_file = "/etc/rebuildd/rebuilddrc"
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = object.__new__(cls)
            cls._instance.init(*args, **kwargs)
        return cls._instance

    def init(self, dontparse=False):
        ConfigParser.ConfigParser.__init__(self)
        # add default sections
        self.add_section('build')
        self.add_section('mail')
        self.add_section('telnet')
        self.add_section('http')
        self.add_section('log')

        # add default values
        self.set('build', 'check_every', '300')
        self.set('build', 'max_threads', '2')
        self.set('build', 'max_jobs', '5')
        self.set('build', 'kill_timeout', '90')
        self.set('build', 'source_cmd', 'apt-get -q --download-only -t ${d} source ${p}=${v}')
        self.set('build', 'build_cmd', 'pbuilder build --basetgz /var/cache/pbuilder/${d}-${a}.tgz ${p}_${v}.dsc')
        self.set('build', 'post_build_cmd', '')
        self.set('build', 'dists', 'squeeze wheezy sid')
        self.set('build', 'work_dir', '/var/cache/rebuildd/build')
        self.set('build', 'database_uri', 'sqlite:///var/lib/rebuildd/rebuildd.db')
        self.set('build', 'build_more_recent', '1')
        self.set('build', 'more_archs', 'any')
        self.set('build', 'no_system_arch', '0')

        self.set('mail', 'from', 'rebuildd@localhost')
        self.set('mail', 'mailto', 'rebuildd@localhost')
        self.set('mail', 'subject_prefix', '[rebuildd]')
        self.set('mail', 'smtp_host', 'localhost')
        self.set('mail', 'smtp_port', '25')

        self.set('telnet', 'port', '9999')
        self.set('telnet', 'ip', '127.0.0.1')
        self.set('telnet', 'prompt', 'rebuildd@localhost->')
        self.set('telnet', 'motd', 'Connected on rebuildd on localhost')

        self.set('http', 'port', '9998')
        self.set('http', 'ip', '0.0.0.0')
        # This is dedicated to MadCoder
        self.set('http', 'log_lines_nb', '30')
        self.set('http', 'templates_dir', '/usr/share/rebuildd/templates')
        self.set('http', 'cache', '1')
        self.set('http', 'logfile', '/var/log/rebuildd/httpd.log')

        self.set('log', 'file', "/var/log/rebuildd/rebuildd.log")
        self.set('log', 'time_format', "%Y-%m-%d %H:%M:%S")
        self.set('log', 'logs_dir', "/var/log/rebuildd/build_logs")
        self.set('log', 'mail_failed', '1')
        self.set('log', 'mail_successful', '0')

        if not dontparse:
            self.reload()

        self.arch = []
        if self.get('build', 'no_system_arch') == 0:
            parch = os.popen("dpkg --print-architecture")
            self.arch.append(parch.readline().strip())
            parch.close()

        for a in self.get('build', 'more_archs').split(' '):
            self.arch.append(a)

    def reload(self):
        """Reload configuration file"""

        return self.read(self.config_file)

    def dump(self):
        """Dump running configuration"""

        conf = ""
        for section in self.sections():
            conf += "[" + section + "]\n"
            for item, value in self.items(section):
                conf += "%s = %s\n" % (item, value)
            conf += "\n"
        return conf

    def save(self):
        """Save configuration file"""

        try:
            self.write(file(self.config_file, 'w'))
        except Exception, error:
            return False
        return True
