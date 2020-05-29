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
    [[RainMachine]]
        token = ACCESS_TOKEN
        ip = RAINMACHINE IP
        usessl = false
"""

try:
    import queue
except ImportError:
    import Queue as queue
import json

import weewx
import weewx.restx
import weewx.units
from weeutil.weeutil import to_bool, startOfDayUTC

VERSION = "0.5"

if weewx.__version__ < "3":
    raise weewx.UnsupportedFeature("weewx 3 is required, found %s" %
                                   weewx.__version__)

try:
    # Test for new-style weewx logging by trying to import weeutil.logger
    import weeutil.logger
    import logging

    log = logging.getLogger(__name__)


    def logdbg(msg):
        log.debug(msg)


    def loginf(msg):
        log.info(msg)


    def logerr(msg):
        log.error(msg)

except ImportError:
    # Old-style weewx logging
    import syslog


    def logmsg(level, msg):
        syslog.syslog(level, 'RainMachine: %s:' % msg)


    def logdbg(msg):
        logmsg(syslog.LOG_DEBUG, msg)


    def loginf(msg):
        logmsg(syslog.LOG_INFO, msg)


    def logerr(msg):
        logmsg(syslog.LOG_ERR, msg)


def _get_day_min_max_temp(dbm, ts):
    if dbm is None:
        return None, None
    sod = startOfDayUTC(ts)
    val = dbm.getSql("SELECT MIN(outTemp), MAX(outTemp) FROM %s "
                     "WHERE dateTime>? AND dateTime<=?" %
                     dbm.table_name, (sod, ts))
    if val is None:
        return None, None

    return val


def _convert_temperature(v, from_unit):
    """convert temperature to celsius (we need this from values read from DB)"""
    if from_unit is None or v is None:
        return None
    if from_unit != weewx.METRIC:
        std_type, _ = weewx.units.getStandardUnitType(from_unit, 'outTemp')
        from_type = (v, std_type, 'group_temperature')
        v = weewx.units.convert(from_type, 'degree_C')[0]
    return v


class RainMachine(weewx.restx.StdRESTful):
    def __init__(self, engine, config_dict):
        super(RainMachine, self).__init__(engine, config_dict)
        loginf('service version is %s' % VERSION)

        site_dict = weewx.restx.get_site_dict(config_dict, 'RainMachine', 'token', 'ip')
        if site_dict is None:
            return

        try:
            site_dict['manager_dict'] = weewx.manager.get_manager_dict_from_config(config_dict, 'wx_binding')
        except weewx.UnknownBinding:
            pass

        self.archive_queue = queue.Queue()
        self.archive_thread = RainMachineThread(self.archive_queue, **site_dict)
        self.archive_thread.start()
        self.bind(weewx.NEW_ARCHIVE_RECORD, self.new_archive_record)
        loginf("Data will be uploaded for RainMachine located at %s ssl: %s" % (site_dict['ip'], site_dict['usessl']))

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
        'timestamp': ('dateTime', 1, 0),  # epoch
        'wind': ('windSpeed', 0.2777777777, 0.0),  # m/s
        'temperature': ('outTemp', 1.0, 0.0),  # C
        'maxrh': ('outHumidity', 1.0, 0.0),  # percent
        'dewpoint': ('dewpoint', 1.0, 0.0),  # C
        'pressure': ('barometer', 0.1, 0.0),  # kPa
        'rain': ('dayRain', 10.0, 0.0),  # mm
        'mintemp': ('outTempMin', 1.0, 0.0),  # C
        'maxtemp': ('outTempMax', 1.0, 0.0),  # C
        'et': ('ET', 10.0, 0),  # mm
    }

    def __init__(self, q,
                 token, ip, manager_dict=None, usessl=False,
                 skip_upload=False,
                 post_interval=3600, max_backlog=0, stale=None,
                 log_success=True, log_failure=True,
                 timeout=60, max_tries=3, retry_wait=5):
        super(RainMachineThread, self).__init__(q,
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
        self.usessl = to_bool(usessl)
        self.skip_upload = to_bool(skip_upload)

    def format_url(self, _):
        """Specialized version that formats the rainmachine URL"""

        if self.usessl:
            proto = "https"
            port = "8080"
        else:
            proto = "http"
            port = "8081"

        url = "%s://%s:%s/api/4/parser/data?access_token=%s" % (proto, self.ip, port, self.token)
        return url

    def get_record(self, record, dbm):
        """Specialized version that gets the data rainmachine needs"""
        rec = super(RainMachineThread, self).get_record(record, dbm)
        # put everything into the right units
        rec = weewx.units.to_METRIC(rec)
        rec['outTempMin'], rec['outTempMax'] = _get_day_min_max_temp(dbm, rec['dateTime'])
        rec['outTempMin'] = _convert_temperature(rec['outTempMin'], record['usUnits'])
        rec['outTempMax'] = _convert_temperature(rec['outTempMax'], record['usUnits'])
        return rec

    def get_post_body(self, record):
        """Specialized version that returns rainmachine POST body"""
        entry = {}
        for _key in self._DATA_MAP:
            rkey = self._DATA_MAP[_key][0]
            if rkey in record and record[rkey] is not None:
                entry[_key] = record[rkey] * self._DATA_MAP[_key][1] + self._DATA_MAP[_key][2]

        values = {}
        values['weather'] = []
        values['weather'].append(entry)
        data = json.dumps(values)
        return data, "application/json"
