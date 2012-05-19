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

import threading, subprocess, smtplib, time, os, signal, socket, select
import sqlobject
from subprocess import Popen,PIPE
from email.Message import Message
from Dists import Dists
from JobStatus import JobStatus
from JobStatus import FailedStatus
from RebuilddLog import RebuilddLog, Log
from RebuilddConfig import RebuilddConfig

__version__ = "$Rev$"

class Job(threading.Thread, sqlobject.SQLObject):
    """Class implementing a build job"""

    status = sqlobject.IntCol(default=JobStatus.UNKNOWN)
    mailto = sqlobject.StringCol(default=None)
    package = sqlobject.ForeignKey('Package', cascade=True)
    dist = sqlobject.StringCol(default='sid')
    arch = sqlobject.StringCol(default='any')
    creation_date = sqlobject.DateTimeCol(default=sqlobject.DateTimeCol.now)
    status_changed = sqlobject.DateTimeCol(default=None)
    build_start = sqlobject.DateTimeCol(default=None)
    build_end = sqlobject.DateTimeCol(default=None)
    host = sqlobject.StringCol(default=None)
    deps = sqlobject.RelatedJoin('Job', joinColumn='joba', otherColumn='jobb')
    log = sqlobject.SingleJoin('Log')

    notify = None

    def __init__(self, *args, **kwargs):
        """Init job"""

        threading.Thread.__init__(self)
        sqlobject.SQLObject.__init__(self, *args, **kwargs)

        self.do_quit = threading.Event()
        self.status_lock = threading.Lock()

    def __setattr__(self, name, value):
        """Override setattr to log build status changes"""

        if name == "status":
            RebuilddLog.info("Job %s for %s_%s on %s/%s changed status from %s to %s"\
                    % (self.id, self.package.name, self.package.version, 
                       self.dist, self.arch,
                       JobStatus.whatis(self.status),
                       JobStatus.whatis(value)))
            self.status_changed = sqlobject.DateTimeCol.now()
        sqlobject.SQLObject.__setattr__(self, name, value)

    @property
    def logfile(self):
        """Compute and return logfile name"""

        build_log_file = "%s/%s_%s-%s-%s-%s.%s.log" % (RebuilddConfig().get('log', 'logs_dir'),
                                           self.package.name, self.package.version,
                                           self.dist, self.arch,
                                           self.creation_date.strftime("%Y%m%d-%H%M%S"),
                                           self.id)
        return build_log_file

    def preexec_child(self):
        """Start a new group process before executing child"""

        os.setsid()

    def run(self):
        """Run job thread, download and build the package"""

        self.build_start = sqlobject.DateTimeCol.now()

        try:
            with open(self.logfile, "w") as build_log:
                build_log.write("Automatic build of %s_%s on %s for %s/%s by rebuildd %s\n" % \
                                 (self.package.name, self.package.version,
                                  self.host, self.dist, self.arch, __version__))
                build_log.write("Build started at %s\n" % self.build_start)
                build_log.write("******************************************************************************\n")
        except IOError:
            return

        build_log = file(self.logfile, "a")

        # we are building
        with self.status_lock:
            self.status = JobStatus.BUILDING

        # execute commands
        for cmd, failed_status in ([Dists().get_dist(self.dist, self.arch).get_source_cmd(self.package),
                                    JobStatus.SOURCE_FAILED],
                                   [Dists().get_dist(self.dist, self.arch).get_build_cmd(self.package),
                                    JobStatus.BUILD_FAILED],
                                   [Dists().get_dist(self.dist, self.arch).get_post_build_cmd(self.package),
                                    JobStatus.POST_BUILD_FAILED]):
            if cmd is None:
                continue
            try:
                proc = subprocess.Popen(cmd.split(), bufsize=0,
                                                     preexec_fn=self.preexec_child,
                                                     stdout=build_log,
                                                     stdin=None,
                                                     stderr=subprocess.STDOUT)
            except Exception, error:
                build_log.write("\nUnable to execute command \"%s\": %s" %\
                        (cmd, error))
                with self.status_lock:
                    self.status = failed_status
                state = 1
                break
            state = proc.poll()
            while not self.do_quit.isSet() and state == None:
                state = proc.poll()
                self.do_quit.wait(1)
            if self.do_quit.isSet():
                break
            if state != 0:
                with self.status_lock:
                    self.status = failed_status
                break

        if self.do_quit.isSet():
            # Kill gently the process
            RebuilddLog.info("Killing job %s with SIGINT" % self.id)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            except OSError, error:
                RebuilddLog.error("Error killing job %s: %s" % (self.id, error))

            # If after 60s it's not dead, KILL HIM
            counter = 0
            timemax = RebuilddConfig().get('build', 'kill_timeout')
            while proc.poll() == None and counter < timemax:
                time.sleep(1)
                counter += 1
            if proc.poll() == None:
                RebuilddLog.error("Killing job %s timed out, killing with SIGKILL" \
                           % self.id)
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

            with self.status_lock:
                self.status = JobStatus.WAIT_LOCKED

            # Reset host
            self.host = None

            build_log.write("\nBuild job killed on request\n")
            build_log.close()

            return

        # build is finished
        with self.status_lock:
            if state == 0:
                self.status = JobStatus.BUILD_OK

        self.build_end = sqlobject.DateTimeCol.now()

        build_log.write("******************************************************************************\n")
        build_log.write("Finished with status %s at %s\n" % (JobStatus.whatis(self.status), self.build_end))
        build_log.write("Build needed %s\n" % (self.build_end - self.build_start))
        build_log.close()


        # Send event to Rebuildd to inform it that it can
        # run a brand new job!
        if self.notify:
            self.notify.set()

        self.send_build_log()

    def send_build_log(self):
        """When job is built, send logs by mail"""

        try:
            with open(self.logfile, "r") as build_log:
                log =  build_log.read()
        except IOError, error:
            RebuilddLog.error("Unable to open logfile for job %d" % self.id)
            return False

        # Store in database
        self.log.text = log

        with self.status_lock:
            if self.status != JobStatus.BUILD_OK and \
                not self.status in FailedStatus:
                return False

            if not RebuilddConfig().getboolean('log', 'mail_successful') \
               and self.status == JobStatus.BUILD_OK:
                return True
            elif not RebuilddConfig().getboolean('log', 'mail_failed') \
                 and self.status in FailedStatus:
                return True

        if self.status == JobStatus.BUILD_OK:
            bstatus = "successful"
        else:
            bstatus = "failed"

        msg = Message()
        if self.mailto:
            msg['To'] = self.mailto
        else:
            msg['To'] = RebuilddConfig().get('mail', 'mailto')
        msg['From'] = RebuilddConfig().get('mail', 'from')
        msg['Subject'] = RebuilddConfig().get('mail', 'subject_prefix') + \
                                 " Log for %s build of %s_%s on %s/%s" % \
                                 (bstatus,
                                  self.package.name, 
                                  self.package.version,
                                  self.dist,
                                  self.arch)
        msg['X-Rebuildd-Version'] = __version__
        msg['X-Rebuildd-Host'] = socket.getfqdn()


        msg.set_payload(log)

        try:
            smtp = smtplib.SMTP()
            smtp.connect(RebuilddConfig().get('mail', 'smtp_host'),
                         RebuilddConfig().get('mail', 'smtp_port'))
            smtp.sendmail(RebuilddConfig().get('mail', 'from'),
                          [m.strip() for m in msg['To'].split(",")],
                          msg.as_string())
        except Exception, error:
            try:
                process = Popen("sendmail", shell=True, stdin=PIPE)
                process.communicate(input=msg.as_string())
            except:
                RebuilddLog.error("Unable to send build log mail for job %d: %s" % (self.id, error))

        return True

    def __str__(self):
        return "I: Job %s for %s_%s is status %s on %s for %s/%s" % \
                (self.id, self.package.name, self.package.version, self.host,
                 JobStatus.whatis(self.status), self.dist, self.arch)

    def is_allowed_to_build(self):
        """ Check if job is allowed to build """

	for dep in Job.selectBy(id=self)[0].deps:
	    if Job.selectBy(id=dep)[0].status != JobStatus.BUILD_OK:
		return False
	return True

    def add_dep(self, dep):
	"""Add a job dependency on another job"""

	for existing_dep in self.deps:
	    if existing_dep.id == dep.id:
		RebuilddLog.error("Already existing dependency between job %s and job %s" % (self.id, dep.id))
		return
	self.addJob(dep)
	RebuilddLog.info("Dependency added between job %s and job %s" % (self.id, dep.id))

    def add_deps(self,deps):
	""" Add several job dependency on another job"""

	for dep in deps:
	    self.add_dep(dep)
