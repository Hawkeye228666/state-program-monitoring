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
print('Startup checks passed: fresh ZIP, spaces, distinct secrets, no secret output, repeat and incomplete .env.')
