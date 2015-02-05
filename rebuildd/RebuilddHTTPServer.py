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
from Rebuildd import Rebuildd
from Package import Package
from Job import Job
from JobStatus import JobStatus
from JobStatus import FailedStatus

import tempfile, socket, sqlobject
import web
import gdchart
from math import ceil

render = web.template.render(RebuilddConfig().get('http', 'templates_dir'), \
         cache=RebuilddConfig().getboolean('http', 'cache'))

def _paginate_query(query):
    # Retrieve requested page
    page = int(web.input(p=1).p)
    if page < 1:
        page = 1

    # Validate and calculate jobs range
    max_jobs = RebuilddConfig().getint('http', 'jobs_by_page')
    nb_pages = int(ceil(query.count() / float(max_jobs)))
    if page > nb_pages:
        page = nb_pages
    start = (page - 1) * (max_jobs - 1)
    end = page * (max_jobs - 1)

    # Return formatted result
    return (query[start:end], page, nb_pages)

class RequestIndex:

    def GET(self):
        return render.base(page=render.index(), \
                hostname=socket.gethostname(), \
                archs=RebuilddConfig().arch, \
                dists=RebuilddConfig().get('build', 'dists').split(' '))

class RequestPackage:

    def GET(self, name=None, version=None):
        jobs = []

        if version:
            pkg = Package.selectBy(name=name, version=version)[0]
            title = "%s %s" % (name, version)
            package = "%s/%s" % (name, version)
        else:
            pkg = Package.selectBy(name=name)[0]
            title = package = name

        result, page, nb_pages = _paginate_query(Job.selectBy(package=pkg))

        jobs.extend(result)
        return render.base(page=render.tab(jobs=jobs, page=page, nb_pages=nb_pages), \
                hostname=socket.gethostname(), \
                title=title, \
                package=package, \
                archs=RebuilddConfig().arch, \
                dists=RebuilddConfig().get('build', 'dists').split(' '))

class RequestArch:

    def GET(self, dist, arch=None):
        jobs = []

        result, page, nb_pages = _paginate_query(Job.select(
                sqlobject.AND(Job.q.arch == arch, Job.q.dist == dist),
                orderBy=sqlobject.DESC(Job.q.creation_date)))

        jobs.extend(result)
        return render.base(page=render.tab(jobs=jobs, page=page, nb_pages=nb_pages), \
                arch=arch, \
                dist=dist, \
                title="%s/%s" % (dist, arch), \
                hostname=socket.gethostname(), \
                archs=RebuilddConfig().arch, \
                dists=RebuilddConfig().get('build', 'dists').split(' '))

class RequestJob:

    def GET(self, jobid=None):
        job = Job.selectBy(id=jobid)[0]

        try:
            with open(job.logfile, "r") as build_logfile:
                build_log = build_logfile.read()
        except IOError, error:
            build_log = job.log.text

        return render.base(page=render.job(job=job, build_log=build_log), \
                hostname=socket.gethostname(), \
                title="job %s" % job.id, \
                archs=RebuilddConfig().arch, \
                dists=RebuilddConfig().get('build', 'dists').split(' '))

class RequestGraph:

    GET = web.autodelegate("GET_")

    def graph_init(self):
        web.header("Content-Type","image/png") 
        graph = gdchart.Bar3D()
        graph.width = 300
        graph.height = 300
        graph.ytitle = "Jobs"
        graph.xtitle = "Build status"
        graph.ext_color = [ "yellow", "orange", "red", "green"]
        graph.bg_color = "white"
        graph.setLabels(["WAIT", "BUILDING", "FAILED", "OK"])

        return graph

    def compute_stats(self, jobs):
        jw = 0
        jb = 0
        jf = 0
        jo = 0
        for job in jobs:
            if job.status == JobStatus.WAIT or \
               job.status == JobStatus.WAIT_LOCKED:
                jw += 1
            elif job.status == JobStatus.BUILDING:
                jb += 1
            elif job.status in FailedStatus:
                jf += 1
            elif job.status == JobStatus.BUILD_OK:
                jo += 1

        return (jw, jb, jf, jo)

    def GET_buildstats(self, distarch=None):
        graph = self.graph_init()
        if distarch == "/":
            graph.title = "Build status"
            jobs = Job.selectBy()
        else:
            dindex = distarch.rindex("/")
            graph.title = "Build status for %s" % distarch[1:]
            jobs = Job.selectBy(arch=distarch[dindex+1:], dist=distarch[1:dindex])

        graph.setData(self.compute_stats(jobs))
        tmp = tempfile.TemporaryFile()
        graph.draw(tmp)
        tmp.seek(0)
        return tmp.read()

    def GET_package(self, package=None):
        graph = self.graph_init()
        if package == "/":
            graph.title = "Build status"
            jobs = Job.selectBy()
        else:
            dindex = package.rindex("/")
            graph.title = "Build status for %s" % package[1:]
            pkg = Package.selectBy(version=package[dindex+1:], name=package[1:dindex])[0]
            jobs = Job.selectBy(package=pkg)

        graph.setData(self.compute_stats(jobs))
        tmp = tempfile.TemporaryFile()
        graph.draw(tmp)
        tmp.seek(0)
        return tmp.read()

class RebuilddHTTPServer:
    """Main HTTP server"""

    urls = (
            '/', 'RequestIndex',
            '/dist/(.*)/arch/(.*)', 'RequestArch',
            '/job/(.*)', 'RequestJob',
            '/package/(.*)/(.*)', 'RequestPackage',
            '/package/(.*)', 'RequestPackage',
            '/graph/(.*)', 'RequestGraph',
            )

    def __init__(self):
        Rebuildd()

    def start(self):

        """Run main HTTP server thread"""

        web.webapi.internalerror = web.debugerror

        import sys; sys.argv.append(RebuilddConfig().get('http', 'ip') + ":" + RebuilddConfig().get('http', 'port'))

	app = web.application(self.urls, globals())
	app.run()

