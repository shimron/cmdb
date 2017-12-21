from django.shortcuts import render
from django.contrib.auth.decorators import login_required
import random
import string
import time
import os

from celery.task import task
from salt_api.api import SaltApi
from mico.settings import cmd_host_aws, cmd_host_qcd, svn_username, svn_password
from asset.utils import logs, dingding_robo
from asset.models import gogroup


# Create your views here.


@login_required
def command_index(request):
    return render(request, 'commandIndex.html')


@login_required
def command_req(request):
    username = request.user
    phone = request.user.userprofile.phone_number
    ip = request.META['REMOTE_ADDR']
    cmd = request.POST['command']
    zone = request.POST['zone']

    #: validate cmd
    svc_name = cmd.split()[0]
    go_group = gogroup.objects.filter(name=svc_name)
    if ';' in cmd or '&&' in cmd or '||' in cmd or len(go_group) == 0:
        result = [{'Command Job': 'Error - invalid command!'}]
    else:
        s_a_l_t = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
        output = '%s-%s-%s-%s.log' % (zone, time.strftime('%Y%m%d.%H%M%S', time.localtime()), username, s_a_l_t)
        output = os.path.join('/tmp', svc_name, output)
        command_exec.delay(username, phone, ip, svc_name, cmd, zone, output)
        result = [{'Command Job': 'The command is running, please check log file(%s)!' % (output,)}]

    return render(request, 'getdata.html', {'result': result})


@task
def command_exec(username, phone, ip, svc_name, cmd, zone, output):
    cmd_host = cmd_host_qcd if zone == 'qcd' else cmd_host_aws

    _cmd = 'svn co http://svn.65dg.me/svn/gotemplate /srv/gotemplate ' \
           ' --non-interactive --username={username} --password={password} && ' \
           'svn co http://svn.65dg.me/svn/{svc_name} /srv/{svc_name} ' \
           ' --non-interactive --username={username} --password={password} && ' \
           '/srv/{svc_name}/{cmd} -c /srv/gotemplate/{svc_name}/conf.ctmpl' \
           ''.format(username=svn_username, password=svn_password,
                     svc_name=svc_name, cmd=cmd)
    print(_cmd)

    salt_api = SaltApi()
    data = {
        'client': 'local',
        'fun': 'cmd.run',
        'tgt': cmd_host,
        'arg': _cmd
    }
    result = salt_api.salt_cmd(data)
    if result != 0:
        result = result['return']

    if not os.path.exists(os.path.dirname(output)):
        try:
            os.makedirs(os.path.dirname(output))
        except Exception as e:
            print(e)
            logs(username, ip, cmd, e)
            dingding_robo(cmd_host, 'command job', ' error ', username, phone)
            return str(e)

    with open(output, 'w') as f:
        if isinstance(result, list):
            for r in result:
                if isinstance(r, dict):
                    for k, v in r.items():
                        f.write('--> ')
                        f.write(k)
                        f.write('\n')
                        f.write(v)
                else:
                    f.write(str(r))
        else:
            f.write(str(result))

    logs(username, ip, cmd, 'running')
    dingding_robo(cmd_host, 'command job', result, username, phone)
    return result
