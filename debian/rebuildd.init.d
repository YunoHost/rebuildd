#! /bin/sh
# rebuildd init script
#
### BEGIN INIT INFO
# Provides:          rebuildd
# Required-Start:
# Required-Stop:
# Should-Start:      $local_fs $network
# Should-Stop:       $local_fs $network
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: rebuild daemon
# Description:       daemon providing rebuild system
#                    for Debian packages
### END INIT INFO

PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
DAEMON=/usr/sbin/rebuildd
NAME=rebuildd
DESC="rebuild daemon"

test -x $DAEMON || exit 0

# Include rebuildd defaults if available
if [ -f /etc/default/rebuildd ] ; then
	. /etc/default/rebuildd
fi

test "$START_REBUILDD" = 1 || exit 0

. /lib/lsb/init-functions

set -e

case "$1" in
  start)
	log_daemon_msg "Starting $DESC" "$NAME"
	start-stop-daemon --start --quiet --pidfile /var/run/$NAME.pid \
		--background --make-pidfile --exec $DAEMON -- $DAEMON_OPTS
        log_end_msg $?
	;;
  stop)
	log_daemon_msg "Stopping $DESC" "$NAME"
	start-stop-daemon --stop --quiet --oknodo --retry 120 --pidfile /var/run/$NAME.pid
	log_end_msg $?
	;;
  #reload)
	#
	#	If the daemon can reload its config files on the fly
	#	for example by sending it SIGHUP, do it here.
	#
	#	If the daemon responds to changes in its config file
	#	directly anyway, make this a do-nothing entry.
	#
	# echo "Reloading $DESC configuration files."
	# start-stop-daemon --stop --signal 1 --quiet --pidfile \
	#	/var/run/$NAME.pid --exec $DAEMON
  #;;
  force-reload)
	#
	#	If the "reload" option is implemented, move the "force-reload"
	#	option to the "reload" entry above. If not, "force-reload" is
	#	just the same as "restart" except that it does nothing if the
	#   daemon isn't already running.
	# check wether $DAEMON is running. If so, restart
	start-stop-daemon --stop --test --quiet --pidfile \
		/var/run/$NAME.pid --exec $DAEMON \
	&& $0 restart \
	|| exit 0
	;;
  restart)
	log_daemon_msg "Restarting $DESC" "$NAME"
	start-stop-daemon --stop --quiet --pidfile \
		/var/run/$NAME.pid --exec $DAEMON
	sleep 1
	start-stop-daemon --start --quiet --pidfile \
		/var/run/$NAME.pid --exec $DAEMON -- $DAEMON_OPTS
	log_end_msg $?
	;;
  *)
	N=/etc/init.d/$NAME
	# echo "Usage: $N {start|stop|restart|reload|force-reload}" >&2
	echo "Usage: $N {start|stop|restart|force-reload}" >&2
	exit 1
	;;
esac

exit 0
