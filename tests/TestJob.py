#!/usr/bin/python
import sys  
  
sys.path.insert(0, "..")  
sys.path.insert(0, ".")  
from RebuilddTestSetup import rebuildd_global_test_setup, rebuildd_global_test_teardown
import unittest, types, os
import sqlobject
from rebuildd.RebuilddConfig import RebuilddConfig
from rebuildd.Package import Package
from rebuildd.Job import Job
from rebuildd.JobStatus import JobStatus

class TestJob(unittest.TestCase):

    def setUp(self):
        rebuildd_global_test_setup()
        self.job = Job(package=Package(name="bash", version="3.1dfsg-8"), arch="alpha", dist="sid")
        self.job_dotted_version = Job(package=Package(name="bash", version="1:3.1dfsg-8"), arch="alpha", dist="sid")

    def tearDown(self):
        rebuildd_global_test_teardown()

    def test_DB_OK(self):
        self.assert_(os.path.isfile('/tmp/rebuildd-tests.db'))
        self.assert_(os.path.getsize('/tmp/rebuildd-tests.db') > 0)

    def test_init_job(self):
        self.assert_(type(self.job) is Job)

    def test_setattr(self):
        self.job.status = JobStatus.UNKNOWN
        self.assert_(self.job.status == JobStatus.UNKNOWN)
        self.job.status = JobStatus.WAIT
        self.assert_(self.job.status == JobStatus.WAIT)

    def test_open_logfile(self):
        file = open(self.job.logfile, "w")
        self.assert_(file is not None)
        filero = open(self.job.logfile, "r")
        self.assert_(filero is not None)
        file.close()
        filero.close()
        os.unlink(file.name)

    def test_status_on_doquit(self):
        self.job.do_quit.set()
        self.job.start()
        self.job.join()
        self.assert_(self.job.status == JobStatus.WAIT_LOCKED)

    def test_build_success(self):
        self.job.do_quit.clear()
        RebuilddConfig().set('build', 'source_cmd', '/bin/true')
        RebuilddConfig().set('build', 'build_cmd', '/bin/true')
        RebuilddConfig().set('build', 'post_build_cmd', '/bin/true')
        self.job.start()
        self.job.join()
        self.assert_(self.job.status == JobStatus.BUILD_OK)

    def test_build_failure_source(self):
        self.job.do_quit.clear()
        RebuilddConfig().set('build', 'source_cmd', '/bin/false')
        RebuilddConfig().set('build', 'build_cmd', '/bin/true')
        RebuilddConfig().set('build', 'post_build_cmd', '/bin/true')
        self.job.start()
        self.job.join()
        self.assert_(self.job.status == JobStatus.SOURCE_FAILED)

    def test_build_failure_build(self):
        self.job.do_quit.clear()
        RebuilddConfig().set('build', 'source_cmd', '/bin/true %s %s %s')
        RebuilddConfig().set('build', 'build_cmd', '/bin/false %s %s %s %s')
        RebuilddConfig().set('build', 'post_build_cmd', '/bin/true %s %s %s %s')
        self.job.start()
        self.job.join()
        self.assert_(self.job.status == JobStatus.BUILD_FAILED)

    def test_build_failure_post_build(self):
        RebuilddConfig().set('build', 'source_cmd', '/bin/true %s %s %s')
        RebuilddConfig().set('build', 'build_cmd', '/bin/true %s %s %s %s')
        RebuilddConfig().set('build', 'post_build_cmd', '/bin/false %s %s %s %s')
        self.job.start()
        self.job.join()
        self.assert_(self.job.status == JobStatus.POST_BUILD_FAILED)

    def test_send_build_log(self):
        file = open(self.job.logfile, "w")
        self.assert_(file is not None)
        file.write("Fake log file")
        file.close()
        self.assert_(self.job.send_build_log() is False)
        self.job.status = JobStatus.BUILD_OK
        self.assert_(self.job.send_build_log() is True)
        self.assert_(self.job.status is JobStatus.BUILD_OK)
        self.job.status = JobStatus.BUILD_FAILED
        self.assert_(self.job.send_build_log() is True)
        self.assert_(self.job.status is JobStatus.BUILD_FAILED)

    def test_get_source_cmd(self):
        RebuilddConfig().set('build', 'source_cmd', '/bin/true $d $a $p $v $j')
        cmd = self.job.get_source_cmd()
        self.assert_(self.job.dist in cmd)
        self.assert_(self.job.package.name in cmd)
        self.assert_(self.job.package.version in cmd)
        self.assert_(str(self.job.id) in cmd)

    def test_get_build_cmd(self):
        RebuilddConfig().set('build', 'build_cmd', '/bin/true $d $a $p $v $j')
        cmd = self.job.get_build_cmd()
        self.assert_(self.job.dist in cmd)
        self.assert_(self.job.arch in cmd)
        self.assert_(self.job.package.name in cmd)
        self.assert_(self.job.package.version in cmd)
        self.assert_(str(self.job.id) in cmd)
        cmd = self.job_dotted_version.get_build_cmd()
        self.assert_(self.job_dotted_version.package.version not in cmd)

    def test_get_post_build_cmd(self):
        RebuilddConfig().set('build', 'post_build_cmd', '')
        cmd = self.job.get_post_build_cmd()
        self.assert_(cmd is None)
        RebuilddConfig().set('build', 'post_build_cmd', '/bin/true $d $a $p $v $j')
        cmd = self.job.get_post_build_cmd()
        self.assert_(self.job.dist in cmd)
        self.assert_(self.job.package.name in cmd)
        self.assert_(self.job.package.version in cmd)
        self.assert_(str(self.job.id) in cmd)

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestJob)
    unittest.TextTestRunner(verbosity=2).run(suite)
