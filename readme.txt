rainmachine - weewx extension that sends data to RainMachine smart irrigation controler
Copyright 2018 Green Electronics LLC

This extension only works on the local network (doesn't work with RainMachine 
Remote Access service). RainMachine IP address and https port 8080 or 
http port 8081 must be accessible from WeeWX installation.

This extension requires RainMachine to be updated to latest version and 
have RainMachine API 4.6 to work.


Installation instructions:

1) run the installer:

wee_extension --install weewx-rainmachine-v0.3.tar.gz

2) modify weewx.conf:

[StdRESTful]
    [[RainMachine]]
        token = RAINMACHINE_ACCESS_TOKEN
        ip = RAINMACHINE_IP_ADDRESS
	usessl = false

The token can be obtained with a POST request:
curl -X POST -k -d ' { "pwd": "your_password", "remember":1}' https://rainmachine_ip:8080/api/4/auth/login

More details can be found here: 
https://support.rainmachine.com/hc/en-us/articles/228022248-Controlling-RainMachine-through-REST-API

3) restart weewx

sudo /etc/init.d/weewx stop
sudo /etc/init.d/weewx start
