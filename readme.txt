rainmachine - weewx extension that sends data to RainMachine
Copyright 2018 Green Electronics LLC

Installation instructions:

1) run the installer:

wee_extension --install weewx-rainmachine.tgz

2) modify weewx.conf:

[StdRESTful]
    [[RainMachine]]
        token = RAINMACHINE_ACCESS_TOKEN
        ip = RAINMACHINE_IP_ADDRESS

3) restart weewx

sudo /etc/init.d/weewx stop
sudo /etc/init.d/weewx start
