#!/usr/bin/python
import sys  
  
sys.path.insert(0, "..")  
sys.path.insert(0, ".")  

from RebuilddTestSetup import rebuildd_global_test_setup, rebuildd_global_test_teardown
import unittest, types, os
from rebuildd.Distribution import Distribution
from rebuildd.RebuilddConfig import RebuilddConfig
from rebuildd.Rebuildd import Rebuildd
from rebuildd.Package import Package

class TestDistribution(unittest.TestCase):

    def setUp(self):
        rebuildd_global_test_setup()
        self.d = Distribution("sid", "alpha")
        self.package = Package(name="xutils", version="7.1.ds.3-1")
        self.package_dotted = Package(name="xutils", version="1:7.1.ds.3-1")

    def tearDown(self):
        rebuildd_global_test_teardown()

    def test_name(self):
        self.assert_(self.d.name is "sid")

    def test_arch(self):
        self.assert_(self.d.arch is "alpha")

if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestDistribution)
    unittest.TextTestRunner(verbosity=2).run(suite)
