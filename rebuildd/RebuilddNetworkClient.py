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

from __future__ import with_statement

from RebuilddConfig import RebuilddConfig
import threading, socket

__version__ = "$Rev$"

class RebuilddNetworkClient(threading.Thread):
    """Network client used for each connection"""

    def __init__(self, socket, rebuildd):
        threading.Thread.__init__(self)
        self.rebuildd = rebuildd
        self.socket = socket

    def run(self):
        """Run client thread"""

        self.socket.settimeout(1)
        self.socket.send(RebuilddConfig().get('telnet', 'motd') + "\n")
        prompt = RebuilddConfig().get('telnet', 'prompt') + " "
        line = ""
        has_timeout = False
        while line != "exit" and not self.rebuildd.do_quit.isSet():
            if not has_timeout:
                try:
                    self.socket.send(self.exec_cmd(line))
                    self.socket.send(prompt)
                except Exception:
                    break
            try:
                line = ""
                line = self.socket.recv(512).strip()
                has_timeout = False
            except socket.timeout:
                has_timeout = True

        self.socket.close()

    def exec_cmd(self, cmd):
        """Execute a command asked by a client"""

        # Return empty if empty
        if cmd == "":
            return ""

        # Split words
        op = cmd.split(' ')
        cmd_fct = op[0]
        if not cmd_fct.isalnum():
            return ""
        op.remove(op[0])
        try:
            return getattr(self, "exec_cmd_" + cmd_fct)(*tuple(op))
        except Exception, error:
            return "E: command error: %s\n" % error

    def exec_cmd_help(self, *args):
        """Show help"""

        help = ""
        for attr in dir(RebuilddNetworkClient):
            if attr.startswith("exec_cmd_"):
                help += "%s -- %s\n" \
                        % (attr[9:].replace("_", " "),
                           getattr(RebuilddNetworkClient, attr).__doc__)

        return help
        
    def exec_cmd_config(self, *args):
        """Manipulate configuration file"""

        if len(args) < 1:
            return "E: usage: config [reload|dump|save]\n"

        if args[0] == "reload":
            if RebuilddConfig().reload():
                return "I: config reloaded\n"
            return "E: config not reloded\n"

        if args[0] == "dump":
            return RebuilddConfig().dump()

        if args[0] == "save":
            if RebuilddConfig().save():
                return "I: config saved\n"
            return "E: config not saved\n"

        return "E: usage: config [reload|dump|save]\n"

    def exec_cmd_status(self, *args):
        """Show current jobs status"""
        return self.rebuildd.dump_jobs()

    def exec_cmd_version(self, *args):
        """Show version"""
        return __version__ + "\n"

    def exec_cmd_job(self, *args):
        """Manipulate jobs"""

        if len(args) > 0 and args[0] == "add":
            return self.exec_cmd_job_add(*args)

        if len(args) > 0 and args[0] == "deps":
            return self.exec_cmd_job_deps(*args)

        if len(args) > 0 and args[0] == "cancel":
            return self.exec_cmd_job_cancel(*args)

        if len(args) > 0 and args[0] == "start":
            return self.exec_cmd_job_start(*args)

        if len(args) > 0 and args[0] == "reload":
            return self.exec_cmd_job_reload(*args)

        if len(args) > 0 and args[0] == "status":
            return self.exec_cmd_job_status(*args)

        if len(args) > 0 and args[0] == "requeue":
            return self.exec_cmd_job_requeue(*args)

        return "E: usage: job <command> [args]\n"

    def exec_cmd_job_add(self, *args):
        """Add job"""

        ret = False
        if len(args) < 4:
            return "E: usage: job add <name> <ver> <priority> <dist> [arch] [mailto]\n"

        if len(args) == 5:
            ret = self.rebuildd.add_job(name=args[1],
                                        version=args[2],
                                        priority=args[3],
                                        dist=args[4])

        if len(args) == 6:
            ret = self.rebuildd.add_job(name=args[1],
                                        version=args[2],
                                        priority=args[3],
                                        dist=args[4],
                                        arch=args[5])

        if len(args) == 7:
            ret = self.rebuildd.add_job(name=args[1], 
                                        version=args[2],
                                        priority=args[3],
                                        dist=args[4], 
                                        arch=args[5],
                                        mailto=args[6])
        
        if ret:
            return "I: job added\n"
        return "E: error adding job\n"

    def exec_cmd_job_requeue(self, *args):
        """Requeue job"""

        if len(args) != 2:
            return "E: usage: job requeue <job_id>\n"

        if self.rebuildd.requeue_job(job_id=int(args[1])):
            return "I: job requeued\n"
        return "E: error requeuing the job\n"

    def exec_cmd_job_deps(self, *args):
        """Add dependency"""

        ret = False
        if len(args) < 2:
            return "E: usage: job deps <job_id> <dependency_job_id> [dependency_job_id] [...]\n"

	ret = self.rebuildd.add_deps(job_id=args[1],
				    dependency_ids=args[2:])

	if ret:
	    return "I: Dependency added\n"
	return "E: error adding deps"


    def exec_cmd_job_cancel(self, *args):
        """Cancel job"""

        if len(args) < 2:
            return "E: usage: job cancel <id>\n"
        if self.rebuildd.cancel_job(int(args[1])):
            return "I: job canceled\n"
        return "E: unknown job\n"

    def exec_cmd_job_start(self, *args):
        """Start jobs"""

        if len(args) == 2:
            return "I: %s jobs started\n" \
                    % self.rebuildd.start_jobs(int(args[1]))
        return "I: %s jobs started\n" \
                % self.rebuildd.start_jobs()

    def exec_cmd_job_reload(self, *args):
        """Load new jobs"""

        return "I: %s new jobs added\n" % self.rebuildd.get_new_jobs()

    def exec_cmd_job_status(self, *args):
        """Dump job status"""

        if len(args) < 2 or len(args) > 5:
            return "E: usage: job status <name> <ver> <dist> [arch]\n"
        elif len(args) == 2:
            jobs = self.rebuildd.get_jobs(name=args[1])
        elif len(args) == 3:
            jobs = self.rebuildd.get_jobs(name=args[1],
                                          version=args[2])
        elif len(args) == 4:
            jobs = self.rebuildd.get_jobs(name=args[1],
                                          version=args[2],
                                          dist=args[3])
        elif len(args) == 5:
            jobs = self.rebuildd.get_jobs(name=args[1],
                                          version=args[2],
                                          dist=args[3],
                                          arch=args[4])

        return self.rebuildd.dump_jobs(jobs)
