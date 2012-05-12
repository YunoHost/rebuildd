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

"""rebuildd - Debian packages rebuild tool"""

from __future__ import with_statement

from Enumeration import Enumeration
from Distribution import Distribution
from Dists import Dists
from RebuilddLog import RebuilddLog, Log
from RebuilddConfig import RebuilddConfig
from RebuilddNetworkServer import RebuilddNetworkServer
from Package import Package
from Job import Job
from JobStatus import JobStatus
from JobStatus import FailedStatus
import threading, os, time, sys, signal, socket
import sqlobject

__version__ = "$Rev$"

class Rebuildd(object):
    jobs = []
    _instance = None 
         
    def __new__(cls):  
        if cls._instance is None:  
           cls._instance = object.__new__(cls)  
           cls._instance.init()
        return cls._instance  

    def init(self):
        self.cfg = RebuilddConfig()

        # Init log system
        RebuilddLog()

        self._sqlconnection = sqlobject.connectionForURI(self.cfg.get('build', 'database_uri'))
        sqlobject.sqlhub.processConnection = self._sqlconnection

        # Create distributions
        for dist in self.cfg.get('build', 'dists').split(' '):
            for arch in self.cfg.arch:
                Dists().add_dist(Distribution(dist, arch))

        self.do_quit = threading.Event()
        self.jobs_locker = threading.Lock()
        self.job_finished = threading.Event()

    def daemon(self):
        RebuilddLog.info("Starting rebuildd %s" % __version__)
        self.daemonize()

        # Run the network server thread
        RebuilddLog.info("Launching network server")
        self.netserv = RebuilddNetworkServer(self)
        self.netserv.setDaemon(True)
        self.netserv.start()

        # Run main loop
        RebuilddLog.info("Running main loop")
        self.loop()

        # On exit
        RebuilddLog.info("Cleaning finished and canceled jobs")
        self.clean_jobs()
        RebuilddLog.info("Stopping all jobs")
        self.stop_all_jobs()
        RebuilddLog.info("Releasing wait-locked jobs")
        self.release_jobs()
        self.netserv.join(10)
        RebuilddLog.info("Exiting rebuildd")

    def daemonize(self):
        """Do daemon stuff"""

        signal.signal(signal.SIGTERM, self.handle_sigterm)
        signal.signal(signal.SIGINT, self.handle_sigterm)

        try:
            os.chdir(self.cfg.get('build', 'work_dir'))
        except Exception, error:
            print "E: unable to chdir to work_dir: %s" % error
            sys.exit(1)

        try:
            sys.stdout = sys.stderr = file(self.cfg.get('log', 'file'), "a")
        except Exception, error:
            print "E: unable to open logfile: %s" % error

    def get_job(self, jobid):
        for job in self.jobs:
            if job.id == jobid:
                return job

        return None

    def get_all_jobs(self, **kwargs):
        jobs = []
        jobs.extend(Job.selectBy(**kwargs))
        return jobs

    def get_new_jobs(self):
        """Feed jobs list with waiting jobs and lock them"""

        max_new = self.cfg.getint('build', 'max_jobs')
        count_current = len(self.jobs)

        with self.jobs_locker:
            if count_current >= max_new:
                return 0

            jobs = []
            for dist in Dists().dists: 
                jobs.extend(Job.selectBy(status=JobStatus.WAIT, dist=dist.name, arch=dist.arch)[:max_new])

            count_new = 0
            for job in jobs:
                # Look for higher versions ?
                if self.cfg.getboolean('build', 'build_more_recent'):
                    packages = Package.selectBy(name=job.package.name)
                    candidate_packages = []
                    candidate_packages.extend(packages)
                    candidate_packages.sort(cmp=Package.version_compare)
                    candidate_packages.reverse()
                    newjob = None

                    # so there are packages with higher version number
                    # try to see if there's a job for us
                    for cpackage in candidate_packages:
                        candidate_jobs = []
                        candidate_jobs.extend(Job.selectBy(package=cpackage, dist=job.dist, arch=job.arch))
                        for cjob in candidate_jobs:
                            if newjob and newjob != cjob and cjob.status == JobStatus.WAIT:
                                cjob.status = JobStatus.GIVEUP
                            elif cjob.status == JobStatus.WAIT:
                                newjob = cjob

                    job = newjob

                # We have to check because it might have changed
                # between our first select and the build_more_recent stuffs

                if not job or job.status != JobStatus.WAIT:
                    continue

		# Check dependencies
		if not job.is_allowed_to_build():
		    continue

                job.status = JobStatus.WAIT_LOCKED
                job.host = socket.gethostname()
                self.jobs.append(job)
                count_new += 1
                count_current += 1

                if count_current >= max_new:
                    break

        return count_new

    def count_running_jobs(self):
        """Count running jobs"""

        count = 0
        with self.jobs_locker:
            for job in self.jobs:
                if job.status == JobStatus.BUILDING and job.isAlive():
                    count += 1

        return count

    def start_jobs(self, overrun=0):
        """Start waiting jobs"""

        running_threads = self.count_running_jobs()
        max_threads = max(overrun, self.cfg.getint('build', 'max_threads'))
        jobs_started = 0

        with self.jobs_locker:
            for job in self.jobs:
                if running_threads >= max_threads:
                    break
            
                with job.status_lock:
                    if job.status == JobStatus.WAIT_LOCKED and not job.isAlive():
                        RebuilddLog.info("Starting new thread for job %s" % job.id)
                        job.notify = self.job_finished
                        job.setDaemon(True)
                        job.start()
                        jobs_started += 1
                        running_threads = running_threads + 1

        RebuilddLog.info("Running threads: [ build %s/%s ] [ real %s ]" %
                           (running_threads, max_threads, threading.activeCount()))

        return jobs_started

    def get_jobs(self, name, version=None, dist=None, arch=None):
        """Dump a job status"""
        
        if version:
            pkgs = Package.selectBy(name=name, version=version)
        else:
            pkgs = Package.selectBy(name=name)

        if not pkgs.count():
            return []

        retjobs = []
        if dist and arch:
            for pkg in pkgs:
                retjobs.extend(Job.selectBy(package=pkg, dist=dist, arch=arch))
        elif dist:
            for pkg in pkgs:
                retjobs.extend(Job.selectBy(package=pkg, dist=dist))
        elif arch:
            for pkg in pkgs:
                retjobs.extend(Job.selectBy(package=pkg, arch=arch))
        else:
            for pkg in pkgs:
                retjobs.extend(Job.selectBy(package=pkg))
        
        return retjobs

    def dump_jobs(self, joblist=None):
        """Dump all jobs status"""

        ret = ""

        if not joblist:
            joblist = self.jobs

        for job in joblist:
            ret = "%s%s\n" % (ret, str(job))

        return ret

    def cancel_job(self, jobid):
        """Cancel a job"""

        with self.jobs_locker:
            job = self.get_job(jobid)
            if job != None:
                if job.isAlive():
                    job.do_quit.set()
                    job.join()
                with job.status_lock:
                    job.status = JobStatus.CANCELED
                self.jobs.remove(job)
                RebuilddLog.info("Canceled job %s for %s_%s on %s/%s for %s" \
                                % (job.id, job.package.name, job.package.version,
                                job.dist, job.arch, job.mailto))
                return True

        return False

    def stop_all_jobs(self):
        """Stop all running jobs"""

        with self.jobs_locker:
            for job in self.jobs:
                if job.status == JobStatus.BUILDING and job.isAlive():
                    job.do_quit.set()
                    RebuilddLog.info("Sending stop to job %s" % job.id)
            for job in self.jobs:
                if job.isAlive():
                    RebuilddLog.info("Waiting for job %s to terminate" % job.id)
                    job.join(60)

        return True

    def add_job(self, name, version, priority, dist, mailto=None, arch=None):
        """Add a job"""

        if not arch:
            arch = self.cfg.arch[0]

        if not Dists().get_dist(dist, arch):
            RebuilddLog.error("Couldn't find dist/arch in the config file for %s_%s on %s/%s, not adding it" \
                           % (name, version, dist, arch))
            return False

        pkgs = Package.selectBy(name=name, version=version)
        if pkgs.count():
            # If several packages exists, just take the first
            pkg = pkgs[0]
        else:
            # Maybe we found no packages, so create a brand new one!
            pkg = Package(name=name, version=version, priority=priority)

        jobs_count = Job.selectBy(package=pkg, dist=dist, arch=arch, mailto=mailto, status=JobStatus.WAIT).count()
        if jobs_count:
            RebuilddLog.error("Job already existing for %s_%s on %s/%s, not adding it" \
                           % (pkg.name, pkg.version, dist, arch))
            return False

        job = Job(package=pkg, dist=dist, arch=arch)
        job.status = JobStatus.WAIT
        job.arch = arch
        job.mailto = mailto

        log = Log(job=job)

        RebuilddLog.info("Added job for %s_%s on %s/%s for %s" \
                      % (name, version, dist, arch, mailto))
        return True

    def requeue_job(self, job_id):
        """Requeue a failed job"""

        if Job.selectBy(id=job_id).count() == 0:
            RebuilddLog.error("There is no job related to %s that is in the job list" % job_id)
            return False
        job = Job.selectBy(id=job_id)[0]

        if job.status in FailedStatus:
            job.status = JobStatus.WAIT
            job.host = ""

        return True

    def add_deps(self, job_id, dependency_ids):

        if Job.selectBy(id=job_id).count() == 0:
	   RebuilddLog.error("There is no job related to %s that is in the job list" % job_id)
	   return False
	job = Job.selectBy(id=job_id)[0]

	deps = []
	for dep in dependency_ids:
	    if Job.selectBy(id=dep).count() == 0:
		RebuilddLog.error("There is no job related to %s that is in the job list" % dep)
		return False
	    dep_job = Job.selectBy(id=dep)[0]
	    deps.append(dep_job)

	job.add_deps(deps)
	return True

    def clean_jobs(self):
        """Clean finished or canceled jobs"""

        with self.jobs_locker:
            for job in self.jobs:
                if job.status == JobStatus.BUILD_OK \
                   or job.status in FailedStatus \
                   or job.status == JobStatus.CANCELED:
                    self.jobs.remove(job)

        return True

    def release_jobs(self):
        """Release jobs"""

        with self.jobs_locker:
            for job in self.jobs:
                with job.status_lock:
                    if job.status == JobStatus.WAIT_LOCKED:
                        job.status = JobStatus.WAIT
                        job.host = ""

        return True

    def fix_jobs(self, print_result=True):
        """If rebuildd crashed, reset jobs to a valid state"""

        jobs = []
        jobs.extend(Job.selectBy(host=socket.gethostname(), status=JobStatus.WAIT_LOCKED))
        jobs.extend(Job.selectBy(host=socket.gethostname(), status=JobStatus.BUILDING))

        for job in jobs:
            if print_result:
                print "I: Fixing job %s (was %s)" % (job.id, JobStatus.whatis(job.status))
            job.host = None
            job.status = JobStatus.WAIT
            job.build_start = None
            job.build_end = None

        return True

    def handle_sigterm(self, signum, stack):
        RebuilddLog.info("Receiving transmission... it's a signal %s capt'ain! EVERYONE OUT!" % signum)
        self.do_quit.set()

    def loop(self):
        """Rebuildd main loop"""

        counter = self.cfg.getint('build', 'check_every')
        while not self.do_quit.isSet():
            if counter == self.cfg.getint('build', 'check_every') \
               or self.job_finished.isSet():
                self.get_new_jobs()
                # Start jobs
                self.start_jobs()
                # Clean finished jobs
                self.clean_jobs()
                counter = 0
                self.job_finished.clear()
            self.do_quit.wait(1)
            counter += 1


