# Copyright 2018 Green Electronics LLC
"""
Upload weather data directly to RainMachine smart irrigation controler 
  http://rainmachine.com

Based on RainMachine API 4.6 https://rainmachine.docs.apiary.io/

This extension only works on the local network (doesn't work with RainMachine 
Remote Access service). RainMachine IP address and https port 8080 must be 
accessible from WeeWX installation.

An access token is needed and can be obtained with a POST request:
curl -X POST -k -d ' { "pwd": "admin", "remember":1}' https://rainmachine_ip:8080/api/4/auth/login

More details can be found here: 
https://support.rainmachine.com/hc/en-us/articles/228022248-Controlling-RainMachine-through-REST-API

By default data is sent to RainMachine hourly. Although is possible to send data more often the
RainMachine Mixer (that aggregates data from multiple sources) runs only hourly.


Minimal configuration:

[StdRESTful]
    [[RainMachie]]
        token = ACCESS_TOKEN
	ip = RAINMACHINE IP
"""

import Queue
import syslog
import urllib
import urllib2
import json

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, accumulateLeaves, startOfDayUTC

VERSION = "0.1"

if weewx.__version__ < "3":
    raise weewx.UnsupportedFeature("weewx 3 is required, found %s" %
                                   weewx.__version__)

def logmsg(level, msg):
    syslog.syslog(level, 'restx: RainMachine: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


def _get_day_max_temp(dbm, ts):
    sod = startOfDayUTC(ts)
    val = dbm.getSql("SELECT MAX(outTemp) FROM %s "
                     "WHERE dateTime>? AND dateTime<=?" %
                     dbm.table_name, (sod, ts))
    return val[0] if val is not None else None

def _get_day_min_temp(dbm, ts):
    sod = startOfDayUTC(ts)
    val = dbm.getSql("SELECT MIN(outTemp) FROM %s "
                     "WHERE dateTime>? AND dateTime<=?" %
                     dbm.table_name, (sod, ts))
    return val[0] if val is not None else None


class RainMachine(weewx.restx.StdRESTful):
    def __init__(self, engine, config_dict):
        super(RainMachine, self).__init__(engine, config_dict)
        loginf('service version is %s' % VERSION)
        try:
            site_dict = config_dict['StdRESTful']['RainMachine']
            site_dict = accumulateLeaves(site_dict, max_level=1)
            site_dict['token']
            site_dict['ip']
        except KeyError, e:
            logerr("Data will not be posted: Missing option %s" % e)
            return

	if config_dict['StdRESTful']['RainMachine'].has_key('password'):
            site_dict['password'] = dict(config_dict['StdRESTful']['RainMachine']['password'])

        site_dict['manager_dict'] = weewx.manager.get_manager_dict(
            config_dict['DataBindings'], config_dict['Databases'], 'wx_binding')

        self.archive_queue = Queue.Queue()
        self.archive_thread = RainMachineThread(self.archive_queue, **site_dict)
        self.archive_thread.start()
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        loginf("Data will be uploaded for RainMachine located at %s" % site_dict['ip'])

    def new_archive_record(self, event):
        self.archive_queue.put(event.record)

class RainMachineThread(weewx.restx.RESTThread):
    """
RainMachine POST /api/4/parser/data expected data format (metric units only):
{
    "weather": [
        {
            "mintemp":null,
            "maxtemp": null,
            "temperature": null,
            "wind": null,
            "solarrad": null,
            "qpf": null,
            "rain": null,
            "minrh": null,
            "maxrh": null,
            "condition": 26,
            "pressure": null,
            "dewpoint": null
        },
        {
            "timestamp": 1563362587,
            "mintemp":null,
            "maxtemp": null,
            "temperature": null,
            "wind": null,
            "solarrad": null,
            "qpf": null,
            "rain": null,
            "minrh": null,
            "maxrh": null,
            "condition": 26,
            "pressure": null,
            "dewpoint": null,
	    "et": null
        }
    ]
}
    """

    _DATA_MAP = {
        'timestamp':          ('dateTime',    1, 0),        # epoch
        'wind':  ('windSpeed',   0.2777777777, 0.0), # m/s
        'temperature': ('outTemp',     1.0, 0.0),    # C
        'maxrh':    ('outHumidity', 1.0, 0.0),    # percent
	'dewpoint': ('dewpoint', 1.0, 0.0), # C
        'pressure':    ('barometer',   10.0, 0.0),    # kPa
        'rain':		('dayRain',      10.0, 0.0),   # mm
	'mintemp':	('OutTempMin', 1.0, 0.0), # C
	'maxtemp':	('OutTempMax', 1.0, 0.0), # C
	'et':		('ET', 10.0, 0), # mm
        }

    def __init__(self, queue,
                 token, ip, manager_dict,
                 skip_upload=False,
                 post_interval=3600, max_backlog=0, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5):
        super(RainMachineThread, self).__init__(queue,
                                                   protocol_name='RainMachine',
                                                   manager_dict=manager_dict,
                                                   post_interval=post_interval,
                                                   max_backlog=max_backlog,
                                                   stale=stale,
                                                   log_success=log_success,
                                                   log_failure=log_failure,
                                                   timeout=timeout,
                                                   max_tries=max_tries,
                                                   retry_wait=retry_wait)
        self.token = token
        self.ip = ip
        self.skip_upload = to_bool(skip_upload)

    def process_record(self, record, dbm):
        r = self.get_record(record, dbm)
        data = self.get_data(r)
        url = "https://%s:8080/api/4/parser/data?access_token=%s" % (self.ip, self.token)

        if self.skip_upload:
            loginf("skipping upload")
            return
        req = urllib2.Request(url, data)
        req.get_method = lambda: 'POST'
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "weewx/%s" % weewx.__version__)
        self.post_with_retries(req)

    def get_record(self, record, dbm):
        rec = super(RainMachineThread, self).get_record(record, dbm)
        # put everything into the right units
        rec = weewx.units.to_METRIC(rec)
        # add the fields specific to weatherbug
        rec['outTempMax'] = _get_day_max_temp(dbm, rec['dateTime'])
        rec['outTempMin'] = _get_day_min_temp(dbm, rec['dateTime'])
        return rec


    def get_data(self, record):
        # put data into expected scaling, structure, and format
	entry = {}
        for _key in self._DATA_MAP:
            rkey = self._DATA_MAP[_key][0]
            if rkey in record and record[rkey] is not None:
                entry[_key] = record[rkey] * self._DATA_MAP[_key][1] + self._DATA_MAP[_key][2]

	values = {}
	values['weather'] = []
	values['weather'].append(entry)
        data = json.dumps(values)
        return data
