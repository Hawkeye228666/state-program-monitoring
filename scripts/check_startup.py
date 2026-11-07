"""Exercise actual Windows/Python environment generators in isolated ZIP-like folders."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent.parent
shell=shutil.which('powershell') if os.name=='nt' else shutil.which('pwsh')
assert shell, 'PowerShell is required for this launcher check'
keys=('DJANGO_SECRET_KEY','POSTGRES_ADMIN_PASSWORD','POSTGRES_APP_PASSWORD')
with tempfile.TemporaryDirectory(prefix='monitor setup ') as temp:
    for generator in ('create_env.ps1','create_env.py'):
        folder=Path(temp)/generator/'project with spaces'
        (folder/'scripts').mkdir(parents=True)
        shutil.copyfile(root/'.env.example',folder/'.env.example')
        shutil.copyfile(root/'scripts'/generator,folder/'scripts'/generator)
        command=([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(folder/'scripts'/generator)]
                 if generator.endswith('.ps1') else [sys.executable,str(folder/'scripts'/generator)])
        def run():
            result=subprocess.run(command,capture_output=True)
            assert result.returncode==0,result.stderr.decode(errors='replace')
            return result.stdout
        output=run()
        target=folder/'.env'
        original=target.read_bytes()
        values=dict(line.split('=',1) for line in original.decode('utf-8-sig').splitlines() if '=' in line and not line.startswith('#'))
        assert len({values[key] for key in keys})==3
        assert all(len(values[key])>=64 for key in keys)
        assert all(values[key].encode() not in output for key in keys)
        run()
        assert target.read_bytes()==original,'Repeat start changed credentials'
        # A copied template or incomplete .env is repaired, preserving custom settings.
        target.write_text('POSTGRES_APP_PASSWORD=keep-this-password\nDJANGO_SECRET_KEY=""\nAPP_PORT=8123\n',encoding='utf-8')
        run()
        repaired=target.read_text(encoding='utf-8-sig')
        assert 'POSTGRES_APP_PASSWORD=keep-this-password\n' in repaired
        assert 'APP_PORT=8123\n' in repaired
        assert 'DJANGO_SECRET_KEY=""' not in repaired
        assert 'POSTGRES_ADMIN_PASSWORD=' in repaired
        before=target.read_bytes();run();assert target.read_bytes()==before
    if os.name=='nt':
        # Exercise cmd -> PowerShell -> setup with a Docker CLI stand-in.
        # Real containers are exercised separately by the Compose CI job.
        folder=Path(temp)/'Windows ZIP with spaces'
        (folder/'scripts').mkdir(parents=True)
        mocks=Path(temp)/'mock-cli';mocks.mkdir()
        for name in ('create_env.ps1','start.ps1'):
            shutil.copyfile(root/'scripts'/name,folder/'scripts'/name)
        for name in ('.env.example','run_windows.bat'):
            shutil.copyfile(root/name,folder/name)
        (mocks/'docker.cmd').write_bytes(b'@echo off\r\necho %*>> "%MONITOR_DOCKER_LOG%"\r\nexit /b 0\r\n')
        harness=Path(temp)/'launch.ps1'
        harness.write_text('param($Project)\n& (Join-Path $Project "run_windows.bat") -NoBrowser -SkipAdmin\nexit $LASTEXITCODE\n',encoding='ascii')
        env=os.environ.copy();env['PATH']=str(mocks)+os.pathsep+env['PATH']
        env['MONITOR_DOCKER_LOG']=str(Path(temp)/'docker-calls.log')
        result=subprocess.run([shell,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(harness),str(folder)],env=env,capture_output=True)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        assert b'Ready: http://127.0.0.1:8000/' in result.stdout
        assert (folder/'.env').is_file()
        calls=Path(env['MONITOR_DOCKER_LOG']).read_text()
        assert 'compose config --quiet' in calls
        assert 'compose up -d --wait db' in calls
        assert 'compose exec -T db sh /docker-entrypoint-initdb.d/10-app.sh' in calls
        assert calls.index('compose up -d --wait db') < calls.index('compose exec -T db sh') < calls.index('compose up --build -d --wait app')
        assert 'compose up --build -d --wait app' in calls
        assert 'bootstrap_postgres --load-if-empty' in calls
print('Startup checks passed: fresh ZIP, spaces, distinct secrets, no secret output, repeat and incomplete .env.')
